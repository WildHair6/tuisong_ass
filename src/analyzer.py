"""
AI分析模块 - 使用 DeepSeek 对论文进行评价、筛选和热点分析
"""

import json
import logging
from typing import List, Tuple
from openai import OpenAI

from .fetcher import Paper

logger = logging.getLogger(__name__)


class PaperAnalyzer:
    """使用 DeepSeek API 分析论文"""

    def __init__(self, config: dict):
        ai_config = config["ai"]
        self.client = OpenAI(
            api_key=ai_config["api_key"],
            base_url=ai_config["base_url"],
            timeout=120.0  # 2分钟超时
        )
        self.model = ai_config["model"]
        self.temperature = ai_config.get("temperature", 0.3)
        self.max_tokens = ai_config.get("max_tokens", 4096)
        self.score_threshold = config["research"].get("score_threshold", 6)
        self.max_papers = config["research"].get("max_papers", 10)
        self.style = config.get("article", {}).get("style", "academic")

    def analyze_and_filter(self, papers: List[Paper]) -> List[Paper]:
        """
        对论文进行AI分析、打分和筛选

        Args:
            papers: 待分析的论文列表

        Returns:
            筛选后的高质量论文列表（已含中文摘要和评价）
        """
        if not papers:
            logger.warning("没有待分析的论文")
            return []

        logger.info(f"开始AI分析 {len(papers)} 篇论文...")

        # 批量分析（每批5篇，节省API调用）
        batch_size = 5
        analyzed_papers = []

        for i in range(0, len(papers), batch_size):
            batch = papers[i:i + batch_size]
            try:
                results = self._batch_analyze(batch)
                analyzed_papers.extend(results)
                logger.info(f"已分析 {min(i + batch_size, len(papers))}/{len(papers)} 篇")
            except Exception as e:
                logger.error(f"批量分析失败: {e}")
                # 单篇重试
                for paper in batch:
                    try:
                        result = self._single_analyze(paper)
                        analyzed_papers.append(result)
                    except Exception as e2:
                        logger.error(f"单篇分析失败 [{paper.arxiv_id}]: {e2}")

        # 按评分筛选和排序
        qualified = [p for p in analyzed_papers if p.score >= self.score_threshold]
        qualified.sort(key=lambda p: p.score, reverse=True)

        # 限制数量
        result = qualified[:self.max_papers]
        logger.info(f"AI筛选完成: {len(analyzed_papers)} 篇分析 → {len(result)} 篇推送")
        return result

    def _batch_analyze(self, papers: List[Paper]) -> List[Paper]:
        """批量分析多篇论文"""
        papers_info = ""
        for idx, p in enumerate(papers, 1):
            papers_info += f"""
--- 论文 {idx} ---
标题: {p.title}
作者: {', '.join(p.authors[:5])}
摘要: {p.abstract[:500]}
分类: {', '.join(p.categories)}
匹配关键词: {', '.join(p.keywords_matched)}
"""

        prompt = f"""你是一位资深的科研论文评审专家，擅长航天器、机器人、自动控制等领域。
请对以下{len(papers)}篇论文逐一进行分析评价。

{papers_info}

请严格按照以下JSON格式输出（不要有任何额外文字）:
{{
  "papers": [
    {{
      "index": 1,
      "score": 8.5,
      "summary_zh": "200字以内的中文摘要，需要包含核心方法和主要贡献",
      "innovation": "50字以内，说明创新点",
      "relevance": "30字以内，与航天/机器人领域的相关性说明",
      "practical_value": "30字以内，实际应用价值评估"
    }}
  ]
}}

评分标准(1-10分):
- 9-10: 重大突破，顶级期刊水平
- 7-8: 有明显创新，值得关注
- 5-6: 一般性工作，有参考价值
- 3-4: 增量改进，参考价值有限
- 1-2: 相关性低或质量不高"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是专业的科研论文评审助手，只输出JSON格式。"},
                {"role": "user", "content": prompt}
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"}
        )

        result_text = response.choices[0].message.content
        result = json.loads(result_text)

        for item in result.get("papers", []):
            idx = item["index"] - 1
            if 0 <= idx < len(papers):
                papers[idx].score = float(item.get("score", 0))
                papers[idx].summary_zh = item.get("summary_zh", "")
                papers[idx].innovation = item.get("innovation", "")
                papers[idx].relevance = item.get("relevance", "")
                papers[idx].practical_value = item.get("practical_value", "")

        return papers

    def _single_analyze(self, paper: Paper) -> Paper:
        """单篇论文分析（备用方案）"""
        prompt = f"""请分析以下论文:

标题: {paper.title}
作者: {', '.join(paper.authors[:5])}
摘要: {paper.abstract[:800]}
分类: {', '.join(paper.categories)}

请按JSON格式输出:
{{
  "score": 8.0,
  "summary_zh": "中文摘要(200字)",
  "innovation": "创新点(50字)",
  "relevance": "领域相关性(30字)",
  "practical_value": "应用价值(30字)"
}}"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是专业的科研论文评审助手，只输出JSON格式。"},
                {"role": "user", "content": prompt}
            ],
            temperature=self.temperature,
            max_tokens=1024,
            response_format={"type": "json_object"}
        )

        result = json.loads(response.choices[0].message.content)
        paper.score = float(result.get("score", 0))
        paper.summary_zh = result.get("summary_zh", "")
        paper.innovation = result.get("innovation", "")
        paper.relevance = result.get("relevance", "")
        paper.practical_value = result.get("practical_value", "")

        return paper

    def generate_trends(self, papers: List[Paper]) -> str:
        """
        综合分析当日论文，生成研究热点趋势报告

        Args:
            papers: 当日高分论文列表

        Returns:
            研究热点分析的Markdown文本
        """
        if not papers:
            return "今日暂无符合条件的论文，无法生成热点分析。"

        papers_summary = ""
        for idx, p in enumerate(papers, 1):
            papers_summary += f"{idx}. [{p.score}分] {p.title}\n   {p.summary_zh[:100]}\n\n"

        prompt = f"""你是一位科研趋势分析专家。以下是今日筛选出的{len(papers)}篇高质量论文:

{papers_summary}

请综合分析这些论文，生成一份"今日研究热点"报告，包含:

1. **热点方向总结**: 提炼2-3个今日主要研究热点方向
2. **趋势洞察**: 这些研究反映了哪些前沿技术发展趋势
3. **值得关注**: 哪1-2篇论文最值得深入阅读，为什么
4. **技术展望**: 基于今日论文，预判未来可能的研究突破点

请用中文撰写，风格{'严谨学术' if self.style == 'academic' else '通俗易懂'}，
总篇幅控制在500字以内。使用Markdown格式。"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是资深科研趋势分析师，擅长把握前沿动态。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=2048
        )

        return response.choices[0].message.content

    def generate_article_title(self, papers: List[Paper], date_str: str) -> str:
        """生成公众号文章标题"""
        top_topics = []
        for p in papers[:3]:
            top_topics.append(p.title[:30])

        prompt = f"""请为一篇科研论文日报（{date_str}）生成一个吸引人的微信公众号标题。
今日重点论文主题: {'; '.join(top_topics)}

要求:
- 20-30个中文字符
- 突出最有趣的研究发现
- 适当使用数字或具体信息增加吸引力
- 不要过于标题党

只输出标题本身，不要其他内容。"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=100
        )

        return response.choices[0].message.content.strip().strip('"').strip('《').strip('》')
