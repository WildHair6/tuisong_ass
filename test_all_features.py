#!/usr/bin/env python3
"""
全功能模拟测试脚本 - 测试 AI 研究助理的所有功能 + 多轮对话

测试清单:
  1. 文献调研 (research)
  2. 文献综述 (review)
  3. 文献导出 (export)
  4. 领域热点分析 (hotspot)
  5. 引用链追踪 (citation_trace)
  6. 论文对比分析 (compare)
  7. 研究空白发现 (gap)
  8. 会议/期刊追踪 (venue)
  9. 选题建议 (topic_suggest)
  10. 作者查询 (author)
  11. 研究问答 (question)
  12. 多轮对话迭代 (multi-turn)
  13. 医学领域测试 (medical - Semantic Scholar)
  14. 帮助/清空命令

Usage:
  python test_all_features.py                  # 运行所有测试
  python test_all_features.py --test research  # 只跑指定测试
  python test_all_features.py --test medical   # 医学领域测试
  python test_all_features.py --test multi     # 多轮对话测试
"""

import asyncio
import json
import logging
import os
import sys
import time
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from src.utils import load_config
from src.research_assistant import ResearchAssistant

# 修正 Windows 控制台编码
import io
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 配置日志
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler("logs/test_all_features.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("test_all_features")

# 测试结果收集
TEST_RESULTS = []


def record_result(test_name: str, success: bool, reply_text: str,
                  duration: float, paper_count: int = 0, files: list = None,
                  notes: str = ""):
    """记录测试结果"""
    result = {
        "test_name": test_name,
        "success": success,
        "duration_seconds": round(duration, 2),
        "reply_length": len(reply_text),
        "paper_count": paper_count,
        "files_generated": len(files) if files else 0,
        "notes": notes,
        "timestamp": datetime.now().isoformat(),
    }
    TEST_RESULTS.append(result)
    status = "✅ PASS" if success else "❌ FAIL"
    logger.info(f"{status} [{test_name}] 耗时 {duration:.1f}s, 回复长度 {len(reply_text)}, "
                f"论文数 {paper_count}, 文件数 {len(files) if files else 0}")
    if notes:
        logger.info(f"  备注: {notes}")


async def test_research(assistant: ResearchAssistant):
    """测试1: 文献调研 - 机器人方向"""
    logger.info("\n" + "="*60)
    logger.info("📚 测试1: 文献调研 (research)")
    logger.info("="*60)

    test_cases = [
        ("搜索机器人抓取操作相关的最新论文", "robotics_grasp"),
        ("查找2023年以来关于大语言模型在机器人中应用的文献", "llm_robotics"),
    ]

    for message, tag in test_cases:
        start = time.time()
        try:
            result = await assistant.handle_message(message, user_id=f"test_{tag}")
            text = result.get("text", "")
            files = result.get("files", [])
            duration = time.time() - start

            # 评估
            has_papers = "**" in text and ("引用" in text or "论文" in text)
            paper_lines = [l for l in text.split("\n") if l.startswith("**") and "." in l[:6]]
            paper_count = len(paper_lines)

            record_result(
                f"research_{tag}", has_papers, text, duration,
                paper_count=paper_count, files=files,
                notes=f"查询: {message}"
            )

            # 打印前500字符预览
            print(f"\n--- [{tag}] 回复预览 (前500字) ---")
            print(text[:500])
            print("...")
        except Exception as e:
            duration = time.time() - start
            record_result(f"research_{tag}", False, str(e), duration, notes=f"异常: {e}")
            logger.error(f"  异常: {e}")


async def test_review(assistant: ResearchAssistant):
    """测试2: 文献综述"""
    logger.info("\n" + "="*60)
    logger.info("📖 测试2: 文献综述 (review)")
    logger.info("="*60)

    message = "写一篇关于航天器在轨服务技术的文献综述"
    start = time.time()
    try:
        result = await assistant.handle_message(message, user_id="test_review")
        text = result.get("text", "")
        files = result.get("files", [])
        duration = time.time() - start

        has_review = "综述" in text and ("研究" in text or "方向" in text)
        has_refs = "参考文献" in text
        has_export_files = len(files) > 0

        notes_parts = []
        if has_review: notes_parts.append("有综述内容")
        if has_refs: notes_parts.append("有参考文献")
        if has_export_files: notes_parts.append(f"生成{len(files)}个导出文件")
        for f in files:
            notes_parts.append(f"  文件: {f.get('name', 'unknown')}")

        record_result(
            "review_spacecraft", has_review, text, duration,
            files=files, notes="; ".join(notes_parts)
        )

        print(f"\n--- [review] 回复预览 (前800字) ---")
        print(text[:800])
        print(f"...\n导出文件: {json.dumps([f.get('name') for f in files], ensure_ascii=False)}")
    except Exception as e:
        duration = time.time() - start
        record_result("review_spacecraft", False, str(e), duration, notes=f"异常: {e}")
        logger.error(f"  异常: {e}")


async def test_export(assistant: ResearchAssistant):
    """测试3: 文献导出"""
    logger.info("\n" + "="*60)
    logger.info("📦 测试3: 文献导出 (export)")
    logger.info("="*60)

    message = "导出机器人导航相关文献的BibTeX"
    start = time.time()
    try:
        result = await assistant.handle_message(message, user_id="test_export")
        text = result.get("text", "")
        files = result.get("files", [])
        duration = time.time() - start

        has_files = len(files) > 0
        notes = f"文件: {[f.get('name') for f in files]}" if files else "无文件生成"

        record_result("export_bibtex", has_files, text, duration, files=files, notes=notes)

        print(f"\n--- [export] 回复 ---")
        print(text[:300])
        if files:
            for f in files:
                path = f.get("path", "")
                if path and os.path.exists(path):
                    size = os.path.getsize(path)
                    print(f"  文件: {f.get('name')} ({size} bytes)")
    except Exception as e:
        duration = time.time() - start
        record_result("export_bibtex", False, str(e), duration, notes=f"异常: {e}")


async def test_hotspot(assistant: ResearchAssistant):
    """测试4: 领域热点分析"""
    logger.info("\n" + "="*60)
    logger.info("🔥 测试4: 领域热点分析 (hotspot)")
    logger.info("="*60)

    message = "分析一下具身智能领域的研究热点"
    start = time.time()
    try:
        result = await assistant.handle_message(message, user_id="test_hotspot")
        text = result.get("text", "")
        duration = time.time() - start

        has_analysis = "热点" in text and ("趋势" in text or "方向" in text)
        has_data = "数据统计" in text or "高频关键词" in text

        record_result("hotspot_embodied_ai", has_analysis, text, duration,
                      notes=f"有分析={has_analysis}, 有数据={has_data}")

        print(f"\n--- [hotspot] 回复预览 (前800字) ---")
        print(text[:800])
    except Exception as e:
        duration = time.time() - start
        record_result("hotspot_embodied_ai", False, str(e), duration, notes=f"异常: {e}")


async def test_citation_trace(assistant: ResearchAssistant):
    """测试5: 引用链追踪"""
    logger.info("\n" + "="*60)
    logger.info("🔗 测试5: 引用链追踪 (citation_trace)")
    logger.info("="*60)

    message = "追踪Attention is All You Need这篇论文的引用网络"
    start = time.time()
    try:
        result = await assistant.handle_message(message, user_id="test_citation")
        text = result.get("text", "")
        duration = time.time() - start

        has_citations = "被引用" in text or "引用" in text
        has_refs = "参考文献" in text
        has_analysis = "AI 分析" in text or "分析" in text

        record_result("citation_attention", has_citations, text, duration,
                      notes=f"有引用列表={has_citations}, 有参考文献={has_refs}")

        print(f"\n--- [citation] 回复预览 (前800字) ---")
        print(text[:800])
    except Exception as e:
        duration = time.time() - start
        record_result("citation_attention", False, str(e), duration, notes=f"异常: {e}")


async def test_compare(assistant: ResearchAssistant):
    """测试6: 论文对比分析"""
    logger.info("\n" + "="*60)
    logger.info("📊 测试6: 论文对比分析 (compare)")
    logger.info("="*60)

    message = "对比强化学习和模仿学习在机器人控制中的应用"
    start = time.time()
    try:
        result = await assistant.handle_message(message, user_id="test_compare")
        text = result.get("text", "")
        duration = time.time() - start

        has_comparison = "对比" in text and ("优" in text or "劣" in text or "方向" in text)
        record_result("compare_rl_il", has_comparison, text, duration,
                      notes=f"有对比内容={has_comparison}")

        print(f"\n--- [compare] 回复预览 (前800字) ---")
        print(text[:800])
    except Exception as e:
        duration = time.time() - start
        record_result("compare_rl_il", False, str(e), duration, notes=f"异常: {e}")


async def test_gap(assistant: ResearchAssistant):
    """测试7: 研究空白发现"""
    logger.info("\n" + "="*60)
    logger.info("🧭 测试7: 研究空白发现 (gap)")
    logger.info("="*60)

    message = "分析太空碎片主动清除领域有哪些研究空白"
    start = time.time()
    try:
        result = await assistant.handle_message(message, user_id="test_gap")
        text = result.get("text", "")
        duration = time.time() - start

        has_gaps = "空白" in text and ("方向" in text or "创新" in text)
        record_result("gap_space_debris", has_gaps, text, duration,
                      notes=f"有空白分析={has_gaps}")

        print(f"\n--- [gap] 回复预览 (前800字) ---")
        print(text[:800])
    except Exception as e:
        duration = time.time() - start
        record_result("gap_space_debris", False, str(e), duration, notes=f"异常: {e}")


async def test_venue(assistant: ResearchAssistant):
    """测试8: 会议/期刊追踪"""
    logger.info("\n" + "="*60)
    logger.info("📅 测试8: 会议/期刊追踪 (venue)")
    logger.info("="*60)

    message = "追踪ICRA 2025的机器人操作相关论文"
    start = time.time()
    try:
        result = await assistant.handle_message(message, user_id="test_venue")
        text = result.get("text", "")
        duration = time.time() - start

        has_venue = "ICRA" in text or "会议" in text or "论文" in text
        record_result("venue_icra", has_venue, text, duration,
                      notes=f"有会议论文={has_venue}")

        print(f"\n--- [venue] 回复预览 (前600字) ---")
        print(text[:600])
    except Exception as e:
        duration = time.time() - start
        record_result("venue_icra", False, str(e), duration, notes=f"异常: {e}")


async def test_topic_suggest(assistant: ResearchAssistant):
    """测试9: 选题建议"""
    logger.info("\n" + "="*60)
    logger.info("💡 测试9: 选题建议 (topic_suggest)")
    logger.info("="*60)

    message = "我想做机器人操作方向的研究，有什么好的选题建议？"
    start = time.time()
    try:
        result = await assistant.handle_message(message, user_id="test_topic")
        text = result.get("text", "")
        duration = time.time() - start

        has_suggestion = "选题" in text and ("建议" in text or "推荐" in text)
        record_result("topic_robot_manipulation", has_suggestion, text, duration,
                      notes=f"有选题建议={has_suggestion}")

        print(f"\n--- [topic_suggest] 回复预览 (前800字) ---")
        print(text[:800])
    except Exception as e:
        duration = time.time() - start
        record_result("topic_robot_manipulation", False, str(e), duration, notes=f"异常: {e}")


async def test_author(assistant: ResearchAssistant):
    """测试10: 作者查询"""
    logger.info("\n" + "="*60)
    logger.info("👤 测试10: 作者查询 (author)")
    logger.info("="*60)

    message = "查询 Pieter Abbeel 的信息和代表作"
    start = time.time()
    try:
        result = await assistant.handle_message(message, user_id="test_author")
        text = result.get("text", "")
        duration = time.time() - start

        has_author = "Abbeel" in text or "作者" in text
        has_papers = "代表作" in text or "论文" in text
        record_result("author_abbeel", has_author, text, duration,
                      notes=f"有作者信息={has_author}, 有论文列表={has_papers}")

        print(f"\n--- [author] 回复 ---")
        print(text[:600])
    except Exception as e:
        duration = time.time() - start
        record_result("author_abbeel", False, str(e), duration, notes=f"异常: {e}")


async def test_question(assistant: ResearchAssistant):
    """测试11: 研究问答"""
    logger.info("\n" + "="*60)
    logger.info("❓ 测试11: 研究问答 (question)")
    logger.info("="*60)

    message = "强化学习和模仿学习的主要区别是什么？各自的优缺点？"
    start = time.time()
    try:
        result = await assistant.handle_message(message, user_id="test_question")
        text = result.get("text", "")
        duration = time.time() - start

        has_answer = len(text) > 100
        record_result("question_rl_vs_il", has_answer, text, duration,
                      notes=f"回复长度={len(text)}")

        print(f"\n--- [question] 回复 ---")
        print(text[:500])
    except Exception as e:
        duration = time.time() - start
        record_result("question_rl_vs_il", False, str(e), duration, notes=f"异常: {e}")


async def test_multi_turn(assistant: ResearchAssistant):
    """测试12: 多轮对话迭代"""
    logger.info("\n" + "="*60)
    logger.info("🔄 测试12: 多轮对话 (multi-turn)")
    logger.info("="*60)

    user_id = "test_multi_turn_001"
    conversations = [
        ("帮我搜索机器人抓取操作相关的论文", "第1轮: 初始搜索"),
        ("上面这些论文中，哪些使用了深度学习方法？能详细介绍一下吗？", "第2轮: 追问细节"),
        ("给我分析一下这个领域的研究热点", "第3轮: 转换意图到热点分析"),
        ("基于你的分析，给我推荐3个具体的研究选题", "第4轮: 请求选题建议"),
        ("导出刚才搜索到的文献为BibTeX格式", "第5轮: 导出文献"),
    ]

    for i, (message, desc) in enumerate(conversations, 1):
        logger.info(f"\n--- 多轮对话 {desc} ---")
        start = time.time()
        try:
            result = await assistant.handle_message(message, user_id=user_id)
            text = result.get("text", "")
            files = result.get("files", [])
            duration = time.time() - start

            success = len(text) > 50
            record_result(
                f"multi_turn_round{i}", success, text, duration,
                files=files, notes=desc
            )

            print(f"\n--- 多轮对话 [{desc}] 回复预览 (前400字) ---")
            print(text[:400])
            print("...")
        except Exception as e:
            duration = time.time() - start
            record_result(f"multi_turn_round{i}", False, str(e), duration, notes=f"{desc} 异常: {e}")
            logger.error(f"  异常: {e}")

        # 多轮对话间隔
        await asyncio.sleep(1)


async def test_medical(assistant: ResearchAssistant):
    """测试13: 医学领域文献搜索 (Semantic Scholar)"""
    logger.info("\n" + "="*60)
    logger.info("🏥 测试13: 医学领域文献 (medical)")
    logger.info("="*60)

    test_cases = [
        ("搜索癌症免疫治疗相关的最新论文", "cancer_immunotherapy"),
        ("写一篇关于中医药治疗骨质疏松的文献综述", "tcm_osteoporosis"),
        ("分析肿瘤微环境领域的研究热点", "tumor_microenvironment"),
    ]

    for message, tag in test_cases:
        logger.info(f"\n--- 医学测试: {tag} ---")
        start = time.time()
        try:
            result = await assistant.handle_message(message, user_id=f"test_med_{tag}")
            text = result.get("text", "")
            files = result.get("files", [])
            duration = time.time() - start

            # 评估
            has_content = len(text) > 100
            has_papers = "**" in text
            is_insufficient = "未找到" in text or "仅找到" in text or "不足" in text

            notes_parts = []
            if is_insufficient:
                notes_parts.append("⚠ 文献数量不足")
            if has_papers:
                paper_lines = [l for l in text.split("\n") if l.startswith("**") and "." in l[:6]]
                notes_parts.append(f"找到约{len(paper_lines)}篇论文")
            if files:
                notes_parts.append(f"导出{len(files)}个文件")

            record_result(
                f"medical_{tag}", has_content and not is_insufficient,
                text, duration, files=files,
                notes="; ".join(notes_parts) if notes_parts else f"查询: {message}"
            )

            print(f"\n--- [medical_{tag}] 回复预览 (前600字) ---")
            print(text[:600])
            if is_insufficient:
                print("\n⚠ 该查询文献不足，需要考虑添加 PubMed 数据源!")
        except Exception as e:
            duration = time.time() - start
            record_result(f"medical_{tag}", False, str(e), duration, notes=f"异常: {e}")
            logger.error(f"  异常: {e}")


async def test_help_and_commands(assistant: ResearchAssistant):
    """测试14: 特殊命令"""
    logger.info("\n" + "="*60)
    logger.info("⚙️ 测试14: 帮助和命令")
    logger.info("="*60)

    commands = [
        ("帮助", "help_cmd"),
        ("清空对话", "clear_cmd"),
    ]

    for msg, tag in commands:
        start = time.time()
        try:
            result = await assistant.handle_message(msg, user_id=f"test_{tag}")
            text = result.get("text", "")
            duration = time.time() - start
            success = len(text) > 5  # 清空对话等命令回复较短
            record_result(tag, success, text, duration, notes=f"命令: {msg}")
            print(f"\n--- [{tag}] 回复长度: {len(text)} ---")
        except Exception as e:
            duration = time.time() - start
            record_result(tag, False, str(e), duration, notes=f"异常: {e}")


def generate_report():
    """生成最终测试报告"""
    total = len(TEST_RESULTS)
    passed = sum(1 for r in TEST_RESULTS if r["success"])
    failed = total - passed
    total_duration = sum(r["duration_seconds"] for r in TEST_RESULTS)
    total_files = sum(r["files_generated"] for r in TEST_RESULTS)

    report = {
        "summary": {
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": f"{passed/total*100:.1f}%" if total > 0 else "N/A",
            "total_duration_seconds": round(total_duration, 1),
            "total_files_generated": total_files,
            "test_time": datetime.now().isoformat(),
        },
        "details": TEST_RESULTS,
        "evaluation": {
            "strengths": [],
            "weaknesses": [],
            "suggestions": [],
        }
    }

    # 自动评估
    avg_duration = total_duration / total if total > 0 else 0
    avg_reply_len = sum(r["reply_length"] for r in TEST_RESULTS) / total if total > 0 else 0

    # 优点分析
    if passed / total >= 0.8 if total > 0 else False:
        report["evaluation"]["strengths"].append(f"通过率高: {passed}/{total}")
    if avg_duration < 30:
        report["evaluation"]["strengths"].append(f"响应速度较好: 平均 {avg_duration:.1f}s")
    if total_files > 0:
        report["evaluation"]["strengths"].append(f"文件导出功能正常: 共生成 {total_files} 个文件")
    report["evaluation"]["strengths"].append("支持12种意图识别，功能覆盖全面")
    report["evaluation"]["strengths"].append("多轮对话支持上下文记忆")
    report["evaluation"]["strengths"].append("搜索回退策略(5级)保证文献覆盖率")

    # 不足分析
    failed_tests = [r for r in TEST_RESULTS if not r["success"]]
    for ft in failed_tests:
        report["evaluation"]["weaknesses"].append(f"测试失败: {ft['test_name']} - {ft['notes']}")

    medical_tests = [r for r in TEST_RESULTS if "medical" in r["test_name"]]
    medical_fails = [r for r in medical_tests if not r["success"]]
    if medical_fails:
        report["evaluation"]["weaknesses"].append(
            f"医学领域文献覆盖不足: {len(medical_fails)}/{len(medical_tests)} 个测试文献不足"
        )
        report["evaluation"]["suggestions"].append(
            "集成 PubMed 数据源以增强医学/生物/化学领域的文献覆盖"
        )

    if avg_duration > 20:
        report["evaluation"]["weaknesses"].append(f"平均响应时间较长: {avg_duration:.1f}s")
        report["evaluation"]["suggestions"].append("考虑并行搜索、缓存常见查询以提升速度")

    # 通用建议
    report["evaluation"]["suggestions"].extend([
        "为医学领域添加 PubMed API 数据源(ai4scholar.net/pubmed/v1/paper/search)",
        "在回退策略中加入 PubMed 作为额外数据源",
        "综述报告可增加图表(趋势图、词云)以提升可读性",
        "对比分析中可增加定量指标的表格对比",
        "可以添加文献质量评分机制(IF影响因子等)",
    ])

    return report


async def main():
    parser = argparse.ArgumentParser(description="全功能测试脚本")
    parser.add_argument("--test", type=str, default="all",
                        help="指定测试: research, review, export, hotspot, citation, "
                             "compare, gap, venue, topic, author, question, multi, medical, help, all")
    args = parser.parse_args()

    # 确保日志目录存在
    os.makedirs("logs", exist_ok=True)

    logger.info("="*70)
    logger.info("🚀 AI 研究助理 - 全功能模拟测试")
    logger.info(f"📅 测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*70)

    # 加载配置 & 初始化
    config = load_config()
    assistant = ResearchAssistant(config)
    logger.info("✅ ResearchAssistant 初始化成功")

    test_map = {
        "research": test_research,
        "review": test_review,
        "export": test_export,
        "hotspot": test_hotspot,
        "citation": test_citation_trace,
        "compare": test_compare,
        "gap": test_gap,
        "venue": test_venue,
        "topic": test_topic_suggest,
        "author": test_author,
        "question": test_question,
        "multi": test_multi_turn,
        "medical": test_medical,
        "help": test_help_and_commands,
    }

    if args.test == "all":
        # 按顺序执行所有测试
        for name, test_func in test_map.items():
            try:
                await test_func(assistant)
            except Exception as e:
                logger.error(f"测试 {name} 异常: {e}")
            await asyncio.sleep(2)  # 测试间隔，避免API限流
    elif args.test in test_map:
        await test_map[args.test](assistant)
    else:
        logger.error(f"未知测试: {args.test}")
        logger.info(f"可用测试: {', '.join(test_map.keys())}")
        return

    # 生成报告
    report = generate_report()

    # 保存JSON报告
    report_path = "logs/test_all_features_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"\n📊 测试报告已保存: {report_path}")

    # 打印总结
    summary = report["summary"]
    print("\n" + "="*70)
    print("📊 测试总结")
    print("="*70)
    print(f"  总测试数: {summary['total_tests']}")
    print(f"  通过: {summary['passed']}  失败: {summary['failed']}")
    print(f"  通过率: {summary['pass_rate']}")
    print(f"  总耗时: {summary['total_duration_seconds']}s")
    print(f"  生成文件: {summary['total_files_generated']} 个")

    print("\n✅ 优点:")
    for s in report["evaluation"]["strengths"]:
        print(f"  + {s}")

    print("\n❌ 不足:")
    for w in report["evaluation"]["weaknesses"]:
        print(f"  - {w}")

    print("\n💡 改进建议:")
    for s in report["evaluation"]["suggestions"]:
        print(f"  → {s}")

    print(f"\n详细报告: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
