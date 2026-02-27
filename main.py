#!/usr/bin/env python3
"""
论文推送工作流 - 主程序入口 (增强版)

功能:
  1. 从 arXiv + Semantic Scholar 多数据源抓取最新论文
  2. 缓存去重，避免重复推送
  3. 使用 DeepSeek AI 进行论文评价和筛选
  4. 生成研究热点分析
  5. 输出微信公众号格式的HTML文章
  6. 通过邮件/钉钉/企微推送
  7. 可选下载论文PDF

使用方式:
  python main.py                    # 正常运行（直接推送）
  python main.py --review           # 审核模式（生成待审核，推送钉钉卡片）
  python main.py --dry-run          # 试运行（不发邮件）
  python main.py --config xxx.yaml  # 指定配置文件
  python main.py --days 3           # 获取最近3天的论文
  python main.py --download-pdf     # 同时下载论文PDF
  python main.py --source arxiv     # 仅使用arXiv数据源
  python main.py --source all       # 使用全部数据源
"""

import sys
import os
import argparse
import logging

# 确保项目根目录在 Python Path 中
sys.path.insert(0, os.path.dirname(__file__))

from src.fetcher import PaperFetcher
from src.analyzer import PaperAnalyzer
from src.template import ArticleGenerator
from src.pusher import EmailPusher, DingTalkPusher, WeComPusher
from src.cache import PaperCache
from src.utils import load_config, setup_logging, get_date_str

logger = logging.getLogger("main")


def parse_args():
    parser = argparse.ArgumentParser(description="论文推送工作流")
    parser.add_argument(
        "--config", type=str, default=None,
        help="配置文件路径 (默认: config.yaml)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="试运行模式: 只生成文章，不发送推送"
    )
    parser.add_argument(
        "--days", type=int, default=2,
        help="回溯天数 (默认: 2)"
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
        "--source", type=str, default="all",
        choices=["arxiv", "semantic", "crossref", "openalex", "all"],
        help="数据源选择: arxiv, semantic, crossref, openalex, all (默认: all)"
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="跳过缓存去重（强制推送所有论文）"
    )
    parser.add_argument(
        "--review", action="store_true",
        help="审核模式: 生成文章后等待审核，而非直接推送"
    )
    parser.add_argument(
        "--review-url", type=str, default="",
        help="审核面板地址（如 http://你的IP:5678），用于钉钉卡片按钮"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # ===== Step 0: 加载配置 =====
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"❌ 配置文件加载失败: {e}")
        sys.exit(1)

    setup_logging(config)
    date_str = get_date_str()
    logger.info(f"{'=' * 50}")
    logger.info(f"📰 论文推送工作流启动 - {date_str}")
    logger.info(f"   数据源: {args.source} | 回溯: {args.days}天 | 模式: {'试运行' if args.dry_run else '正式运行'}")
    logger.info(f"{'=' * 50}")

    # ===== Step 1: 多数据源抓取论文 =====
    logger.info("📥 Step 1/7: 抓取最新论文...")
    papers = []

    # arXiv 数据源
    if args.source in ("arxiv", "all"):
        try:
            fetcher = PaperFetcher(config)
            arxiv_papers = fetcher.fetch_and_sort(days=args.days)
            papers.extend(arxiv_papers)
            logger.info(f"  📦 arXiv: {len(arxiv_papers)} 篇")
        except Exception as e:
            logger.error(f"  ❌ arXiv 抓取失败: {e}")

    # Semantic Scholar 数据源
    if args.source in ("semantic", "all"):
        try:
            from src.semantic_scholar import SemanticScholarFetcher
            ss_fetcher = SemanticScholarFetcher(config)
            ss_papers = ss_fetcher.fetch_recent_papers(days=max(args.days, 7))
            papers.extend(ss_papers)
            logger.info(f"  📦 Semantic Scholar: {len(ss_papers)} 篇")
        except ImportError:
            logger.debug("Semantic Scholar 模块未安装，跳过")
        except Exception as e:
            logger.warning(f"  ⚠️ Semantic Scholar 抓取失败: {e}")

    # CrossRef 数据源（正式期刊论文）
    if args.source in ("crossref", "all"):
        try:
            from src.crossref import CrossRefFetcher
            cr_fetcher = CrossRefFetcher(config)
            cr_papers = cr_fetcher.fetch_recent_papers(days=max(args.days, 7))
            papers.extend(cr_papers)
            logger.info(f"  📦 CrossRef: {len(cr_papers)} 篇")
        except Exception as e:
            logger.warning(f"  ⚠️ CrossRef 抓取失败: {e}")

    # OpenAlex 数据源
    if args.source in ("openalex", "all"):
        try:
            from src.openalex import OpenAlexFetcher
            oa_fetcher = OpenAlexFetcher(config)
            oa_papers = oa_fetcher.fetch_recent_papers(days=max(args.days, 7))
            papers.extend(oa_papers)
            logger.info(f"  📦 OpenAlex: {len(oa_papers)} 篇")
        except Exception as e:
            logger.warning(f"  ⚠️ OpenAlex 抓取失败: {e}")

    # 全局去重（按 arXiv ID）
    seen = set()
    unique_papers = []
    for p in papers:
        if p.arxiv_id not in seen:
            seen.add(p.arxiv_id)
            unique_papers.append(p)
    papers = unique_papers

    total_fetched = len(papers)
    logger.info(f"✅ 共获取 {total_fetched} 篇去重后的论文")

    if not papers:
        logger.warning("⚠️ 今日没有获取到相关论文，工作流结束")
        sys.exit(0)

    # ===== Step 2: 缓存去重 =====
    cache = PaperCache()
    if not args.no_cache:
        logger.info("🗃️ Step 2/7: 缓存去重...")
        cache.cleanup()  # 清理过期缓存
        papers = cache.filter_new(papers)
        logger.info(f"✅ 过滤后剩余 {len(papers)} 篇新论文")
        if not papers:
            logger.warning("⚠️ 所有论文都已推送过，工作流结束")
            sys.exit(0)
    else:
        logger.info("⏭️ Step 2/7: 跳过缓存去重")

    # ===== Step 3: AI分析筛选 =====
    logger.info("🤖 Step 3/7: AI分析论文质量...")
    try:
        analyzer = PaperAnalyzer(config)
        selected_papers = analyzer.analyze_and_filter(papers)
        logger.info(f"✅ 精选 {len(selected_papers)} 篇高质量论文")
    except Exception as e:
        logger.error(f"❌ AI分析失败: {e}")
        sys.exit(1)

    if not selected_papers:
        logger.warning("⚠️ 没有论文通过质量筛选，工作流结束")
        sys.exit(0)

    # ===== Step 4: 研究热点分析 =====
    trends = ""
    include_trends = config.get("article", {}).get("include_trends", True) and not args.no_trends
    if include_trends:
        logger.info("🔥 Step 4/7: 生成研究热点分析...")
        try:
            trends = analyzer.generate_trends(selected_papers)
            logger.info("✅ 研究热点分析完成")
        except Exception as e:
            logger.warning(f"⚠️ 热点分析失败（不影响推送）: {e}")
    else:
        logger.info("⏭️ Step 4/7: 跳过研究热点分析")

    # ===== Step 5: 生成文章 =====
    logger.info("📝 Step 5/7: 生成公众号文章...")
    try:
        title = analyzer.generate_article_title(selected_papers, date_str)
        logger.info(f"📌 文章标题: {title}")

        generator = ArticleGenerator(config)
        html_content = generator.generate(
            papers=selected_papers,
            trends=trends,
            title=title,
            total_fetched=total_fetched,
            date_str=date_str
        )
        plain_text = generator.generate_plain_text(
            papers=selected_papers,
            trends=trends,
            title=title,
            date_str=date_str
        )
        logger.info("✅ 公众号文章生成完成")
    except Exception as e:
        logger.error(f"❌ 文章生成失败: {e}")
        sys.exit(1)

    # ===== Step 6: PDF下载（可选）=====
    if args.download_pdf:
        logger.info("📥 Step 6/7: 下载论文PDF...")
        try:
            from src.downloader import PDFDownloader
            downloader = PDFDownloader(config)
            pdf_results = downloader.download_papers(selected_papers)
            logger.info(f"✅ 已下载 {len(pdf_results)} 篇PDF，总大小: {downloader.get_total_size()}")
        except Exception as e:
            logger.warning(f"⚠️ PDF下载失败（不影响推送）: {e}")
    else:
        logger.info("⏭️ Step 6/7: 跳过PDF下载")

    # ===== Step 7: 推送 =====
    if args.dry_run:
        logger.info("🏃 Step 7/7: 试运行模式，跳过推送")
        logger.info(f"📄 文章预览 (前500字):\n{plain_text[:500]}")
    elif args.review:
        # ===== 审核模式: 保存待审核 + 发钉钉卡片 =====
        logger.info("📋 Step 7/7: 审核模式 - 保存待审核文章...")
        try:
            from review_server import save_pending_article
            avg_score = "%.1f" % (sum(p.score for p in selected_papers) / len(selected_papers))
            sources_used = []
            if args.source == "all":
                sources_used = ["arXiv", "CrossRef", "OpenAlex", "S2"]
            else:
                sources_used = [args.source]
            article_id = save_pending_article(
                title=title,
                html_content=html_content,
                papers=selected_papers,
                date_str=date_str,
                avg_score=avg_score,
                sources=sources_used
            )
            logger.info(f"  ✅ 待审核文章已保存: {article_id}")
        except Exception as e:
            logger.error(f"  ❌ 保存待审核文章失败: {e}")

        # 发送钉钉卡片通知
        dingtalk_config = config.get("dingtalk", {})
        if dingtalk_config.get("webhook_url"):
            try:
                dt_pusher = DingTalkPusher(config)
                review_url = args.review_url or config.get("review", {}).get("url", "")
                if dt_pusher.send_paper_card(
                    title=title,
                    papers=selected_papers,
                    trends=trends,
                    date_str=date_str,
                    review_url=f"{review_url}/preview/{article_id}" if review_url else ""
                ):
                    logger.info("  ✅ 钉钉审核卡片已推送")
                else:
                    logger.error("  ❌ 钉钉推送失败")
            except Exception as e:
                logger.warning(f"  ⚠️ 钉钉推送失败: {e}")
        else:
            logger.info("  ℹ️ 未配置钉钉，审核文章请访问 Web 面板")

        # 邮件也发一份（方便预览）
        email_config = config.get("email", {})
        if email_config.get("sender_email") and email_config.get("sender_password"):
            try:
                pusher = EmailPusher(config)
                if pusher.send(subject=f"[待审核] {title}", html_content=html_content, plain_text=plain_text):
                    logger.info("  ✅ 审核预览邮件已发送")
                else:
                    logger.warning("  ⚠️ 审核预览邮件发送失败")
            except Exception as e:
                logger.warning(f"  ⚠️ 邮件发送失败: {e}")

        logger.info(f"  📋 请访问审核面板或通过钉钉完成审核")
    else:
        logger.info("📧 Step 7/7: 发送推送...")
        push_success = False

        # 邮件推送
        email_config = config.get("email", {})
        if email_config.get("sender_email") and email_config.get("sender_password"):
            try:
                pusher = EmailPusher(config)
                if pusher.send(subject=title, html_content=html_content, plain_text=plain_text):
                    logger.info("  ✅ 邮件推送成功")
                    push_success = True
                else:
                    logger.error("  ❌ 邮件推送失败")
            except Exception as e:
                logger.error(f"  ❌ 邮件推送异常: {e}")

        # 钉钉推送（如已配置）
        dingtalk_config = config.get("dingtalk", {})
        if dingtalk_config.get("webhook_url"):
            try:
                dt_pusher = DingTalkPusher(config)
                dt_pusher.send_paper_card(
                    title=title,
                    papers=selected_papers,
                    trends=trends,
                    date_str=date_str
                )
                logger.info("  ✅ 钉钉推送成功")
                push_success = True
            except Exception as e:
                logger.warning(f"  ⚠️ 钉钉推送失败: {e}")

        # 企业微信推送（如已配置）
        wecom_config = config.get("wecom", {})
        if wecom_config.get("webhook_url"):
            try:
                wc_pusher = WeComPusher(webhook_url=wecom_config["webhook_url"])
                if wc_pusher.send(content=plain_text[:4000]):
                    logger.info("  ✅ 企业微信推送成功")
                    push_success = True
            except Exception as e:
                logger.warning(f"  ⚠️ 企业微信推送失败: {e}")

        if not push_success:
            logger.error("❌ 所有推送渠道均失败")
            sys.exit(1)

    # ===== 更新缓存 =====
    if not args.no_cache:
        cache.mark_pushed(selected_papers)

    # ===== 完成 =====
    logger.info(f"{'=' * 50}")
    logger.info(f"🎉 工作流完成! 共推送 {len(selected_papers)} 篇论文")
    stats = cache.get_stats()
    logger.info(f"📊 累计推送: {stats['total_cached']} 篇 | 上次推送: {stats['last_push']}")
    logger.info(f"{'=' * 50}")


if __name__ == "__main__":
    main()
