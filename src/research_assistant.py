"""
AI 研究助理模块 - 全功能科研助手

功能:
  1. 文献调研 - 搜索文献（支持作者/机构/主题过滤）
  2. 文献综述 - AI生成综述 + Word/Excel/BibTeX 导出
  3. 领域热点分析 - 统计高频关键词、高引增长趋势
  4. 引用链追踪 - 追踪论文的引用网络和学术传承
  5. 论文对比分析 - 对比多个研究方向的方法与优劣
  6. 研究空白发现 - 识别未被充分探索的创新方向
  7. 会议/期刊追踪 - 追踪顶会顶刊最新论文
  8. 选题建议 - 基于前沿和空白推荐具体选题
  9. 作者查询 - 查询作者信息和代表作
  10. 文献导出 - BibTeX/CSV/Excel 格式
  11. 研究问答 - 回答一般科研问题
"""

import json
import logging
import os
import re
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from collections import defaultdict

from openai import OpenAI

from .semantic_scholar import SemanticScholarFetcher
from .literature_export import LiteratureExporter
from .fetcher import Paper
from .pubmed import PubMedFetcher, is_medical_query

logger = logging.getLogger(__name__)


# 用户意图类型
INTENT_RESEARCH = "research"        # 文献调研
INTENT_REVIEW = "review"            # 文献综述
INTENT_EXPORT = "export"            # 文献导出
INTENT_QUESTION = "question"        # 一般问题
INTENT_AUTHOR = "author"            # 作者查询
INTENT_PAPER_DETAIL = "detail"      # 论文详情
INTENT_HOTSPOT = "hotspot"          # 领域热点分析
INTENT_CITATION_TRACE = "citation_trace"  # 引用链追踪
INTENT_COMPARE = "compare"          # 论文对比分析
INTENT_GAP = "gap"                  # 研究空白发现
INTENT_VENUE = "venue"              # 会议/期刊追踪
INTENT_TOPIC_SUGGEST = "topic_suggest"    # 选题建议
INTENT_HELP = "help"                # 帮助信息


class ResearchAssistant:
    """
    AI 研究助理 - 钉钉群机器人后端

    处理用户消息，分派到不同功能模块
    支持多轮对话记忆，可根据上下文理解后续追问
    """

    # 对话历史保留的最大轮数
    MAX_HISTORY_TURNS = 20
    # 对话超时（秒），超过则清空上下文
    CONVERSATION_TIMEOUT = 1800  # 30分钟

    def __init__(self, config: dict):
        self.config = config
        ai_config = config.get("ai", {})

        self.client = OpenAI(
            api_key=ai_config["api_key"],
            base_url=ai_config.get("base_url", "https://api.deepseek.com"),
            timeout=120.0,
        )
        self.model = ai_config.get("model", "deepseek-chat")

        self.s2_fetcher = SemanticScholarFetcher(config)
        self.exporter = LiteratureExporter(config)

        # PubMed 数据源（医学/生物/化学领域补充）
        try:
            self.pubmed_fetcher = PubMedFetcher(config)
            self._pubmed_available = True
            logger.info("PubMed 数据源已启用")
        except Exception as e:
            self.pubmed_fetcher = None
            self._pubmed_available = False
            logger.warning(f"PubMed 数据源初始化失败: {e}")

        # ===== 对话记忆系统 =====
        # user_id -> {"messages": [{"role","content","time"}], "context": {...}}
        self._conversations: Dict[str, Dict] = defaultdict(lambda: {
            "messages": [],
            "context": {},      # 上次搜索的论文/主题等
            "last_active": 0,
        })

        # 对话日志保存目录
        self._chat_logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "chat_logs")
        os.makedirs(self._chat_logs_dir, exist_ok=True)

    # ================================================================
    # 智能搜索：多策略回退
    # ================================================================
    def _search_with_fallback(self, query: str, limit: int = 100,
                              year_from: int = None, year_to: int = None,
                              sort_by: str = "citationCount",
                              min_results: int = 5,
                              query_zh: str = "") -> List:
        """
        带回退策略的搜索，在结果不足时自动尝试多种策略:
        1. 原始查询（带年份过滤）
        2. 简化查询（取前3个关键词）
        3. 去掉年份过滤重搜
        4. 中文查询补充
        5. 拆分关键词分别搜索

        Returns:
            去重后的论文列表
        """
        all_papers = []
        strategies_used = []
        current_year = datetime.now().year

        # 策略1: 原始查询
        try:
            papers = self.s2_fetcher.research_query(
                query=query, limit=limit,
                year_from=year_from, year_to=year_to,
                sort_by=sort_by,
            )
            all_papers.extend(papers)
            strategies_used.append(f"原始查询: {len(papers)}篇")
            logger.info(f"  [搜索策略1] 原始查询 '{query[:50]}': {len(papers)}篇")
        except Exception as e:
            logger.warning(f"  [搜索策略1] 原始查询失败: {e}")

        # 如果找到足够多结果，直接返回
        if len(all_papers) >= min_results:
            return self._deduplicate_papers(all_papers), strategies_used

        # 策略2: 取前几个关键词简化查询
        words = query.split()
        if len(words) > 3:
            simple_query = " ".join(words[:3])
            try:
                papers = self.s2_fetcher.research_query(
                    query=simple_query, limit=limit,
                    year_from=year_from, year_to=year_to,
                    sort_by=sort_by,
                )
                all_papers.extend(papers)
                strategies_used.append(f"简化查询'{simple_query}': {len(papers)}篇")
                logger.info(f"  [搜索策略2] 简化查询 '{simple_query}': {len(papers)}篇")
            except Exception as e:
                logger.warning(f"  [搜索策略2] 简化查询失败: {e}")

        unique_so_far = self._deduplicate_papers(all_papers)
        if len(unique_so_far) >= min_results:
            return unique_so_far, strategies_used

        # 策略3: 去掉年份限制重搜
        if year_from or year_to:
            try:
                papers = self.s2_fetcher.research_query(
                    query=query, limit=limit,
                    sort_by=sort_by,
                )
                all_papers.extend(papers)
                strategies_used.append(f"无年份限制: {len(papers)}篇")
                logger.info(f"  [搜索策略3] 无年份限制: {len(papers)}篇")
            except Exception as e:
                logger.warning(f"  [搜索策略3] 无年份限制搜索失败: {e}")

        unique_so_far = self._deduplicate_papers(all_papers)
        if len(unique_so_far) >= min_results:
            return unique_so_far, strategies_used

        # 策略4: 中文查询补充（S2支持中文但效果可能不同）
        if query_zh and query_zh != query:
            try:
                papers = self.s2_fetcher.research_query(
                    query=query_zh, limit=min(limit, 50),
                    sort_by=sort_by,
                )
                all_papers.extend(papers)
                strategies_used.append(f"中文查询: {len(papers)}篇")
                logger.info(f"  [搜索策略4] 中文查询 '{query_zh[:30]}': {len(papers)}篇")
            except Exception as e:
                logger.warning(f"  [搜索策略4] 中文查询失败: {e}")

        unique_so_far = self._deduplicate_papers(all_papers)
        if len(unique_so_far) >= min_results:
            return unique_so_far, strategies_used

        # 策略5: 拆分查询词分别搜索
        keywords = [w for w in words if len(w) >= 3]
        if len(keywords) >= 2:
            for kw in keywords[:3]:
                try:
                    papers = self.s2_fetcher.research_query(
                        query=kw, limit=30,
                        sort_by=sort_by,
                    )
                    all_papers.extend(papers)
                    strategies_used.append(f"关键词'{kw}': {len(papers)}篇")
                    logger.info(f"  [搜索策略5] 关键词 '{kw}': {len(papers)}篇")
                except Exception as e:
                    logger.warning(f"  [搜索策略5] 关键词搜索失败: {e}")

        unique_so_far = self._deduplicate_papers(all_papers)
        if len(unique_so_far) >= min_results:
            logger.info(f"  [搜索汇总] 总计去重后: {len(unique_so_far)}篇, 策略: {'; '.join(strategies_used)}")
            return unique_so_far, strategies_used

        # 策略6: PubMed 补充搜索（医学/生物/化学领域）
        if self._pubmed_available and is_medical_query(query + " " + query_zh):
            try:
                pubmed_papers = self.pubmed_fetcher.search(query=query, limit=min(limit, 50))
                all_papers.extend(pubmed_papers)
                strategies_used.append(f"PubMed补充: {len(pubmed_papers)}篇")
                logger.info(f"  [搜索策略6] PubMed 补充搜索: {len(pubmed_papers)}篇")
            except Exception as e:
                logger.warning(f"  [搜索策略6] PubMed 搜索失败: {e}")

        final = self._deduplicate_papers(all_papers)
        logger.info(f"  [搜索汇总] 总计去重后: {len(final)}篇, 策略: {'; '.join(strategies_used)}")
        return final, strategies_used

    def _deduplicate_papers(self, papers: list) -> list:
        """论文去重（按标题）"""
        seen = set()
        unique = []
        for p in papers:
            key = p.title.strip().lower()
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique

    def _insufficient_papers_message(self, query_zh: str, found_count: int,
                                     strategies: list = None,
                                     min_needed: int = 5) -> str:
        """生成文献不足的友好提示"""
        lines = []
        if found_count == 0:
            lines.append(f"❌ 未找到与 **{query_zh}** 相关的文献。")
        else:
            lines.append(f"⚠ 仅找到 **{found_count}** 篇相关文献（需要至少 {min_needed} 篇才能进行有效分析）。")

        if strategies:
            lines.append(f"\n> 已尝试的搜索策略: {'; '.join(strategies)}")

        lines.append("\n**可能的原因及建议:**")
        lines.append("1. **搜索词过于具体** → 尝试使用更宽泛的英文关键词")
        lines.append("2. **该领域文献较少** → 已联合搜索 Semantic Scholar + PubMed，中文文献可能覆盖不全")
        lines.append("3. **年份范围太窄** → 尝试扩大搜索年份范围")
        lines.append("4. **领域术语差异** → 尝试使用该领域的标准英文术语（如 MeSH 词汇）")
        lines.append(f"\n💡 建议尝试: \"搜索 {query_zh} related topics\" 或换个更通用的英文关键词")
        return "\n".join(lines)

    def _get_conversation(self, user_id: str) -> Dict:
        """获取用户对话，超时则自动重置"""
        conv = self._conversations[user_id]
        now = datetime.now().timestamp()
        if conv["last_active"] and (now - conv["last_active"]) > self.CONVERSATION_TIMEOUT:
            logger.info(f"对话超时，清空用户 {user_id[:8]} 的对话上下文")
            conv["messages"] = []
            conv["context"] = {}
        conv["last_active"] = now
        return conv

    def _add_message(self, user_id: str, role: str, content: str):
        """添加消息到对话历史"""
        conv = self._conversations[user_id]
        conv["messages"].append({
            "role": role,
            "content": content[:3000],  # 限制长度避免token溢出
            "time": datetime.now().isoformat(),
        })
        # 保留最近 N 轮
        if len(conv["messages"]) > self.MAX_HISTORY_TURNS * 2:
            conv["messages"] = conv["messages"][-self.MAX_HISTORY_TURNS * 2:]

    def _get_context_summary(self, user_id: str) -> str:
        """获取对话上下文摘要，用于意图解析"""
        conv = self._conversations[user_id]
        if not conv["messages"]:
            return ""

        # 取最近几轮对话
        recent = conv["messages"][-8:]
        summary_parts = []
        for msg in recent:
            role_label = "用户" if msg["role"] == "user" else "助理"
            # 截取关键内容
            text = msg["content"][:200]
            summary_parts.append(f"[{role_label}]: {text}")

        context_info = ""
        ctx = conv.get("context", {})
        if ctx.get("last_topic"):
            context_info += f"\n上次讨论的主题: {ctx['last_topic']}"
        if ctx.get("last_intent"):
            context_info += f"\n上次执行的操作: {ctx['last_intent']}"
        if ctx.get("last_paper_count"):
            context_info += f"\n上次搜索到的论文数: {ctx['last_paper_count']}"

        return f"对话历史:\n" + "\n".join(summary_parts) + context_info

    async def handle_message(self, user_message: str, user_id: str = "") -> Dict[str, Any]:
        """
        处理用户消息的主入口（支持多轮对话）
        """
        logger.info(f"收到用户消息 [{user_id[:8]}]: {user_message[:100]}")

        # 获取对话上下文
        conv = self._get_conversation(user_id)

        # 保存用户消息
        self._add_message(user_id, "user", user_message)

        # 检查特殊命令
        cmd = user_message.strip().lower()
        if cmd in ("/help", "帮助", "/帮助", "help"):
            return {"text": self._help_text()}
        if cmd in ("/clear", "清空对话", "/reset", "重置"):
            conv["messages"] = []
            conv["context"] = {}
            return {"text": "✅ 对话上下文已清空。"}
        if cmd in ("/export_chat", "导出对话", "/导出对话"):
            return self._export_conversation(user_id)

        # 1. 获取上下文摘要
        context_summary = self._get_context_summary(user_id)

        # 2. 意图识别（带上下文）
        intent, params = self._parse_intent(user_message, context_summary)
        logger.info(f"  意图: {intent}")
        logger.info(f"  搜索词: {params.get('search_query', 'N/A')}")
        logger.info(f"  搜索词(中文): {params.get('search_query_zh', 'N/A')}")
        logger.info(f"  参数: {json.dumps({k:v for k,v in params.items() if k not in ('search_query','search_query_zh')}, ensure_ascii=False)[:200]}")

        # 3. 分派处理
        handler_map = {
            INTENT_RESEARCH: lambda: self._handle_research(params),
            INTENT_REVIEW: lambda: self._handle_review(params),
            INTENT_EXPORT: lambda: self._handle_export(params),
            INTENT_AUTHOR: lambda: self._handle_author(params),
            INTENT_PAPER_DETAIL: lambda: self._handle_paper_detail(params),
            INTENT_HOTSPOT: lambda: self._handle_hotspot(params),
            INTENT_CITATION_TRACE: lambda: self._handle_citation_trace(params),
            INTENT_COMPARE: lambda: self._handle_compare(params),
            INTENT_GAP: lambda: self._handle_gap(params),
            INTENT_VENUE: lambda: self._handle_venue(params),
            INTENT_TOPIC_SUGGEST: lambda: self._handle_topic_suggest(params),
            INTENT_HELP: lambda: {"text": self._help_text()},
        }
        handler = handler_map.get(intent)
        if handler:
            result = handler()
        else:
            # question 意图 → 使用带上下文的智能对话
            result = self._handle_question_with_context(user_message, user_id)

        # 4. 保存助理回复到对话历史
        reply_text = result.get("text", "")
        self._add_message(user_id, "assistant", reply_text)

        # 5. 更新上下文信息
        conv["context"]["last_intent"] = intent
        conv["context"]["last_topic"] = params.get("query_zh", "")
        if "search_query" in params:
            conv["context"]["last_search_query"] = params["search_query"]

        return result

    def _parse_intent(self, message: str, context_summary: str = "") -> Tuple[str, dict]:
        """
        使用 AI 解析用户意图（支持上下文理解）

        Returns:
            (intent_type, parameters_dict)
        """
        current_year = datetime.now().year
        default_year_from = current_year - 3

        prompt = f"""你是一位AI研究助理的意图解析器。请分析用户的消息，判断其意图并提取参数。

用户消息: "{message}"
{f'''
对话上下文（帮助你理解追问和后续讨论）:
{context_summary}
''' if context_summary else ''}

可能的意图:
1. "research" - 用户想搜索/调研某个领域的文献
2. "review" - 用户想要某个主题的文献综述
3. "export" - 用户想导出文献列表（BibTeX/CSV/表格）
4. "author" - 用户在查询某个作者的信息或论文
5. "detail" - 用户想了解某篇具体论文的详情
6. "hotspot" - 用户想了解某个领域的研究热点/趋势/前沿动态
7. "citation_trace" - 用户想追踪某篇论文的引用链（谁引用了它、它引用了谁）
8. "compare" - 用户想对比分析多篇论文或多个研究方向
9. "gap" - 用户想发现某个领域的研究空白/未解决问题/潜在创新方向
10. "venue" - 用户想追踪某个会议或期刊的最新论文
11. "topic_suggest" - 用户在寻求选题建议/研究方向推荐
12. "question" - 用户在问一个一般性的研究问题
13. "help" - 用户需要帮助信息

意图判断规则:
- 如果用户在**追问之前搜索结果的细节**（如"上面哪些论文..."、"详细介绍一下第X个"、"这些论文中..."），应判为 "question"（利用对话上下文回答）
- "热点"、"趋势"、"前沿"、"最新进展"、"发展方向" → hotspot
- "引用链"、"引用网络"、"谁引用了"、"被引用" → citation_trace
- "对比"、"比较"、"区别"、"差异"、"哪个更好" → compare
- "空白"、"缺口"、"未解决"、"创新点"、"未来方向" → gap
- "会议"、"期刊"、"ICRA"、"NeurIPS"、"Nature"、"顶会"、"顶刊" → venue
- "选题"、"课题建议"、"研究方向推荐"、"做什么方向好" → topic_suggest
- "综述"、"review"、"总结"、"概述" → review
- "搜索"、"查找"、"文献"、"论文" → research
- "导出"、"下载"、"BibTeX" → export

请严格按JSON格式输出:
{{
  "intent": "research",
  "params": {{
    "search_query": "一个综合性的英文搜索查询",
    "search_query_zh": "同一查询的中文版本",
    "query_zh": "用户请求的简短中文描述",
    "limit": 100,
    "year_from": {default_year_from},
    "year_to": {current_year},
    "fields_of_study": [],
    "sort_by": "citationCount",
    "export_format": null,
    "author_name": null,
    "institution": null,
    "paper_id": null,
    "venue_name": null,
    "compare_topics": []
  }}
}}

重要规则:
- search_query 必须是英文，是一个综合性的搜索短语，包含该领域的核心术语
  例如"机器人规划与控制" → "robot motion planning control trajectory optimization"
  例如"肿瘤免疫治疗" → "tumor immunotherapy cancer immune checkpoint therapy"
  例如"中医药治疗骨质疏松" → "traditional Chinese medicine osteoporosis treatment herbal"
  目标是让一次 API 调用覆盖用户想要的所有方面
  注意: 搜索引擎基于 Semantic Scholar，请使用该领域的标准英文学术术语
  对于医学/生物/化学等领域，请使用标准英文医学术语（如 MeSH 词汇）
- search_query_zh 是同一查询的中文版本（用于回退搜索）
- limit 默认 100
- year_from 默认 {default_year_from}（近3年），用户指定则用用户的
- sort_by 默认 "citationCount"
- author_name: 提取作者英文名（如有）
- institution: 提取机构英文名（如有）
- venue_name: 如果用户提到了会议/期刊（如"ICRA 2024"、"Nature Robotics"），提取标准名称
- compare_topics: 如果是对比意图，提取2-4个要对比的方向/论文标题（英文列表）
  例如"对比强化学习和模仿学习" → ["reinforcement learning", "imitation learning"]
- 如果用户同时指定了作者/机构和主题，search_query 里只放主题关键词
- search_query 不要过长（3-8个词），太长反而搜不到
- 只输出 JSON，不要其他文字"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是精确的意图解析器，只输出JSON。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content)
            intent = result.get("intent", "question")
            params = result.get("params", {})
            return (intent, params)
        except Exception as e:
            logger.error(f"意图解析失败: {e}")
            return ("question", {"search_query": message, "query_zh": message})

    def _handle_research(self, params: dict) -> Dict[str, Any]:
        """处理文献调研请求 — 单次综合查询，支持作者/机构过滤"""
        search_query = params.get("search_query", "")
        search_query_zh = params.get("search_query_zh", "")
        query_zh = params.get("query_zh", search_query)
        limit = params.get("limit", 100)
        year_from = params.get("year_from")
        year_to = params.get("year_to")
        fields = params.get("fields_of_study") or []
        sort_by = params.get("sort_by", "citationCount")
        export_format = params.get("export_format")
        author_name = params.get("author_name") or ""
        institution = params.get("institution") or ""

        # 兼容旧字段
        if not search_query:
            search_query = params.get("query", "") or " ".join(params.get("queries", []))
        if not search_query and not author_name:
            return {"text": "请提供要搜索的关键词、主题或作者。"}

        all_papers = []

        # ==========  如果指定了作者，走作者搜索路径  ==========
        if author_name:
            author_papers = self._search_by_author(author_name, search_query, limit, year_from, year_to)
            all_papers.extend(author_papers)
            logger.info(f"  作者搜索 [{author_name}]: {len(author_papers)} 篇")

        # ==========  如果指定机构但没有作者，机构名加入搜索词  ==========
        if institution and not author_name and search_query:
            search_query_with_inst = f"{search_query} {institution}"
            try:
                papers = self.s2_fetcher.research_query(
                    query=search_query_with_inst,
                    limit=limit,
                    year_from=year_from, year_to=year_to,
                    fields_of_study=fields if fields else None,
                    sort_by=sort_by,
                )
                all_papers.extend(papers)
                logger.info(f"  机构+主题搜索 [{search_query_with_inst[:50]}]: {len(papers)} 篇")
            except Exception as e:
                logger.warning(f"  机构搜索失败: {e}")

        # ==========  常规主题搜索（带回退策略）  ==========
        if search_query and not author_name:
            found, strategies = self._search_with_fallback(
                query=search_query, limit=limit,
                year_from=year_from, year_to=year_to,
                sort_by=sort_by, min_results=3,
                query_zh=search_query_zh,
            )
            all_papers.extend(found)
            logger.info(f"  主题搜索（含回退）: {len(found)} 篇")

        # ==========  医学领域: 主动补充 PubMed 搜索  ==========
        if search_query and self._pubmed_available and is_medical_query(search_query + " " + search_query_zh):
            try:
                pubmed_papers = self.pubmed_fetcher.search(query=search_query, limit=min(limit, 50))
                if pubmed_papers:
                    all_papers.extend(pubmed_papers)
                    logger.info(f"  PubMed 主动补充: {len(pubmed_papers)} 篇")
            except Exception as e:
                logger.warning(f"  PubMed 补充搜索失败: {e}")

        # 去重（按 title 去重）
        seen_titles = set()
        unique_papers = []
        for p in all_papers:
            title_key = p.title.strip().lower()
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique_papers.append(p)

        # 如果指定了机构，二次过滤：优先展示作者机构匹配的论文
        if institution and unique_papers:
            inst_lower = institution.lower()
            matched = [p for p in unique_papers if any(inst_lower in a.lower() for a in p.authors)]
            # 即使没匹配到也不过滤（机构信息不一定在 authors 里）

        # 按引用数排序
        unique_papers.sort(key=lambda p: getattr(p, '_citation_count', 0) or 0, reverse=True)

        if not unique_papers:
            return {"text": f"未找到与 **{query_zh}** 相关的文献，请尝试换个关键词。"}

        # ========== 自动导出 BibTeX + Excel ==========
        files = self._do_export(unique_papers, "all", query_zh)
        # 如果用户指定了其他格式，也额外导出
        if export_format and export_format not in ("bib", "bibtex", "excel", "xlsx", "all"):
            extra_files = self._do_export(unique_papers, export_format, query_zh)
            files.extend(extra_files)

        # ========== 生成 AI 研究总结 ==========
        logger.info(f"  正在生成 AI 研究总结...")
        summary = self._generate_research_summary(unique_papers, query_zh, search_query)

        # ========== 构建简洁的钉钉回复 ==========
        lines = []
        lines.append(f"## 📚 文献调研: {query_zh}")
        lines.append(f"> 搜索词: `{search_query}`")
        if author_name:
            lines.append(f"> 作者: `{author_name}`")
        if institution:
            lines.append(f"> 机构: `{institution}`")
        lines.append(f"> 找到 **{len(unique_papers)}** 篇相关文献 ({year_from or '...'}-{year_to or '...'})")
        # 标记数据来源
        pubmed_count = sum(1 for p in unique_papers if getattr(p, '_source', '') == 'pubmed')
        if pubmed_count > 0:
            ss_count = len(unique_papers) - pubmed_count
            lines.append(f"> 📊 数据来源: Semantic Scholar {ss_count} 篇 + PubMed {pubmed_count} 篇")
        lines.append("")

        # AI 总结
        if summary:
            lines.append(summary)
            lines.append("")

        # 仅显示 Top 5 高引论文概览
        lines.append("### 🏆 高引代表作 (Top 5)")
        for i, p in enumerate(unique_papers[:5], 1):
            citation = getattr(p, '_citation_count', 0) or 0
            year = getattr(p, '_year', '') or ''
            authors_str = ', '.join(p.authors[:2])
            if len(p.authors) > 2:
                authors_str += ' et al.'
            lines.append(f"**{i}.** {p.title}")
            lines.append(f"> {authors_str} ({year}) | 引用 {citation}")
            lines.append("")

        result = {"text": "\n".join(lines), "files": files}
        return result

    def _handle_review(self, params: dict) -> Dict[str, Any]:
        """处理文献综述请求 — 单次查询 + AI综述 + Word文档"""
        search_query = params.get("search_query", "")
        query_zh = params.get("query_zh", "")
        search_query_zh = params.get("search_query_zh", query_zh)
        limit = params.get("limit", 100)
        year_from = params.get("year_from")
        year_to = params.get("year_to")
        author_name = params.get("author_name") or ""
        institution = params.get("institution") or ""

        # 兼容旧字段
        if not search_query:
            search_query = params.get("query", "") or " ".join(params.get("queries", []))
        if not search_query and not author_name:
            return {"text": "请提供要生成综述的主题。"}
        if not query_zh:
            query_zh = search_query

        logger.info(f"[综述] 开始: '{search_query}' (中文: {query_zh})")

        # 搜索文献（使用回退策略）
        all_papers = []
        strategies = []

        # 如果指定了作者
        if author_name:
            author_papers = self._search_by_author(author_name, search_query, limit, year_from, year_to)
            all_papers.extend(author_papers)

        # 主题搜索（带回退）
        if search_query and not author_name:
            q = f"{search_query} {institution}" if institution else search_query
            found, strats = self._search_with_fallback(
                query=q, limit=limit,
                year_from=year_from, year_to=year_to,
                sort_by="citationCount", min_results=5,
                query_zh=search_query_zh,
            )
            all_papers.extend(found)
            strategies = strats

        # 医学领域: 主动补充 PubMed 搜索
        if search_query and self._pubmed_available and is_medical_query(search_query + " " + search_query_zh):
            try:
                pubmed_papers = self.pubmed_fetcher.search(query=search_query, limit=min(limit, 50))
                if pubmed_papers:
                    all_papers.extend(pubmed_papers)
                    strategies.append(f"PubMed补充: {len(pubmed_papers)}篇")
                    logger.info(f"  [综述] PubMed 补充: {len(pubmed_papers)} 篇")
            except Exception as e:
                logger.warning(f"  [综述] PubMed 补充失败: {e}")

        # 去重 & 排序
        unique_papers = self._deduplicate_papers(all_papers)
        unique_papers.sort(key=lambda p: getattr(p, '_citation_count', 0) or 0, reverse=True)

        logger.info(f"  [综述] 去重后: {len(unique_papers)} 篇")

        # 最低论文数检查
        MIN_PAPERS_FOR_REVIEW = 5
        if len(unique_papers) < MIN_PAPERS_FOR_REVIEW:
            return {"text": self._insufficient_papers_message(
                query_zh, len(unique_papers), strategies, MIN_PAPERS_FOR_REVIEW)}

        # 取top N用于综述
        papers_for_review = unique_papers[:30]

        # AI 生成综述（带重试）
        papers_info = ""
        for i, p in enumerate(papers_for_review[:20], 1):
            citation = getattr(p, '_citation_count', 0) or 0
            year = getattr(p, '_year', '') or ''
            papers_info += f"{i}. [{year}] {p.title} (引用:{citation})\n"
            if p.abstract:
                papers_info += f"   摘要: {p.abstract[:150]}\n\n"

        prompt = f"""你是一位学术综述专家。请根据以下 {len(papers_for_review)} 篇与「{query_zh}」相关的文献，撰写一篇简要的文献综述。

{papers_info}

请用中文撰写，结构如下：
1. **研究背景与现状**（100字）
2. **主要研究方向**（对文献进行分类，列出3-5个子方向，每个方向引用相关论文）
3. **关键技术与方法**（150字，总结主要的技术方法）
4. **研究趋势与展望**（100字）
5. **推荐精读论文**（列出最值得深入阅读的3-5篇，简述理由）

总篇幅控制在800字以内，使用 Markdown 格式。在引用论文时使用序号 [1], [2] 等。"""

        review_text = None
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "你是资深学术综述专家，擅长文献分析与归纳总结。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.5,
                    max_tokens=3000,
                    timeout=90.0,
                )
                review_text = response.choices[0].message.content
                break
            except Exception as e:
                logger.warning(f"综述生成第{attempt+1}次尝试失败: {e}")
                if attempt < 2:
                    import time
                    time.sleep(3 * (attempt + 1))

        if not review_text:
            review_text = ("⚠ AI 综述生成失败（网络波动），但文献数据已检索成功。\n"
                          "请下载下方的 Excel/BibTeX 文件查看完整文献列表，或稍后重试综述生成。")

        lines = []
        lines.append(f"## 📖 文献综述: {query_zh}")
        lines.append(f"> 基于 Semantic Scholar 检索到的 {len(unique_papers)} 篇文献（综述使用前 {len(papers_for_review)} 篇高引文献）")
        lines.append("")
        lines.append(review_text)
        lines.append("")
        lines.append("---")
        lines.append(f"📚 参考文献列表 ({len(papers_for_review)} 篇):")
        for i, p in enumerate(papers_for_review[:20], 1):
            year = getattr(p, '_year', '') or ''
            lines.append(f"{i}. {', '.join(p.authors[:2])} et al. ({year}). *{p.title}*. [链接]({p.url})")

        result = {"text": "\n".join(lines)}

        # 综述默认附带 BibTeX + Excel + Word 导出
        files = self._do_export(unique_papers, "all", query_zh)

        # 生成综述 Word 文档（含参考文献）
        if review_text and "⚠" not in review_text:
            try:
                docx_path = self.exporter.export_review_docx(
                    topic=query_zh,
                    review_text=review_text,
                    papers=papers_for_review,
                    filename_prefix=re.sub(r'[^\w\u4e00-\u9fff]', '_', query_zh)[:30] + f"_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                )
                if docx_path:
                    file_server = self.config.get("dingtalk_bot", {}).get("file_server_url", "http://127.0.0.1:5679")
                    fname = docx_path.split('/')[-1] if '/' in docx_path else docx_path.split(chr(92))[-1]
                    files.append({
                        "name": f"{query_zh}_综述.docx",
                        "path": docx_path,
                        "url": f"{file_server}/download/{fname}",
                    })
            except Exception as e:
                logger.warning(f"Word综述导出失败: {e}")

        result["files"] = files

        return result

    def _handle_export(self, params: dict) -> Dict[str, Any]:
        """处理文献导出请求"""
        search_query = params.get("search_query", "")
        query_zh = params.get("query_zh", "")
        export_format = params.get("export_format", "bib")
        limit = params.get("limit", 100)

        # 兼容旧字段
        if not search_query:
            search_query = params.get("query", "") or " ".join(params.get("queries", []))
        if not search_query:
            return {"text": "请提供要导出的文献主题或关键词。"}
        if not query_zh:
            query_zh = search_query

        # 单次查询
        papers = self.s2_fetcher.research_query(query=search_query, limit=limit)

        if not papers:
            return {"text": f"未找到与 **{query_zh}** 相关的文献。"}

        files = self._do_export(papers, export_format, query_zh)

        lines = [
            f"## 📦 文献导出: {query_zh}",
            f"> 共 {len(papers)} 篇文献，格式: {export_format.upper()}",
            "",
            "文件已生成，请点击下方链接下载:",
        ]
        for f in files:
            lines.append(f"- 📥 [{f['name']}]({f['url']})")

        return {"text": "\n".join(lines), "files": files}

    def _search_by_author(self, author_name: str, topic_query: str = "",
                          limit: int = 100, year_from: int = None,
                          year_to: int = None) -> List[Paper]:
        """
        通过作者名搜索论文

        策略:
        1. 用 S2 Author Search API 找到作者 ID
        2. 获取该作者的论文列表
        3. 如果有主题 query，按标题/摘要做关键词过滤
        """
        papers = []
        try:
            authors = self.s2_fetcher.search_authors(author_name)
            if not authors:
                logger.warning(f"未找到作者: {author_name}")
                # 降级: 把作者名加入搜索词
                if topic_query:
                    return self.s2_fetcher.research_query(
                        query=f"{author_name} {topic_query}",
                        limit=limit, year_from=year_from, year_to=year_to,
                    )
                return []

            # 取第一个匹配的作者
            author = authors[0]
            author_id = author.get("authorId", "")
            if not author_id:
                return []

            logger.info(f"  找到作者: {author.get('name')} (ID={author_id}, "
                        f"论文={author.get('paperCount',0)}, 机构={author.get('affiliations',[])})")

            # 获取该作者的论文
            author_data = self.s2_fetcher.get_author_papers(author_id, limit=min(limit, 500))
            if not author_data:
                return []

            # 转换为 Paper 对象并过滤
            topic_words = set(topic_query.lower().split()) if topic_query else set()
            for item in author_data:
                title = item.get("title", "")
                year = item.get("year")
                citation_count = item.get("citationCount", 0)
                url = item.get("url", "")
                venue = item.get("venue", "")
                abstract = item.get("abstract", "") or ""
                paper_authors = [a.get("name", "") for a in (item.get("authors") or [])[:10]]

                # 年份过滤
                if year_from and year and year < year_from:
                    continue
                if year_to and year and year > year_to:
                    continue

                # 主题过滤（如果指定了主题，标题或摘要需要包含至少一个关键词）
                if topic_words:
                    text_lower = (title + " " + abstract).lower()
                    if not any(w in text_lower for w in topic_words):
                        continue

                paper = Paper(
                    title=title,
                    authors=paper_authors if paper_authors else [author.get("name", author_name)],
                    abstract=abstract,
                    arxiv_id=f"s2-{item.get('paperId','')}",
                    url=url or f"https://www.semanticscholar.org/paper/{item.get('paperId','')}",
                    pdf_url="",
                    categories=[],
                    published=datetime.now(),
                    updated=datetime.now(),
                    keywords_matched=[],
                )
                paper._citation_count = citation_count
                paper._venue = venue
                paper._year = year
                paper._doi = ""
                paper._s2_id = item.get("paperId", "")
                papers.append(paper)

            logger.info(f"  作者 {author_name} 匹配论文: {len(papers)} 篇")
        except Exception as e:
            logger.error(f"  作者搜索异常: {e}")
            # 降级: 把作者名加入搜索词
            if topic_query:
                try:
                    return self.s2_fetcher.research_query(
                        query=f"{author_name} {topic_query}",
                        limit=limit, year_from=year_from, year_to=year_to,
                    )
                except Exception:
                    pass

        return papers

    def _handle_author(self, params: dict) -> Dict[str, Any]:
        """处理作者查询 — 展示作者信息 + 代表作"""
        author_name = params.get("author_name", "")
        if not author_name:
            return {"text": "请提供要查询的作者姓名。"}

        authors = self.s2_fetcher.search_authors(author_name)
        if not authors:
            return {"text": f"未找到作者: **{author_name}**"}

        lines = [f"## 👤 作者查询: {author_name}", ""]
        for a in authors[:3]:
            name = a.get("name", "")
            affiliations = a.get("affiliations", [])
            paper_count = a.get("paperCount", 0)
            citation_count = a.get("citationCount", 0)
            h_index = a.get("hIndex", 0)
            author_id = a.get("authorId", "")

            lines.append(f"**{name}**")
            if affiliations:
                lines.append(f"> 🏫 {', '.join(affiliations)}")
            lines.append(f"> 📄 论文: {paper_count} | 📊 引用: {citation_count} | 📈 H-index: {h_index}")

            # 获取该作者的代表论文（前5篇高引）
            if author_id:
                try:
                    top_papers = self.s2_fetcher.get_author_papers(author_id, limit=10)
                    if top_papers:
                        # 按引用排序
                        top_papers.sort(key=lambda x: x.get("citationCount", 0) or 0, reverse=True)
                        lines.append(f"\n> **代表作（高引前5）:**")
                        for j, tp in enumerate(top_papers[:5], 1):
                            tc = tp.get('citationCount', 0) or 0
                            ty = tp.get('year', '')
                            lines.append(f"> {j}. {tp.get('title','')} ({ty}, 引用:{tc})")
                except Exception:
                    pass
            lines.append("")

        return {"text": "\n".join(lines)}

    def _handle_paper_detail(self, params: dict) -> Dict[str, Any]:
        """处理论文详情查询"""
        paper_id = params.get("paper_id", "")
        query = params.get("search_query", "") or params.get("query", "") or params.get("query_zh", "")

        if not paper_id and query:
            # 先搜索，取第一篇
            papers = self.s2_fetcher.research_query(query=query, limit=1)
            if papers:
                paper_id = getattr(papers[0], '_s2_id', '') or papers[0].arxiv_id
            else:
                return {"text": "未找到相关论文。"}

        if not paper_id:
            return {"text": "请提供论文标题或ID。"}

        detail = self.s2_fetcher.get_paper_details(paper_id)
        if not detail:
            return {"text": "无法获取论文详情。"}

        title = detail.get("title", "")
        authors = [a.get("name", "") for a in (detail.get("authors") or [])[:10]]
        abstract = detail.get("abstract", "无摘要")
        year = detail.get("year", "")
        venue = detail.get("venue", "")
        citation_count = detail.get("citationCount", 0)
        reference_count = detail.get("referenceCount", 0)

        lines = [
            f"## 📄 论文详情",
            "",
            f"### {title}",
            f"> 👤 {', '.join(authors[:5])}",
            f"> 📅 {year} | 📖 {venue}" if venue else f"> 📅 {year}",
            f"> 📊 引用: {citation_count} | 参考文献: {reference_count}",
            "",
            f"**摘要:**",
            abstract[:500],
            "",
        ]

        # 主要引用
        citations = detail.get("citations", [])
        if citations:
            lines.append(f"### 📈 被引用 (前5篇)")
            for c in citations[:5]:
                cp = c.get("citingPaper", {})
                lines.append(f"- {cp.get('title', 'N/A')} ({cp.get('year', '')})")
            lines.append("")

        # 参考文献
        refs = detail.get("references", [])
        if refs:
            lines.append(f"### 📚 参考文献 (前5篇)")
            for r in refs[:5]:
                rp = r.get("citedPaper", {})
                lines.append(f"- {rp.get('title', 'N/A')} ({rp.get('year', '')})")

        return {"text": "\n".join(lines)}

    def _handle_hotspot(self, params: dict) -> Dict[str, Any]:
        """
        🔥 领域热点分析
        分析某领域近1-3年的研究热点趋势，统计高频关键词、高引论文增长，生成热点报告
        """
        search_query = params.get("search_query", "")
        query_zh = params.get("query_zh", search_query)
        search_query_zh = params.get("search_query_zh", query_zh)
        year_from = params.get("year_from")
        year_to = params.get("year_to")
        current_year = datetime.now().year

        if not search_query:
            return {"text": "请提供要分析热点的研究领域。"}

        logger.info(f"[热点分析] 开始: '{search_query}' (中文: {query_zh})")

        # 获取近3年高引论文（带回退策略）
        unique, strategies = self._search_with_fallback(
            query=search_query, limit=200,
            year_from=year_from or (current_year - 3),
            year_to=year_to or current_year,
            sort_by="citationCount", min_results=10,
            query_zh=search_query_zh,
        )

        logger.info(f"  [热点分析] 去重后: {len(unique)} 篇")

        # 最低论文数检查
        MIN_PAPERS_FOR_HOTSPOT = 5
        if len(unique) < MIN_PAPERS_FOR_HOTSPOT:
            return {"text": self._insufficient_papers_message(
                query_zh, len(unique), strategies, MIN_PAPERS_FOR_HOTSPOT)}

        # 按年份分组统计
        year_stats = {}
        for p in unique:
            y = getattr(p, '_year', None)
            if y:
                year_stats.setdefault(y, {"count": 0, "total_citations": 0, "top_papers": []})
                year_stats[y]["count"] += 1
                year_stats[y]["total_citations"] += getattr(p, '_citation_count', 0) or 0
                year_stats[y]["top_papers"].append(p)

        # 提取高频词（从标题中）
        from collections import Counter
        word_freq = Counter()
        stop_words = {'the', 'a', 'an', 'of', 'in', 'for', 'and', 'to', 'on', 'with',
                      'by', 'from', 'at', 'is', 'are', 'was', 'were', 'be', 'been',
                      'its', 'this', 'that', 'as', 'or', 'not', 'using', 'based', 'via'}
        for p in unique:
            words = re.findall(r'[a-zA-Z]{3,}', p.title.lower())
            for w in words:
                if w not in stop_words:
                    word_freq[w] += 1

        # 准备 AI 分析的数据
        top_papers_info = ""
        for i, p in enumerate(unique[:25], 1):
            citation = getattr(p, '_citation_count', 0) or 0
            year = getattr(p, '_year', '') or ''
            top_papers_info += f"{i}. [{year}] {p.title} (引用:{citation})\n"
            if p.abstract:
                top_papers_info += f"   摘要: {p.abstract[:120]}\n"

        year_trend_text = ""
        for y in sorted(year_stats.keys()):
            s = year_stats[y]
            year_trend_text += f"  {y}年: {s['count']}篇, 总引用{s['total_citations']}\n"

        top_keywords = word_freq.most_common(20)
        keyword_text = ", ".join([f"{w}({c})" for w, c in top_keywords])

        prompt = f"""你是一位学术趋势分析专家。请根据以下「{query_zh}」领域的文献数据，撰写一份研究热点分析报告。

## 数据概况
- 共检索到 {len(unique)} 篇论文
- 年份分布:
{year_trend_text}
- 高频关键词(词频): {keyword_text}

## 高引论文 (前25篇):
{top_papers_info}

请用中文撰写热点分析，结构如下:
1. **领域概况** (50字，该领域近年的整体研究热度)
2. **🔥 当前研究热点** (列出5-8个热点方向，每个方向用一句话概括，并引用相关论文编号)
3. **📈 趋势变化** (分析近几年的研究重心是否发生转移，新兴方向有哪些)
4. **🌟 突破性工作** (列出3-5篇最具创新性/影响力的代表作，简述其突破点)
5. **🔮 未来展望** (基于趋势预判未来1-2年的研究热点)

总篇幅600-800字，使用 Markdown 格式。"""

        report = None
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "你是资深学术趋势分析专家，擅长洞察研究前沿和热点方向。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.5,
                    max_tokens=3000,
                    timeout=90.0,
                )
                report = response.choices[0].message.content
                break
            except Exception as e:
                logger.warning(f"热点分析生成第{attempt+1}次失败: {e}")
                if attempt < 2:
                    import time
                    time.sleep(3 * (attempt + 1))

        lines = [f"## 🔥 领域热点分析: {query_zh}"]
        lines.append(f"> 基于 {len(unique)} 篇文献 ({year_from or current_year-3}-{year_to or current_year})")
        lines.append("")

        # 数据统计面板
        lines.append("### 📊 数据统计")
        for y in sorted(year_stats.keys()):
            s = year_stats[y]
            avg_cite = s['total_citations'] // max(s['count'], 1)
            lines.append(f"> {y}年: {s['count']}篇 | 平均引用: {avg_cite}")
        lines.append("")
        lines.append(f"**高频关键词**: {', '.join([w for w, _ in top_keywords[:10]])}")
        lines.append("")

        if report:
            lines.append(report)
        else:
            lines.append("⚠ AI 分析生成失败，请查看上方数据统计。")

        return {"text": "\n".join(lines)}

    def _handle_citation_trace(self, params: dict) -> Dict[str, Any]:
        """
        🔗 引用链追踪
        追踪一篇论文的引用网络：谁引用了它、它引用了谁，找出核心文献脉络
        """
        search_query = params.get("search_query", "")
        paper_id = params.get("paper_id", "")
        query_zh = params.get("query_zh", search_query)

        # 先找到目标论文 — 用论文标题搜索（去掉 citation/network 等无关词）
        if not paper_id and search_query:
            # 清洗搜索词：去掉 citation/network/trace 等辅助词
            import re as _re
            clean_query = _re.sub(r'\b(citation|network|trace|tracking|引用|网络|追踪)\b', '', search_query, flags=_re.IGNORECASE).strip()
            if not clean_query:
                clean_query = search_query
            papers = self.s2_fetcher.research_query(query=clean_query, limit=5, sort_by="citationCount")
            if papers:
                paper_id = getattr(papers[0], '_s2_id', '')
                query_zh = papers[0].title
            else:
                return {"text": f"未找到与 **{query_zh}** 相关的论文。"}

        if not paper_id:
            return {"text": "请提供要追踪引用链的论文标题或ID。"}

        # 获取论文详情
        detail = self.s2_fetcher.get_paper_details(paper_id)
        if not detail:
            return {"text": "无法获取论文详情。"}

        title = detail.get("title", "")
        authors = [a.get("name", "") for a in (detail.get("authors") or [])[:5]]
        year = detail.get("year", "")
        citation_count = detail.get("citationCount", 0)
        reference_count = detail.get("referenceCount", 0)

        lines = [f"## 🔗 引用链追踪"]
        lines.append(f"### 📄 目标论文: {title}")
        lines.append(f"> 👤 {', '.join(authors)}")
        lines.append(f"> 📅 {year} | 📊 被引 {citation_count} 次 | 参考文献 {reference_count} 篇")
        lines.append("")

        # 获取引用该论文的文献（被引）
        citing = self.s2_fetcher.get_paper_citations(paper_id, limit=20)
        if citing:
            lines.append(f"### 📈 被引用（共 {citation_count} 篇，展示前 {min(len(citing), 15)} 篇高引）")
            citing_papers = []
            for c in citing:
                cp = c.get("citingPaper", {})
                if cp.get("title"):
                    citing_papers.append(cp)
            # 按引用数排序
            citing_papers.sort(key=lambda x: x.get("citationCount", 0) or 0, reverse=True)
            for i, cp in enumerate(citing_papers[:15], 1):
                ct = cp.get("citationCount", 0) or 0
                cy = cp.get("year", "")
                ca = ", ".join([a.get("name", "") for a in (cp.get("authors") or [])[:2]])
                lines.append(f"{i}. **{cp.get('title','')}**")
                lines.append(f"   > {ca} | {cy} | 引用: {ct}")
            lines.append("")

        # 获取参考文献
        refs = self.s2_fetcher.get_paper_references(paper_id, limit=20)
        if refs:
            lines.append(f"### 📚 参考文献（共 {reference_count} 篇，展示前 {min(len(refs), 15)} 篇）")
            ref_papers = []
            for r in refs:
                rp = r.get("citedPaper", {})
                if rp.get("title"):
                    ref_papers.append(rp)
            ref_papers.sort(key=lambda x: x.get("citationCount", 0) or 0, reverse=True)
            for i, rp in enumerate(ref_papers[:15], 1):
                rt = rp.get("citationCount", 0) or 0
                ry = rp.get("year", "")
                lines.append(f"{i}. **{rp.get('title','')}** ({ry}, 引用: {rt})")
            lines.append("")

        # AI 分析引用关系
        cite_info = "\n".join([f"- {cp.get('title','')} ({cp.get('year','')}, 引用:{cp.get('citationCount',0)})"
                               for cp in citing_papers[:10]]) if citing else "无"
        ref_info = "\n".join([f"- {rp.get('title','')} ({rp.get('year','')}, 引用:{rp.get('citationCount',0)})"
                               for rp in ref_papers[:10]]) if refs else "无"

        prompt = f"""请简要分析以下论文的学术影响力和引用脉络:

目标论文: {title} ({year}), 被引 {citation_count} 次

引用该论文的主要工作:
{cite_info}

该论文的主要参考文献:
{ref_info}

请用中文简要分析(200-300字):
1. 该论文在领域中的地位和影响力
2. 引用脉络（学术传承关系）
3. 后续研究的主要发展方向"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是学术引用分析专家。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5, max_tokens=1500, timeout=60.0,
            )
            lines.append("### 🧠 AI 分析")
            lines.append(response.choices[0].message.content)
        except Exception as e:
            logger.warning(f"引用分析AI生成失败: {e}")

        return {"text": "\n".join(lines)}

    def _handle_compare(self, params: dict) -> Dict[str, Any]:
        """
        📊 论文/方向对比分析
        对比多个研究方向或论文的方法、贡献、优劣势
        """
        compare_topics = params.get("compare_topics") or []
        search_query = params.get("search_query", "")
        query_zh = params.get("query_zh", "")
        year_from = params.get("year_from")
        year_to = params.get("year_to")

        if not compare_topics and search_query:
            # 从搜索词中尝试拆分对比对象
            compare_topics = [search_query]

        if len(compare_topics) < 2:
            return {"text": "请提供至少两个要对比的研究方向或论文标题。\n\n"
                           "例如:\n- \"对比强化学习和模仿学习在机器人控制中的应用\"\n"
                           "- \"比较Transformer和CNN在目标检测中的优劣\""}

        # 为每个方向搜索代表性论文（带回退）
        topic_data = {}
        total_found = 0
        for topic in compare_topics[:4]:
            found, strats = self._search_with_fallback(
                query=topic, limit=30,
                year_from=year_from, year_to=year_to,
                sort_by="citationCount", min_results=3,
            )
            topic_data[topic] = found[:15]
            total_found += len(found)
            logger.info(f"  对比搜索 [{topic[:30]}]: {len(found)} 篇 ({'; '.join(strats)})")

        # 检查是否有足够论文
        if total_found < 3:
            return {"text": f"⚠ 对比分析需要每个方向都有足够的文献数据。\n\n"
                           f"搜索结果:\n" +
                           "\n".join([f"- {t}: {len(p)} 篇" for t, p in topic_data.items()]) +
                           f"\n\n建议使用更通用的英文术语，或检查研究方向名称是否正确。"}

        # 构建AI对比分析的数据
        compare_info = ""
        for topic, papers in topic_data.items():
            compare_info += f"\n## 方向: {topic} (找到 {len(papers)} 篇)\n"
            for i, p in enumerate(papers[:8], 1):
                citation = getattr(p, '_citation_count', 0) or 0
                year = getattr(p, '_year', '') or ''
                compare_info += f"{i}. [{year}] {p.title} (引用:{citation})\n"
                if p.abstract:
                    compare_info += f"   摘要: {p.abstract[:120]}\n"

        prompt = f"""你是一位学术分析专家。请对以下几个研究方向进行对比分析:

对比方向: {', '.join(compare_topics)}

各方向的代表性文献:
{compare_info}

请用中文撰写对比分析报告，结构如下:
1. **各方向概述** (每个方向2-3句话描述核心思想)
2. **方法对比表** (用 Markdown 表格列出: 方向、核心方法、优势、局限性、适用场景)
3. **性能对比** (如果文献中有相关数据，总结关键性能指标的差异)
4. **研究热度对比** (基于论文数量和引用数比较各方向的研究活跃度)
5. **综合建议** (针对不同需求推荐最适合的方向)

总篇幅600-800字，使用 Markdown 格式。"""

        report = None
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "你是资深学术分析专家，擅长多方向对比研究。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.5, max_tokens=3000, timeout=90.0,
                )
                report = response.choices[0].message.content
                break
            except Exception as e:
                logger.warning(f"对比分析生成第{attempt+1}次失败: {e}")
                if attempt < 2:
                    import time
                    time.sleep(3 * (attempt + 1))

        lines = [f"## 📊 对比分析: {query_zh or ' vs '.join(compare_topics)}"]
        lines.append(f"> 对比方向: {' | '.join(compare_topics)}")
        total = sum(len(v) for v in topic_data.values())
        lines.append(f"> 参考文献总计: {total} 篇")
        lines.append("")

        if report:
            lines.append(report)
        else:
            lines.append("⚠ AI 对比分析生成失败，请稍后重试。")
            # 至少展示每个方向的 top 论文
            for topic, papers in topic_data.items():
                lines.append(f"\n### {topic} (前5篇)")
                for i, p in enumerate(papers[:5], 1):
                    citation = getattr(p, '_citation_count', 0) or 0
                    lines.append(f"{i}. {p.title} (引用:{citation})")

        return {"text": "\n".join(lines)}

    def _handle_gap(self, params: dict) -> Dict[str, Any]:
        """
        🧭 研究空白发现
        分析领域已有研究，识别尚未被充分探索的研究方向和潜在创新点
        """
        search_query = params.get("search_query", "")
        query_zh = params.get("query_zh", search_query)
        search_query_zh = params.get("search_query_zh", query_zh)
        year_from = params.get("year_from")
        year_to = params.get("year_to")
        current_year = datetime.now().year

        if not search_query:
            return {"text": "请提供要分析研究空白的领域。"}

        logger.info(f"[研究空白] 开始分析: '{search_query}' (中文: {query_zh})")

        # 搜索该领域的综述/survey论文 + 高引论文 → 使用回退策略
        all_papers = []
        all_strategies = []

        # 1. 综述/survey 搜索（带回退）
        survey_query = f"{search_query} survey review"
        survey_papers, s1 = self._search_with_fallback(
            query=survey_query, limit=50,
            year_from=year_from or (current_year - 5),
            sort_by="citationCount", min_results=3,
            query_zh=f"{search_query_zh} 综述"
        )
        all_papers.extend(survey_papers)
        all_strategies.extend([f"综述-{s}" for s in s1])
        logger.info(f"  综述搜索: {len(survey_papers)} 篇")

        # 2. 最新论文搜索（带回退）
        recent_papers, s2 = self._search_with_fallback(
            query=search_query, limit=100,
            year_from=current_year - 2, year_to=current_year,
            sort_by="citationCount", min_results=3,
            query_zh=search_query_zh
        )
        all_papers.extend(recent_papers)
        all_strategies.extend([f"最新-{s}" for s in s2])
        logger.info(f"  最新论文搜索: {len(recent_papers)} 篇")

        # 3. 如果综述和最新都不够，再试高引不限年份
        if len(survey_papers) + len(recent_papers) < 5:
            logger.info(f"  文献不足({len(survey_papers)}+{len(recent_papers)}), 尝试补充高引搜索...")
            try:
                extra = self.s2_fetcher.research_query(
                    query=search_query, limit=100, sort_by="citationCount",
                )
                all_papers.extend(extra)
                all_strategies.append(f"高引补充: {len(extra)}篇")
                logger.info(f"  高引补充: {len(extra)} 篇")
            except Exception as e:
                logger.warning(f"  高引补充搜索失败: {e}")

        # 去重
        unique = self._deduplicate_papers(all_papers)
        logger.info(f"  [研究空白] 去重后总计: {len(unique)} 篇")

        # 最低论文数检查
        MIN_PAPERS_FOR_GAP = 5
        if len(unique) < MIN_PAPERS_FOR_GAP:
            return {"text": self._insufficient_papers_message(
                query_zh, len(unique), all_strategies, MIN_PAPERS_FOR_GAP)}

        # 构建AI分析数据
        papers_info = ""
        for i, p in enumerate(unique[:30], 1):
            citation = getattr(p, '_citation_count', 0) or 0
            year = getattr(p, '_year', '') or ''
            papers_info += f"{i}. [{year}] {p.title} (引用:{citation})\n"
            if p.abstract:
                papers_info += f"   摘要: {p.abstract[:150]}\n"

        prompt = f"""你是一位学术研究顾问，擅长识别研究空白和创新机会。请根据以下「{query_zh}」领域的文献数据，分析研究空白。

## 文献数据 ({len(unique)} 篇):
{papers_info}

请用中文撰写研究空白分析报告，结构如下:
1. **领域研究现状概述** (100字，总结该领域已有研究的主要方向和成果)
2. **🔍 已识别的研究空白** (列出4-6个具体的研究空白，每个包含:)
   - 空白描述：具体是什么问题尚未被充分研究
   - 证据：为什么判断这是空白（基于文献数据）
   - 重要性：填补这个空白的意义
3. **💡 潜在创新方向** (基于已有工作和空白，提出3-5个具体可操作的创新研究方向)
4. **⚡ 推荐切入点** (对于初入该领域的研究者，推荐最容易切入且有潜力的2-3个方向)

总篇幅800-1000字。要求具体、可操作，避免泛泛而谈。"""

        report = None
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "你是资深学术研究顾问，擅长洞察研究空白和创新机会。请基于文献数据给出具体的分析。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.6,
                    max_tokens=3500,
                    timeout=90.0,
                )
                report = response.choices[0].message.content
                break
            except Exception as e:
                logger.warning(f"研究空白分析第{attempt+1}次失败: {e}")
                if attempt < 2:
                    import time
                    time.sleep(3 * (attempt + 1))

        lines = [f"## 🧭 研究空白分析: {query_zh}"]
        lines.append(f"> 基于 {len(unique)} 篇文献（含综述论文和最新研究）")
        lines.append("")

        if report:
            lines.append(report)
        else:
            lines.append("⚠ AI 分析生成失败，请稍后重试。")

        return {"text": "\n".join(lines)}

    def _handle_venue(self, params: dict) -> Dict[str, Any]:
        """
        📅 会议/期刊追踪
        追踪指定会议或期刊的最新论文，支持 ICRA, NeurIPS, Nature 等
        """
        venue_name = params.get("venue_name") or ""
        search_query = params.get("search_query", "")
        query_zh = params.get("query_zh", "")
        year_from = params.get("year_from")
        year_to = params.get("year_to")
        current_year = datetime.now().year

        if not venue_name and not search_query:
            return {"text": "请提供要追踪的会议或期刊名称。\n\n"
                           "支持的格式:\n"
                           "- \"追踪 ICRA 2025 的最新论文\"\n"
                           "- \"看看今年 Nature Robotics 发了哪些文章\"\n"
                           "- \"NeurIPS 2024 关于大模型的论文\""}

        # 构建搜索查询
        venue_query = venue_name or search_query
        topic_filter = search_query if venue_name else ""

        # 搜索该会议/期刊的论文（带回退）
        search_term = f"{venue_query} {topic_filter}".strip()
        all_papers, strategies = self._search_with_fallback(
            query=search_term, limit=100,
            year_from=year_from or (current_year - 1),
            year_to=year_to or current_year,
            sort_by="citationCount", min_results=3,
        )

        # 按 venue 字段过滤（S2返回的论文有 venue 信息）
        venue_lower = (venue_name or search_query).lower()
        # 提取简称（如 "ICRA", "NeurIPS", "CVPR" 等）
        venue_keywords = set(re.findall(r'[A-Za-z]+', venue_lower))

        venue_matched = []
        other_papers = []
        for p in all_papers:
            v = (getattr(p, '_venue', '') or '').lower()
            if any(kw in v for kw in venue_keywords if len(kw) >= 3):
                venue_matched.append(p)
            else:
                other_papers.append(p)

        # 优先展示 venue 匹配的
        display_papers = venue_matched + other_papers

        # 去重
        seen = set()
        unique = []
        for p in display_papers:
            key = p.title.strip().lower()
            if key not in seen:
                seen.add(key)
                unique.append(p)

        if not unique:
            return {"text": f"未找到 **{venue_query}** 的相关论文，请检查会议/期刊名称。"}

        lines = [f"## 📅 会议/期刊追踪: {venue_query}"]
        if topic_filter:
            lines.append(f"> 主题过滤: `{topic_filter}`")
        lines.append(f"> 找到 **{len(unique)}** 篇论文 ({year_from or current_year-1}-{year_to or current_year})")
        if venue_matched:
            lines.append(f"> 其中 {len(venue_matched)} 篇确认发表在该会议/期刊")
        lines.append("")

        # 按年份分组展示
        year_groups = {}
        for p in unique:
            y = getattr(p, '_year', '') or 'unknown'
            year_groups.setdefault(y, []).append(p)

        for y in sorted(year_groups.keys(), reverse=True):
            papers_in_year = year_groups[y]
            lines.append(f"### 📆 {y}年 ({len(papers_in_year)} 篇)")
            for i, p in enumerate(papers_in_year[:15], 1):
                citation = getattr(p, '_citation_count', 0) or 0
                venue = getattr(p, '_venue', '') or ''
                authors_str = ', '.join(p.authors[:3])
                if len(p.authors) > 3:
                    authors_str += ' et al.'
                lines.append(f"**{i}. {p.title}**")
                lines.append(f"> 👤 {authors_str} | 📖 {venue} | 📊 引用 {citation}")
                lines.append(f"> 🔗 [查看论文]({p.url})")
                lines.append("")

        return {"text": "\n".join(lines)}

    def _handle_topic_suggest(self, params: dict) -> Dict[str, Any]:
        """
        💡 选题建议助手
        根据用户的研究方向和兴趣，结合领域热点和研究空白，给出具体选题建议
        """
        search_query = params.get("search_query", "")
        query_zh = params.get("query_zh", search_query)
        search_query_zh = params.get("search_query_zh", query_zh)
        year_from = params.get("year_from")
        year_to = params.get("year_to")
        current_year = datetime.now().year

        if not search_query:
            return {"text": "请告诉我你的研究方向或感兴趣的领域，我来帮你推荐选题。\n\n"
                           "例如:\n- \"我想做机器人操作方面的研究，有什么好的选题建议？\"\n"
                           "- \"航天器在轨服务领域，给我推荐几个有潜力的研究课题\""}

        logger.info(f"[选题建议] 开始: '{search_query}' (中文: {query_zh})")

        # 搜集该领域数据: 高引 + 最新（带回退策略）
        all_papers = []
        all_strategies = []

        # 1. 高引经典论文
        high_cited, s1 = self._search_with_fallback(
            query=search_query, limit=50,
            year_from=current_year - 5,
            sort_by="citationCount", min_results=3,
            query_zh=search_query_zh,
        )
        all_papers.extend(high_cited)
        all_strategies.extend([f"高引-{s}" for s in s1])

        # 2. 最新研究
        recent, s2 = self._search_with_fallback(
            query=search_query, limit=50,
            year_from=current_year - 1, year_to=current_year,
            sort_by="citationCount", min_results=3,
            query_zh=search_query_zh,
        )
        all_papers.extend(recent)
        all_strategies.extend([f"最新-{s}" for s in s2])

        # 去重
        unique = self._deduplicate_papers(all_papers)
        logger.info(f"  [选题建议] 去重后: {len(unique)} 篇")

        # 最低论文数检查
        MIN_PAPERS_FOR_TOPIC = 5
        if len(unique) < MIN_PAPERS_FOR_TOPIC:
            return {"text": self._insufficient_papers_message(
                query_zh, len(unique), all_strategies, MIN_PAPERS_FOR_TOPIC)}

        # 构建数据
        papers_info = ""
        for i, p in enumerate(unique[:30], 1):
            citation = getattr(p, '_citation_count', 0) or 0
            year = getattr(p, '_year', '') or ''
            papers_info += f"{i}. [{year}] {p.title} (引用:{citation})\n"
            if p.abstract:
                papers_info += f"   摘要: {p.abstract[:120]}\n"

        prompt = f"""你是一位资深科研导师，擅长指导学生选题。用户对「{query_zh}」领域感兴趣，请根据以下文献数据为其推荐研究选题。

## 领域文献 ({len(unique)} 篇):
{papers_info}

请用中文给出选题建议，结构如下:

1. **领域现状评估** (100字，总结该领域的研究成熟度和活跃度)

2. **🎯 推荐选题** (推荐5-7个具体的研究选题，每个包含:)
   - **选题名称**: 明确具体的研究题目
   - **研究内容**: 2-3句话描述要做什么
   - **创新点**: 为什么这个方向有创新性
   - **可行性**: ⭐⭐⭐⭐⭐ (5星评价)
   - **潜力**: ⭐⭐⭐⭐⭐ (5星评价)

3. **📋 选题对比表** (用 Markdown 表格: 选题、创新性、可行性、工作量、建议人群)

4. **💬 选题策略建议** (100字，给出整体的选题策略建议)

要求:
- 选题必须具体、可操作，不能太宽泛
- 兼顾不同层次（本科生/硕士/博士）
- 区分理论研究和工程应用类选题"""

        report = None
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "你是资深科研导师，擅长根据研究前沿为学生推荐具体可行的选题。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.6,
                    max_tokens=4000,
                    timeout=90.0,
                )
                report = response.choices[0].message.content
                break
            except Exception as e:
                logger.warning(f"选题建议生成第{attempt+1}次失败: {e}")
                if attempt < 2:
                    import time
                    time.sleep(3 * (attempt + 1))

        lines = [f"## 💡 选题建议: {query_zh}"]
        lines.append(f"> 基于 {len(unique)} 篇文献（高引经典 + 最新前沿）")
        lines.append("")

        if report:
            lines.append(report)
        else:
            lines.append("⚠ AI 选题建议生成失败，请稍后重试。")

        return {"text": "\n".join(lines)}

    def _handle_question(self, message: str) -> Dict[str, Any]:
        """处理一般研究问题（无上下文）"""
        return self._handle_question_with_context(message, "")

    def _handle_question_with_context(self, message: str, user_id: str = "") -> Dict[str, Any]:
        """
        处理带上下文的对话 — 智能体核心

        利用完整对话历史，实现多轮学术讨论：
        - 理解追问（如"能详细说说第3个方向吗？"）
        - 根据之前的分析结果继续深入讨论
        - 可以根据新意见重新查询
        """
        # 构建对话消息列表
        messages = [
            {"role": "system", "content": """你是一位专业的科研AI助手，正在与用户进行多轮学术讨论。

你的能力:
- 回答科研问题，提供专业的学术分析
- 记住之前的对话内容，理解追问和后续讨论
- 如果用户提到"第X个方向"、"上面的"、"刚才的"等指代词，根据对话历史理解
- 如果用户想要更深入的分析或换个角度讨论，基于之前的结果继续
- 如果用户想做新的搜索/分析，建议使用相应功能

格式要求:
- 用中文回答，使用 Markdown 格式
- 如果用户追问之前分析的某个子方向，给出深入的解读
- 如果需要文献支撑，可以主动建议"我可以帮你搜索相关文献"
- 回答控制在 500 字以内"""}
        ]

        # 注入对话历史
        if user_id:
            conv = self._conversations.get(user_id, {})
            history = conv.get("messages", [])
            # 取最近的对话历史（不包括当前消息，因为已经在 handle_message 中添加了）
            for msg in history[-12:-1]:  # 排除最后一条（就是当前用户消息）
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"][:1500],
                })

        # 当前消息
        messages.append({"role": "user", "content": message})

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.5,
                max_tokens=2000,
                timeout=60.0,
            )
            answer = response.choices[0].message.content
            return {"text": answer}
        except Exception as e:
            logger.error(f"对话回答失败: {e}")
            return {"text": "抱歉，处理您的问题时出现错误，请稍后重试。"}

    def _export_conversation(self, user_id: str) -> Dict[str, Any]:
        """
        导出对话历史为 Markdown 文件
        """
        conv = self._conversations.get(user_id, {})
        messages = conv.get("messages", [])

        if not messages:
            return {"text": "当前没有对话记录可以导出。"}

        # 生成 Markdown
        lines = [
            f"# AI 研究助理 - 对话记录",
            f"",
            f"**导出时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**对话轮数**: {len([m for m in messages if m['role'] == 'user'])} 轮",
            f"",
            "---",
            "",
        ]

        for msg in messages:
            time_str = msg.get("time", "")[:19]
            if msg["role"] == "user":
                lines.append(f"## 🧑 用户 ({time_str})")
                lines.append("")
                lines.append(msg["content"])
                lines.append("")
            else:
                lines.append(f"## 🤖 AI 助理 ({time_str})")
                lines.append("")
                lines.append(msg["content"])
                lines.append("")
            lines.append("---")
            lines.append("")

        content = "\n".join(lines)

        # 保存文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"chat_{user_id[:8]}_{timestamp}.md"
        filepath = os.path.join(self._chat_logs_dir, filename)

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"对话导出成功: {filepath}")

            file_server = self.config.get("dingtalk_bot", {}).get("file_server_url", "http://127.0.0.1:5679")
            return {
                "text": f"✅ 对话记录已导出（{len(messages)} 条消息）",
                "files": [{
                    "name": filename,
                    "path": filepath,
                    "url": f"{file_server}/download/{filename}",
                }],
            }
        except Exception as e:
            logger.error(f"对话导出失败: {e}")
            return {"text": "对话导出失败，请稍后重试。"}

    def _do_export(self, papers: List[Paper], fmt: str, topic: str) -> List[Dict]:
        """执行文献导出 — 支持 BibTeX / CSV / Excel / Word / all"""
        files = []
        safe_topic = re.sub(r'[^\w\u4e00-\u9fff]', '_', topic)[:30]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_server = self.config.get("dingtalk_bot", {}).get("file_server_url", "http://127.0.0.1:5679")

        def _add_file(path, name):
            if path:
                fname = path.split('/')[-1] if '/' in path else path.split(chr(92))[-1]
                files.append({
                    "name": name,
                    "path": path,
                    "url": f"{file_server}/download/{fname}",
                })

        prefix = f"{safe_topic}_{timestamp}"

        if fmt in ("bib", "bibtex"):
            _add_file(self.exporter.export_bibtex(papers, prefix), f"{safe_topic}.bib")

        elif fmt in ("csv",):
            _add_file(self.exporter.export_csv(papers, prefix), f"{safe_topic}.csv")

        elif fmt in ("excel", "xlsx", "xls"):
            _add_file(self.exporter.export_excel(papers, prefix), f"{safe_topic}.xlsx")

        elif fmt in ("docx", "word"):
            # 单独导出 Word（无综述，只是文献列表）
            _add_file(self.exporter.export_excel(papers, prefix), f"{safe_topic}.xlsx")

        elif fmt == "all":
            # 同时导出 BibTeX + Excel
            _add_file(self.exporter.export_bibtex(papers, prefix), f"{safe_topic}.bib")
            _add_file(self.exporter.export_excel(papers, prefix), f"{safe_topic}.xlsx")

        else:
            # 默认导出 BibTeX + Excel
            _add_file(self.exporter.export_bibtex(papers, prefix), f"{safe_topic}.bib")
            _add_file(self.exporter.export_excel(papers, prefix), f"{safe_topic}.xlsx")

        return files

    def _generate_research_summary(self, papers: List[Paper], query_zh: str, query_en: str) -> str:
        """用 AI 生成文献调研的简要总结分析"""
        # 收集论文信息（取 top 20 篇用于总结）
        top_papers = papers[:20]
        papers_info = ""
        for i, p in enumerate(top_papers, 1):
            citation = getattr(p, '_citation_count', 0) or 0
            year = getattr(p, '_year', '') or ''
            venue = getattr(p, '_venue', '') or ''
            papers_info += f"{i}. [{year}] {p.title} (引用:{citation}, 期刊:{venue})\n"
            if p.abstract:
                papers_info += f"   摘要: {p.abstract[:120]}\n"

        # 统计年份分布
        years = [getattr(p, '_year', 0) or 0 for p in papers if getattr(p, '_year', 0)]
        year_dist = {}
        for y in years:
            year_dist[y] = year_dist.get(y, 0) + 1
        year_dist_str = ', '.join(f"{k}:{v}篇" for k, v in sorted(year_dist.items())[-5:])

        prompt = f"""你是一位学术研究分析专家。请根据以下与「{query_zh}」相关的 {len(papers)} 篇文献，
撰写一段简洁的研究领域总结（300-500字），包含：

1. **研究现状概述**：该领域的整体研究状态和主要方向
2. **主要方法/技术**：最常用的几种研究方法或技术路线
3. **研究趋势**：近年来的发展趋势或热点变化
4. **关键发现**：重要的研究结论或突破

统计信息：共 {len(papers)} 篇文献，年份分布: {year_dist_str}

代表性文献列表:
{papers_info}

要求:
- 用中文撰写，语言简洁专业
- 不要列举论文标题，要概括性总结
- 直接输出总结内容，不要加标题"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是学术研究分析专家，擅长总结文献调研结果。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1000,
            )
            summary = response.choices[0].message.content.strip()
            logger.info(f"  AI 研究总结已生成 ({len(summary)} 字)")
            return summary
        except Exception as e:
            logger.error(f"  AI 研究总结生成失败: {e}")
            return ""

    def _help_text(self) -> str:
        """生成帮助信息"""
        return """## 🤖 AI 研究助理 - 使用指南

### 📚 文献调研
- "帮我搜索机器人抓取相关的论文"
- "查找2023年以来关于大语言模型的文献"
- "搜索 Yann LeCun 关于深度学习的论文"
- "查找清华大学在机器人领域的研究"

### 📖 文献综述（自动生成 Word 文档）
- "写一篇关于空间碎片主动清除技术的文献综述"
- 自动生成 Word + Excel + BibTeX 三种格式

### 🔥 领域热点分析
- "分析一下机器人操作领域的研究热点"
- "深度学习最近几年的前沿趋势是什么"

### 📊 论文对比分析
- "对比强化学习和模仿学习在机器人中的应用"
- "比较Transformer和CNN在目标检测中的表现"

### 🧭 研究空白发现
- "航天器在轨服务领域有哪些研究空白？"
- "分析机械臂抓取领域有什么创新机会"

### 🔗 引用链追踪
- "追踪Attention is All You Need的引用网络"
- "分析这篇论文的引用脉络: xxx"

### 📅 会议/期刊追踪
- "追踪 ICRA 2025 的最新论文"
- "NeurIPS 2024 关于大模型的论文"

### 💡 选题建议
- "我想做机器人操作方向，有什么选题建议？"
- "航天器编队飞行领域推荐几个研究课题"

### 👤 作者查询
- "查询 Yoshua Bengio 的信息和代表作"

### 📦 文献导出
- "导出机器人导航相关文献的Excel"

### ❓ 研究问题
- 直接提问: "强化学习和模仿学习有什么区别？"

---
💡 搜索关键词用英文效果更好 | 综述自动生成 Word/Excel/BibTeX | 医学领域自动补充 PubMed 数据

### 🔄 多轮对话
- 分析完毕后可以直接追问，如"详细说说第3个方向"
- 输入 **清空对话** 重置上下文
- 输入 **导出对话** 保存对话记录为 Markdown"""
