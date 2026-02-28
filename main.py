#!/usr/bin/env python3
"""
多频道推送工作流 - 主程序入口 (v2.0)

功能:
  每天早上推送三条独立消息到钉钉群:
    1. 🚀 航天领域最新文献（Semantic Scholar）
    2. 🤖 机器人与AI领域最新文献（Semantic Scholar）
    3. 📈 全球经济新闻与市场分析（DuckDuckGo + AI）

使用方式:
  python main.py                       # 推送全部3个频道
  python main.py --channel aerospace   # 仅推送航天频道
  python main.py --channel robotics    # 仅推送机器人AI频道
  python main.py --channel finance     # 仅推送财经频道
  python main.py --dry-run             # 试运行（不发送）
  python main.py --days 3              # 文献回溯3天
  python main.py --review              # 审核模式（文献频道）
"""

import sys
import os
import argparse
import logging

sys.path.insert(0, os.path.dirname(__file__))

from src.utils import load_config, setup_logging, get_date_str

logger = logging.getLogger("main")


def parse_args():
    parser = argparse.ArgumentParser(description="多频道推送工作流 v2.0")
    parser.add_argument(
        "--config", type=str, default=None,
        help="配置文件路径 (默认: config.yaml)"
    )
    parser.add_argument(
        "--channel", type=str, default="all",
        choices=["aerospace", "robotics", "finance", "all"],
        help="推送频道: aerospace, robotics, finance, all (默认: all)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="试运行模式: 只生成内容，不发送推送"
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="文献回溯天数 (默认: 7，Semantic Scholar 索引有延迟)"
    )
    parser.add_argument(
        "--no-trends", action="store_true",
        help="跳过研究热点分析"
    )
    parser.add_argument(
        "--download-pdf", action="store_true",
        help="下载精选论文的PDF到本地"
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="跳过缓存去重（强制推送所有论文）"
    )
    parser.add_argument(
        "--review", action="store_true",
        help="审核模式: 文献频道生成后等待审核"
    )
    parser.add_argument(
        "--review-url", type=str, default="",
        help="审核面板地址"
    )
    return parser.parse_args()


def run_paper_channel(config: dict, channel_name: str, channel_config: dict,
                      args, date_str: str) -> bool:
    """
    运行论文类频道（航天 / 机器人AI）

    Returns:
        是否成功
    """
    from src.semantic_scholar import SemanticScholarFetcher
    from src.analyzer import PaperAnalyzer
    from src.template import ArticleGenerator
    from src.pusher import DingTalkPusher, EmailPusher
    from src.cache import PaperCache

    channel_display = channel_config.get("name", channel_name)
    logger.info(f"\n{'=' * 50}")
    logger.info(f"📡 频道: {channel_display}")
    logger.info(f"{'=' * 50}")

    # Step 1: 从 Semantic Scholar 获取论文
    logger.info("📥 Step 1: 从 Semantic Scholar 获取论文...")
    try:
        fetcher = SemanticScholarFetcher(config)
        papers = fetcher.fetch_channel_papers(channel_config, days=args.days)
        logger.info(f"  获取到 {len(papers)} 篇论文")
    except Exception as e:
        logger.error(f"  ❌ 论文获取失败: {e}")
        return False

    if not papers:
        logger.warning(f"  ⚠️ {channel_display} 今日没有获取到论文")
        return False

    total_fetched = len(papers)

    # Step 2: 缓存去重
    cache = PaperCache()
    if not args.no_cache:
        logger.info("🗃️ Step 2: 缓存去重...")
        cache.cleanup()
        papers = cache.filter_new(papers)
        logger.info(f"  过滤后剩余 {len(papers)} 篇新论文")
        if not papers:
            logger.warning(f"  ⚠️ 所有论文已推送过")
            return True  # 不是错误
    else:
        logger.info("⏭️ Step 2: 跳过缓存去重")

    # Step 3: AI 分析筛选（使用频道专属的 reviewer persona）
    logger.info("🤖 Step 3: AI 分析论文质量...")

    # 预筛选：如果论文太多，先按引用数排序取 top N 再送 AI 分析
    max_for_ai = channel_config.get("max_papers", 8) * 5  # 分析量 = 推送量 × 5
    if len(papers) > max_for_ai:
        logger.info(f"  📊 预筛选: {len(papers)} 篇 → 取引用数 Top {max_for_ai} 送 AI 分析")
        # 按引用数降序排列（_citation_count 是 S2 解析时附加的）
        papers.sort(key=lambda p: getattr(p, '_citation_count', 0), reverse=True)
        papers = papers[:max_for_ai]

    try:
        # 创建频道专属的分析器配置
        channel_analyzer_config = {**config}
        # 覆盖评分阈值和数量限制
        if "research" not in channel_analyzer_config:
            channel_analyzer_config["research"] = {}
        channel_analyzer_config["research"]["score_threshold"] = channel_config.get("score_threshold", 6)
        channel_analyzer_config["research"]["max_papers"] = channel_config.get("max_papers", 8)

        analyzer = PaperAnalyzer(channel_analyzer_config)
        # 设置频道专属的评审人角色
        reviewer_persona = channel_config.get("reviewer_persona", "")
        if reviewer_persona:
            analyzer._channel_persona = reviewer_persona

        selected_papers = analyzer.analyze_and_filter(papers)
        logger.info(f"  精选 {len(selected_papers)} 篇高质量论文")
    except Exception as e:
        logger.error(f"  ❌ AI 分析失败: {e}")
        return False

    if not selected_papers:
        logger.warning(f"  ⚠️ 没有论文通过质量筛选")
        return True

    # Step 4: 研究热点分析
    trends = ""
    include_trends = config.get("article", {}).get("include_trends", True) and not args.no_trends
    if include_trends:
        logger.info("🔥 Step 4: 生成研究热点分析...")
        try:
            trends = analyzer.generate_trends(selected_papers)
        except Exception as e:
            logger.warning(f"  ⚠️ 热点分析失败: {e}")
    else:
        logger.info("⏭️ Step 4: 跳过热点分析")

    # Step 5: 生成文章标题和内容
    logger.info("📝 Step 5: 生成文章...")
    try:
        title = f"{channel_display} · {date_str}"
        try:
            ai_title = analyzer.generate_article_title(selected_papers, date_str)
            title = f"{channel_display} | {ai_title}"
        except Exception:
            pass

        generator = ArticleGenerator(config)
        html_content = generator.generate(
            papers=selected_papers,
            trends=trends,
            title=title,
            total_fetched=total_fetched,
            date_str=date_str,
        )
        plain_text = generator.generate_plain_text(
            papers=selected_papers,
            trends=trends,
            title=title,
            date_str=date_str,
        )
    except Exception as e:
        logger.error(f"  ❌ 文章生成失败: {e}")
        return False

    # Step 6: 推送
    if args.dry_run:
        logger.info("🏃 试运行模式，跳过推送")
        logger.info(f"📄 标题: {title}")
        logger.info(f"📄 预览:\n{plain_text[:300]}")
        return True

    if args.review:
        logger.info("📋 审核模式 - 保存待审核文章...")
        try:
            from review_server import save_pending_article
            avg_score = "%.1f" % (sum(p.score for p in selected_papers) / len(selected_papers))
            article_id = save_pending_article(
                title=title,
                html_content=html_content,
                papers=selected_papers,
                date_str=date_str,
                avg_score=avg_score,
                sources=["Semantic Scholar"]
            )
            logger.info(f"  ✅ 待审核文章: {article_id}")
        except Exception as e:
            logger.error(f"  ❌ 保存失败: {e}")

    # 钉钉推送
    push_success = False
    dingtalk_config = config.get("dingtalk", {})
    if dingtalk_config.get("webhook_url"):
        try:
            dt_pusher = DingTalkPusher(config)
            review_url = args.review_url or config.get("review", {}).get("url", "")
            dt_pusher.send_paper_card(
                title=title,
                papers=selected_papers,
                trends=trends,
                date_str=date_str,
                review_url=f"{review_url}/preview/{channel_name}" if review_url and args.review else ""
            )
            logger.info("  ✅ 钉钉推送成功")
            push_success = True
        except Exception as e:
            logger.warning(f"  ⚠️ 钉钉推送失败: {e}")

    # 邮件推送
    email_config = config.get("email", {})
    if email_config.get("sender_email") and email_config.get("sender_password"):
        try:
            pusher = EmailPusher(config)
            prefix = "[待审核] " if args.review else ""
            pusher.send(subject=f"{prefix}{title}", html_content=html_content, plain_text=plain_text)
            logger.info("  ✅ 邮件推送成功")
            push_success = True
        except Exception as e:
            logger.warning(f"  ⚠️ 邮件推送失败: {e}")

    # 更新缓存
    if not args.no_cache:
        cache.mark_pushed(selected_papers)

    return push_success


def run_finance_channel(config: dict, args, date_str: str) -> bool:
    """
    运行财经频道

    Returns:
        是否成功
    """
    from src.news_fetcher import NewsFetcher
    from src.pusher import DingTalkPusher

    channel_config = config.get("channels", {}).get("finance", {})
    channel_display = channel_config.get("name", "📈 全球财经早报")

    logger.info(f"\n{'=' * 50}")
    logger.info(f"📡 频道: {channel_display}")
    logger.info(f"{'=' * 50}")

    # 获取财经数据
    logger.info("📈 获取全球财经数据...")
    try:
        news_fetcher = NewsFetcher(config)
        report = news_fetcher.fetch_all()
    except Exception as e:
        logger.error(f"  ❌ 财经数据获取失败: {e}")
        return False

    if args.dry_run:
        logger.info("🏃 试运行模式，跳过推送")
        logger.info(f"📄 标题: {report.title}")
        msg = news_fetcher.generate_dingtalk_message(report)
        logger.info(f"📄 预览:\n{msg[:500]}")
        return True

    # 钉钉推送
    push_success = False
    dingtalk_config = config.get("dingtalk", {})
    if dingtalk_config.get("webhook_url"):
        try:
            dt_pusher = DingTalkPusher(config)
            md_message = news_fetcher.generate_dingtalk_message(report)

            # 使用 ActionCard 格式推送
            data = {
                "msgtype": "actionCard",
                "actionCard": {
                    "title": f"📈 {report.title}",
                    "text": md_message,
                    "singleTitle": "📊 查看详细分析",
                    "singleURL": "https://finance.yahoo.com/"
                }
            }
            result = dt_pusher._post(data)
            if result:
                logger.info("  ✅ 钉钉财经推送成功")
                push_success = True
            else:
                logger.error("  ❌ 钉钉财经推送失败")
        except Exception as e:
            logger.warning(f"  ⚠️ 钉钉推送失败: {e}")

    return push_success


def main():
    args = parse_args()

    # 加载配置
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"❌ 配置文件加载失败: {e}")
        sys.exit(1)

    setup_logging(config)
    date_str = get_date_str()

    logger.info(f"{'=' * 60}")
    logger.info(f"📰 多频道推送工作流 v2.0 启动 - {date_str}")
    logger.info(f"   频道: {args.channel} | 回溯: {args.days}天 | 模式: {'试运行' if args.dry_run else '正式'}")
    logger.info(f"{'=' * 60}")

    channels_config = config.get("channels", {})
    results = {}

    # 频道 1: 航天领域文献
    if args.channel in ("aerospace", "all"):
        ch_config = channels_config.get("aerospace", {})
        if ch_config.get("enabled", True):
            try:
                success = run_paper_channel(config, "aerospace", ch_config, args, date_str)
                results["aerospace"] = "✅" if success else "⚠️"
            except Exception as e:
                logger.error(f"航天频道异常: {e}")
                results["aerospace"] = "❌"

    # 频道 2: 机器人与AI
    if args.channel in ("robotics", "all"):
        ch_config = channels_config.get("robotics", {})
        if ch_config.get("enabled", True):
            try:
                success = run_paper_channel(config, "robotics", ch_config, args, date_str)
                results["robotics"] = "✅" if success else "⚠️"
            except Exception as e:
                logger.error(f"机器人AI频道异常: {e}")
                results["robotics"] = "❌"

    # 频道 3: 全球财经
    if args.channel in ("finance", "all"):
        ch_config = channels_config.get("finance", {})
        if ch_config.get("enabled", True):
            try:
                success = run_finance_channel(config, args, date_str)
                results["finance"] = "✅" if success else "⚠️"
            except Exception as e:
                logger.error(f"财经频道异常: {e}")
                results["finance"] = "❌"

    # 汇总
    logger.info(f"\n{'=' * 60}")
    logger.info(f"🎉 推送工作流完成!")
    for ch, status in results.items():
        ch_name = channels_config.get(ch, {}).get("name", ch)
        logger.info(f"  {status} {ch_name}")
    logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    main()

