"""
CrossRef 数据源 - 获取正式出版的期刊论文
覆盖 Elsevier, Springer, IEEE, Wiley 等主要出版商

API文档: https://api.crossref.org/swagger-ui/index.html
免费，无需API Key，建议设置联系邮箱以获得更高速率（polite pool）
"""

import requests
import logging
from datetime import datetime, timedelta
from typing import List

from .fetcher import Paper

logger = logging.getLogger(__name__)

CROSSREF_API = "https://api.crossref.org/works"


class CrossRefFetcher:
    """从 CrossRef 获取正式出版的期刊论文"""

    def __init__(self, config: dict):
        self.keywords = config["research"]["keywords"]
        self.max_results = config["research"].get("max_papers", 10) * 5  # 多取一些用于筛选
        self.contact_email = config.get("crossref", {}).get("email", "")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": f"PaperPushBot/1.0 (mailto:{self.contact_email})" if self.contact_email
                          else "PaperPushBot/1.0"
        })

    def fetch_recent_papers(self, days: int = 7) -> List[Paper]:
        """
        获取最近N天内发表的期刊论文
        
        CrossRef 索引延迟较长，建议搜索7天以上范围。
        """
        all_papers = []

        # 构建关键词搜索（每次搜索2-3个关键词组合）
        keyword_groups = self._group_keywords(self.keywords, group_size=3)

        for group in keyword_groups[:5]:  # 最多5组查询
            try:
                query = " OR ".join(group)
                papers = self._search(query, days)
                all_papers.extend(papers)
                logger.info(f"CrossRef [{query[:40]}...]: 获取 {len(papers)} 篇")
            except Exception as e:
                logger.warning(f"CrossRef 搜索失败 [{group}]: {e}")

        # 去重
        seen = set()
        unique = []
        for p in all_papers:
            if p.arxiv_id not in seen:
                seen.add(p.arxiv_id)
                unique.append(p)

        logger.info(f"CrossRef 共获取 {len(unique)} 篇去重论文")
        return unique

    def _search(self, query: str, days: int) -> List[Paper]:
        """执行CrossRef搜索"""
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        date_to = datetime.now().strftime("%Y-%m-%d")

        params = {
            "query": query,
            "rows": min(self.max_results, 100),
            "sort": "published",
            "order": "desc",
            "filter": f"from-pub-date:{date_from},until-pub-date:{date_to},type:journal-article",
            "select": "DOI,title,author,abstract,published,container-title,subject,link,URL"
        }

        response = self.session.get(CROSSREF_API, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        papers = []
        for item in data.get("message", {}).get("items", []):
            # 提取标题
            titles = item.get("title", [])
            title = titles[0] if titles else ""
            if not title:
                continue

            # 提取摘要（CrossRef的摘要可能包含HTML标签）
            abstract = item.get("abstract", "")
            if abstract:
                # 简单去除HTML标签
                import re
                abstract = re.sub(r'<[^>]+>', '', abstract).strip()

            if not abstract:
                continue  # 跳过无摘要的论文

            # 提取作者
            authors = []
            for author in (item.get("author", []) or [])[:10]:
                name = f"{author.get('given', '')} {author.get('family', '')}".strip()
                if name:
                    authors.append(name)

            # 提取DOI
            doi = item.get("DOI", "")

            # 提取发布日期
            pub_parts = item.get("published", {}).get("date-parts", [[]])
            if pub_parts and pub_parts[0]:
                parts = pub_parts[0]
                year = parts[0] if len(parts) > 0 else 2026
                month = parts[1] if len(parts) > 1 else 1
                day = parts[2] if len(parts) > 2 else 1
                try:
                    pub_date = datetime(year, month, day)
                except ValueError:
                    pub_date = datetime.now()
            else:
                pub_date = datetime.now()

            # 提取期刊名
            journal = item.get("container-title", [""])[0] if item.get("container-title") else ""

            # 提取链接
            url = item.get("URL", f"https://doi.org/{doi}")

            # 提取PDF链接
            pdf_url = ""
            for link in (item.get("link", []) or []):
                if link.get("content-type") == "application/pdf":
                    pdf_url = link.get("URL", "")
                    break

            # 提取学科分类
            subjects = item.get("subject", []) or []

            paper = Paper(
                title=title,
                authors=authors,
                abstract=abstract[:1000],  # 限制摘要长度
                arxiv_id=f"cr-{doi}",  # 用DOI作为ID，加前缀区分来源
                url=url,
                pdf_url=pdf_url,
                categories=[journal] + subjects[:3] if journal else subjects[:4],
                published=pub_date,
                updated=pub_date,
                keywords_matched=self._match_keywords(title, abstract)
            )

            if paper.keywords_matched:  # 只保留匹配关键词的论文
                papers.append(paper)

        return papers

    def _match_keywords(self, title: str, abstract: str) -> List[str]:
        """检查论文是否匹配关键词"""
        text = (title + " " + abstract).lower()
        return [kw for kw in self.keywords if kw.lower() in text]

    @staticmethod
    def _group_keywords(keywords: List[str], group_size: int = 3) -> List[List[str]]:
        """将关键词分组"""
        return [keywords[i:i + group_size] for i in range(0, len(keywords), group_size)]
