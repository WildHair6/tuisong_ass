"""
Semantic Scholar 数据源 - 补充 arXiv 以外的论文
支持更多期刊论文（不仅限于预印本）
"""

import requests
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from .fetcher import Paper

logger = logging.getLogger(__name__)

# Semantic Scholar API 免费配额: 100次/5分钟
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1"


class SemanticScholarFetcher:
    """
    从 Semantic Scholar 获取论文
    
    优势:
    - 覆盖范围更广（不限于arXiv，包含各大出版商的期刊论文）
    - 提供引用数、影响力等指标
    - 免费API，无需注册
    
    API文档: https://api.semanticscholar.org/api-docs/
    """

    def __init__(self, config: dict):
        self.keywords = config["research"]["keywords"]
        self.max_papers = config["research"].get("max_papers", 10)
        self.api_key = config.get("semantic_scholar", {}).get("api_key", None)
        self.session = requests.Session()
        if self.api_key:
            self.session.headers["x-api-key"] = self.api_key

    def fetch_recent_papers(self, days: int = 7) -> List[Paper]:
        """
        搜索最近N天的论文
        
        注意: Semantic Scholar 的索引有延迟（通常1-3天），
        所以默认搜索最近7天来确保覆盖。
        """
        import time
        all_papers = []

        for keyword in self.keywords[:5]:  # 限制关键词数避免超频
            try:
                papers = self._search_keyword(keyword, days)
                all_papers.extend(papers)
                logger.info(f"Semantic Scholar [{keyword}]: 获取 {len(papers)} 篇")
                time.sleep(3.5)  # 遵守速率限制: 100次/5分钟
            except Exception as e:
                logger.warning(f"Semantic Scholar [{keyword}] 搜索失败: {e}")
                time.sleep(5)  # 限流后多等一会

        # 去重
        seen_ids = set()
        unique = []
        for p in all_papers:
            if p.arxiv_id not in seen_ids:
                seen_ids.add(p.arxiv_id)
                unique.append(p)

        logger.info(f"Semantic Scholar 共获取 {len(unique)} 篇去重论文")
        return unique

    def _search_keyword(self, keyword: str, days: int) -> List[Paper]:
        """按关键词搜索论文"""
        # 计算日期范围
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        date_to = datetime.now().strftime("%Y-%m-%d")

        url = f"{SEMANTIC_SCHOLAR_API}/paper/search"
        params = {
            "query": keyword,
            "limit": 50,
            "fields": "title,authors,abstract,externalIds,url,publicationDate,citationCount,fieldsOfStudy,openAccessPdf",
            "publicationDateOrYear": f"{date_from}:{date_to}",
            "openAccessPdf": "",  # 只获取有开放获取PDF的论文
        }

        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        papers = []
        for item in data.get("data", []):
            if not item.get("abstract"):
                continue

            # 提取 arXiv ID（如果有）
            external_ids = item.get("externalIds", {})
            arxiv_id = external_ids.get("ArXiv", "")
            paper_id = arxiv_id or external_ids.get("DOI", "") or item.get("paperId", "")

            # 提取PDF链接
            pdf_info = item.get("openAccessPdf", {})
            pdf_url = pdf_info.get("url", "") if pdf_info else ""

            # 解析发布日期
            pub_date_str = item.get("publicationDate", "")
            try:
                pub_date = datetime.strptime(pub_date_str, "%Y-%m-%d") if pub_date_str else datetime.now()
            except ValueError:
                pub_date = datetime.now()

            paper = Paper(
                title=item.get("title", "").strip(),
                authors=[a.get("name", "") for a in (item.get("authors", []) or [])[:10]],
                abstract=item.get("abstract", "").strip(),
                arxiv_id=f"s2-{paper_id}",  # 加前缀区分来源
                url=item.get("url", f"https://www.semanticscholar.org/paper/{item.get('paperId', '')}"),
                pdf_url=pdf_url,
                categories=item.get("fieldsOfStudy", []) or [],
                published=pub_date,
                updated=pub_date,
                keywords_matched=[keyword]
            )
            papers.append(paper)

        return papers

    def enrich_paper_metadata(self, arxiv_id: str) -> Optional[dict]:
        """
        用 Semantic Scholar 补充论文的引用数等元数据
        
        Args:
            arxiv_id: arXiv ID（如 2401.12345）
        
        Returns:
            包含 citationCount, influentialCitationCount 等信息的字典
        """
        try:
            url = f"{SEMANTIC_SCHOLAR_API}/paper/ArXiv:{arxiv_id}"
            params = {
                "fields": "citationCount,influentialCitationCount,referenceCount,fieldsOfStudy"
            }
            response = self.session.get(url, params=params, timeout=15)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.debug(f"元数据补充失败 [{arxiv_id}]: {e}")
        return None
