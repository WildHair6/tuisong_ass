"""
论文抓取模块 - 论文数据结构 & arXiv 获取（可选）
"""

try:
    import arxiv
    HAS_ARXIV = True
except ImportError:
    HAS_ARXIV = False

import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Paper:
    """论文数据结构"""
    title: str
    authors: List[str]
    abstract: str
    arxiv_id: str
    url: str
    pdf_url: str
    categories: List[str]
    published: datetime
    updated: datetime
    # 以下字段在AI分析后填充
    score: float = 0.0
    summary_zh: str = ""
    innovation: str = ""
    relevance: str = ""
    practical_value: str = ""
    keywords_matched: List[str] = field(default_factory=list)


class PaperFetcher:
    """从 arXiv 抓取最新论文（可选，需要 arxiv 包）"""

    def __init__(self, config: dict):
        if not HAS_ARXIV:
            raise ImportError("arxiv 包未安装。如需使用 arXiv 数据源，请运行: pip install arxiv")
        self.categories = config["research"]["arxiv_categories"]
        self.keywords = config["research"]["keywords"]
        self.max_papers = config["research"].get("max_papers", 10)

    def fetch_recent_papers(self, days: int = 2) -> List[Paper]:
        """
        获取最近N天内指定领域的论文
        
        Args:
            days: 回溯天数，默认2天（确保不遗漏）
        
        Returns:
            Paper列表
        """
        all_papers = []

        for category in self.categories:
            try:
                papers = self._fetch_by_category(category, days)
                all_papers.extend(papers)
                logger.info(f"从 {category} 获取到 {len(papers)} 篇论文")
            except Exception as e:
                logger.error(f"获取 {category} 论文失败: {e}")

        # 去重（按 arXiv ID）
        seen_ids = set()
        unique_papers = []
        for paper in all_papers:
            if paper.arxiv_id not in seen_ids:
                seen_ids.add(paper.arxiv_id)
                unique_papers.append(paper)

        logger.info(f"共获取 {len(unique_papers)} 篇去重后的论文")

        # 关键词过滤
        filtered = self._filter_by_keywords(unique_papers)
        logger.info(f"关键词过滤后剩余 {len(filtered)} 篇论文")

        return filtered

    def _fetch_by_category(self, category: str, days: int) -> List[Paper]:
        """按分类从 arXiv 获取论文"""
        # 构建搜索查询
        query = f"cat:{category}"

        client = arxiv.Client(
            page_size=100,
            delay_seconds=3.0,  # 遵守 arXiv 速率限制
            num_retries=3
        )

        search = arxiv.Search(
            query=query,
            max_results=200,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending
        )

        cutoff_date = datetime.now(tz=None) - timedelta(days=days)
        papers = []

        for result in client.results(search):
            # 过滤日期 - arXiv 返回的是 UTC 时间
            pub_date = result.published.replace(tzinfo=None)
            if pub_date < cutoff_date:
                break  # 已经按时间排序，后面的更早

            paper = Paper(
                title=result.title.strip().replace("\n", " "),
                authors=[str(a) for a in result.authors[:10]],  # 最多10位作者
                abstract=result.summary.strip().replace("\n", " "),
                arxiv_id=result.entry_id.split("/")[-1],
                url=result.entry_id,
                pdf_url=result.pdf_url,
                categories=[str(c) for c in result.categories],
                published=pub_date,
                updated=result.updated.replace(tzinfo=None)
            )
            papers.append(paper)

        return papers

    def _filter_by_keywords(self, papers: List[Paper]) -> List[Paper]:
        """通过关键词过滤论文"""
        if not self.keywords:
            return papers

        filtered = []
        for paper in papers:
            text = (paper.title + " " + paper.abstract).lower()
            matched = [kw for kw in self.keywords if kw.lower() in text]
            if matched:
                paper.keywords_matched = matched
                filtered.append(paper)

        return filtered

    def fetch_and_sort(self, days: int = 2) -> List[Paper]:
        """
        获取论文并按相关性初步排序
        匹配关键词越多的排在前面
        """
        papers = self.fetch_recent_papers(days)
        papers.sort(key=lambda p: len(p.keywords_matched), reverse=True)
        return papers
