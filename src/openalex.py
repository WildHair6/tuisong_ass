"""
OpenAlex 数据源 - 微软学术(Microsoft Academic)的继承者
覆盖 2.5亿+ 学术作品，完全免费开放

API文档: https://docs.openalex.org/
特点:
- 完全免费，无需注册
- 数据量大，更新快
- 支持按概念(concept)、机构、期刊等多维度检索
- 提供引用网络和影响力指标
"""

import requests
import logging
from datetime import datetime, timedelta
from typing import List

from .fetcher import Paper

logger = logging.getLogger(__name__)

OPENALEX_API = "https://api.openalex.org"


class OpenAlexFetcher:
    """从 OpenAlex 获取学术论文"""

    def __init__(self, config: dict):
        self.keywords = config["research"]["keywords"]
        self.max_results = config["research"].get("max_papers", 10) * 5
        self.contact_email = config.get("openalex", {}).get("email", "")
        self.session = requests.Session()
        # OpenAlex 推荐设置邮箱以进入"polite pool"（更快响应）
        if self.contact_email:
            self.session.params = {"mailto": self.contact_email}

    def fetch_recent_papers(self, days: int = 7) -> List[Paper]:
        """
        获取最近N天发表的论文
        
        OpenAlex 使用概念(concept)体系分类论文，
        也支持全文搜索。
        """
        all_papers = []

        # 方式1: 按关键词搜索
        for keyword in self.keywords[:6]:  # 限制请求数
            try:
                papers = self._search_by_keyword(keyword, days)
                all_papers.extend(papers)
                logger.info(f"OpenAlex [{keyword}]: 获取 {len(papers)} 篇")
            except Exception as e:
                logger.warning(f"OpenAlex [{keyword}] 搜索失败: {e}")

        # 去重
        seen = set()
        unique = []
        for p in all_papers:
            if p.arxiv_id not in seen:
                seen.add(p.arxiv_id)
                unique.append(p)

        logger.info(f"OpenAlex 共获取 {len(unique)} 篇去重论文")
        return unique

    def _search_by_keyword(self, keyword: str, days: int) -> List[Paper]:
        """按关键词搜索论文"""
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        url = f"{OPENALEX_API}/works"
        params = {
            "search": keyword,
            "filter": f"from_publication_date:{date_from},type:article,has_abstract:true",
            "sort": "publication_date:desc",
            "per_page": min(self.max_results, 50),
            "select": "id,doi,title,authorships,abstract_inverted_index,publication_date,"
                      "primary_location,concepts,cited_by_count,open_access,type"
        }

        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        papers = []
        for item in data.get("results", []):
            try:
                paper = self._parse_work(item, keyword)
                if paper:
                    papers.append(paper)
            except Exception as e:
                logger.debug(f"解析 OpenAlex 论文失败: {e}")

        return papers

    def _parse_work(self, item: dict, matched_keyword: str) -> Paper:
        """解析 OpenAlex 返回的单篇论文"""
        title = item.get("title", "")
        if not title:
            return None

        # 还原倒排索引格式的摘要
        abstract = self._reconstruct_abstract(item.get("abstract_inverted_index", {}))
        if not abstract:
            return None

        # 提取作者
        authors = []
        for authorship in (item.get("authorships", []) or [])[:10]:
            author = authorship.get("author", {})
            name = author.get("display_name", "")
            if name:
                authors.append(name)

        # 提取DOI和ID
        doi = (item.get("doi") or "").replace("https://doi.org/", "")
        openalex_id = (item.get("id") or "").split("/")[-1]

        # 提取发布日期
        pub_date_str = item.get("publication_date", "")
        try:
            pub_date = datetime.strptime(pub_date_str, "%Y-%m-%d") if pub_date_str else datetime.now()
        except ValueError:
            pub_date = datetime.now()

        # 提取期刊/来源
        location = item.get("primary_location", {}) or {}
        source = location.get("source", {}) or {}
        journal = source.get("display_name", "")

        # 提取URL和PDF链接
        url = item.get("doi") or f"https://openalex.org/{openalex_id}"
        
        oa = item.get("open_access", {}) or {}
        pdf_url = oa.get("oa_url", "") or ""

        # 提取概念分类
        concepts = []
        for concept in (item.get("concepts", []) or [])[:5]:
            if concept.get("score", 0) > 0.3:  # 只取相关度>0.3的概念
                concepts.append(concept.get("display_name", ""))

        categories = [journal] + concepts if journal else concepts

        # 引用数
        cited_by = item.get("cited_by_count", 0)

        # 关键词匹配
        text = (title + " " + abstract).lower()
        matched = [kw for kw in self.keywords if kw.lower() in text]

        if not matched:
            return None

        paper = Paper(
            title=title,
            authors=authors,
            abstract=abstract[:1000],
            arxiv_id=f"oa-{doi or openalex_id}",  # 加前缀区分来源
            url=url,
            pdf_url=pdf_url,
            categories=categories,
            published=pub_date,
            updated=pub_date,
            keywords_matched=matched
        )

        return paper

    @staticmethod
    def _reconstruct_abstract(inverted_index: dict) -> str:
        """
        OpenAlex 用倒排索引存储摘要，需要还原。
        格式: {"word1": [0, 5], "word2": [1, 3]} → 按位置排列还原文本
        """
        if not inverted_index:
            return ""

        # 构建 (position, word) 列表
        word_positions = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))

        # 按位置排序并拼接
        word_positions.sort(key=lambda x: x[0])
        return " ".join(word for _, word in word_positions)
