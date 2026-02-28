"""
PubMed 数据源 - 医学/生物/化学领域文献搜索

通过 ai4scholar.net 代理调用 PubMed API，增强医学领域文献覆盖。
当 Semantic Scholar 搜索结果不足时自动补充 PubMed 数据。

API: https://ai4scholar.net/pubmed/v1/paper/search
认证: Bearer Token (与 Semantic Scholar 代理共用)
"""

import requests
import logging
import time
from datetime import datetime
from typing import List, Optional, Dict, Any

from .fetcher import Paper

logger = logging.getLogger(__name__)

# 医学/生物/化学相关领域关键词（用于自动判断是否需要 PubMed 补充）
MEDICAL_KEYWORDS = {
    # 英文
    "cancer", "tumor", "tumour", "immunotherapy", "chemotherapy", "oncology",
    "clinical", "patient", "disease", "therapy", "treatment", "drug", "pharmaceutical",
    "medical", "medicine", "surgery", "surgical", "diagnosis", "diagnostic",
    "biomarker", "genomic", "genetic", "gene", "protein", "molecular",
    "cell", "cellular", "tissue", "organ", "blood", "brain", "heart", "liver", "lung",
    "neuroscience", "neurology", "cardiology", "dermatology", "radiology",
    "pathology", "pharmacology", "toxicology", "epidemiology",
    "infection", "virus", "bacteria", "antibiotic", "vaccine",
    "diabetes", "alzheimer", "parkinson", "stroke", "hypertension",
    "osteoporosis", "arthritis", "asthma", "allergy",
    "mental health", "depression", "anxiety", "psychiatric",
    "traditional chinese medicine", "tcm", "herbal", "acupuncture",
    "metabolism", "immune", "inflammation", "microbiome",
    "pubmed", "medline", "clinical trial",
    # 中文
    "癌症", "肿瘤", "免疫", "治疗", "药物", "临床", "患者", "疾病",
    "手术", "诊断", "基因", "蛋白", "细胞", "组织", "器官",
    "神经", "心脏", "肝", "肺", "脑", "血液",
    "感染", "病毒", "细菌", "抗生素", "疫苗",
    "糖尿病", "高血压", "骨质疏松", "关节炎",
    "中医", "中药", "针灸", "草药", "方剂",
    "代谢", "炎症", "微生物",
    "医学", "药学", "病理", "流行病",
}


def is_medical_query(query: str) -> bool:
    """
    判断查询是否属于医学/生物/化学领域

    Args:
        query: 搜索查询词

    Returns:
        True 如果查询可能属于医学领域
    """
    query_lower = query.lower()
    matched = sum(1 for kw in MEDICAL_KEYWORDS if kw in query_lower)
    return matched >= 1


class PubMedFetcher:
    """
    PubMed 文献搜索（通过 ai4scholar.net 代理）

    用于补充 Semantic Scholar 在医学领域的不足，
    特别是中医药、临床研究、生物医学等领域。
    """

    def __init__(self, config: dict):
        self.config = config
        s2_config = config.get("semantic_scholar", {})

        # 复用 Semantic Scholar 代理的 API key 和 base_url
        self.api_key = s2_config.get("api_key", "")
        base_url = s2_config.get("base_url", "https://ai4scholar.net").rstrip("/")
        self.search_url = f"{base_url}/pubmed/v1/paper/search"

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "PaperPush/2.0 (research-bot)",
        })

        # 速率控制
        self._last_request_time = 0
        self._min_interval = 1.0

    def _rate_limit(self):
        """遵守 API 速率限制"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def search(self, query: str, limit: int = 20, max_retries: int = 3) -> List[Paper]:
        """
        搜索 PubMed 文献

        Args:
            query: 搜索查询（英文效果最好）
            limit: 返回数量上限
            max_retries: 最大重试次数

        Returns:
            Paper 对象列表
        """
        self._rate_limit()

        data = {
            "query": query,
            "limit": min(limit, 50),  # PubMed API 单次最大50
        }

        for attempt in range(max_retries):
            try:
                response = self.session.post(
                    self.search_url,
                    json=data,
                    timeout=30,
                )

                if response.status_code == 200:
                    result = response.json()
                    total = result.get("total", 0)
                    papers_data = result.get("papers", [])

                    # 记录积分消耗
                    credits_remaining = response.headers.get("X-Credits-Remaining", "?")
                    credits_charged = response.headers.get("X-Credits-Charged", "?")
                    logger.info(f"PubMed 搜索 '{query[:50]}': {len(papers_data)}/{total} 篇 "
                                f"(积分消耗: {credits_charged}, 剩余: {credits_remaining})")

                    return self._parse_results(papers_data)

                elif response.status_code == 402:
                    logger.warning("PubMed API 积分不足 (402)，跳过 PubMed 补充")
                    return []

                elif response.status_code == 429:
                    wait = 10 * (attempt + 1)
                    logger.warning(f"PubMed API 限流 (429)，等待 {wait}s...")
                    time.sleep(wait)
                    continue

                elif response.status_code >= 500:
                    wait = 5 * (attempt + 1)
                    logger.warning(f"PubMed API 服务器错误 ({response.status_code})，等待 {wait}s...")
                    time.sleep(wait)
                    continue

                else:
                    logger.error(f"PubMed API 请求失败: {response.status_code} - {response.text[:200]}")
                    return []

            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    logger.warning(f"PubMed 请求超时，重试 ({attempt+1}/{max_retries})")
                    time.sleep(3)
                else:
                    logger.error("PubMed 请求超时，已达最大重试次数")
                    return []

            except requests.exceptions.ConnectionError as e:
                if attempt < max_retries - 1:
                    logger.warning(f"PubMed 连接错误，重试: {e}")
                    time.sleep(3)
                else:
                    logger.error(f"PubMed 连接失败: {e}")
                    return []

            except Exception as e:
                logger.error(f"PubMed 搜索异常: {e}")
                return []

        return []

    def _parse_results(self, papers_data: list) -> List[Paper]:
        """
        解析 PubMed API 返回的论文数据，转换为 Paper 对象

        PubMed 返回的字段可能包括:
        - title, authors, abstract, pubmed_id, doi, url
        - publication_date, journal, mesh_terms
        """
        papers = []
        for item in papers_data:
            try:
                title = item.get("title", "").strip()
                if not title:
                    continue

                # 作者列表
                authors_raw = item.get("authors", [])
                if isinstance(authors_raw, list):
                    parsed_authors = []
                    for a in authors_raw[:10]:
                        if isinstance(a, str):
                            parsed_authors.append(a)
                        elif isinstance(a, dict):
                            # PubMed 返回 {'lastName': 'X', 'foreName': 'Y', ...}
                            last = a.get("lastName", "") or a.get("last_name", "")
                            first = a.get("foreName", "") or a.get("first_name", "") or a.get("initials", "")
                            name = a.get("name", "")
                            if last and first:
                                parsed_authors.append(f"{first} {last}")
                            elif name:
                                parsed_authors.append(name)
                            elif last:
                                parsed_authors.append(last)
                            else:
                                parsed_authors.append(str(a))
                        else:
                            parsed_authors.append(str(a))
                    authors = parsed_authors
                elif isinstance(authors_raw, str):
                    authors = [a.strip() for a in authors_raw.split(",")[:10]]
                else:
                    authors = []

                # 摘要
                abstract = item.get("abstract", "").strip()
                if not abstract:
                    continue  # 跳过无摘要的论文

                # 唯一ID
                pubmed_id = str(item.get("pubmed_id", "") or item.get("pmid", "") or "")
                doi = item.get("doi", "") or ""
                paper_id = doi or pubmed_id

                # URL
                url = item.get("url", "")
                if not url:
                    if pubmed_id:
                        url = f"https://pubmed.ncbi.nlm.nih.gov/{pubmed_id}/"
                    elif doi:
                        url = f"https://doi.org/{doi}"

                # 发表日期
                pub_date_str = item.get("publication_date", "") or item.get("pub_date", "")
                pub_date = datetime.now()
                if isinstance(pub_date_str, str) and pub_date_str:
                    try:
                        # 尝试常见日期格式
                        for fmt in ["%Y-%m-%d", "%Y-%m", "%Y"]:
                            try:
                                pub_date = datetime.strptime(pub_date_str[:10], fmt)
                                break
                            except ValueError:
                                continue
                        else:
                            import re
                            year_match = re.search(r"(19|20)\d{2}", pub_date_str)
                            if year_match:
                                pub_date = datetime(int(year_match.group()), 1, 1)
                    except Exception:
                        pass
                elif isinstance(pub_date_str, (int, float)):
                    pub_date = datetime(int(pub_date_str), 1, 1)

                # 期刊
                journal_raw = item.get("journal", "") or item.get("venue", "") or ""
                if isinstance(journal_raw, dict):
                    # PubMed 返回 {'title': 'xxx', 'isoAbbreviation': 'xxx', ...}
                    journal = journal_raw.get("title", "") or journal_raw.get("isoAbbreviation", "")
                elif isinstance(journal_raw, str):
                    journal = journal_raw
                else:
                    journal = str(journal_raw) if journal_raw else ""

                # MeSH 关键词
                mesh_terms = item.get("mesh_terms", []) or item.get("keywords", []) or []
                if isinstance(mesh_terms, str):
                    mesh_terms = [t.strip() for t in mesh_terms.split(",")]

                # 年份
                year = item.get("year")
                if isinstance(year, str):
                    import re
                    ym = re.search(r"(19|20)\d{2}", year)
                    year = int(ym.group()) if ym else None
                if not year and pub_date:
                    year = pub_date.year
                # PubMed venue dict 中也可能有 pubDate
                if not year and isinstance(journal_raw, dict):
                    pd = journal_raw.get("pubDate", "")
                    if isinstance(pd, (int, float)):
                        year = int(pd)
                    elif isinstance(pd, str):
                        import re
                        ym = re.search(r"(19|20)\d{2}", pd)
                        if ym:
                            year = int(ym.group())

                # 引用数（PubMed 可能不提供）
                citation_count = item.get("citation_count", 0) or item.get("citationCount", 0) or 0

                paper = Paper(
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    arxiv_id=f"pubmed-{paper_id}",
                    url=url,
                    pdf_url="",  # PubMed 一般不提供 PDF
                    categories=mesh_terms[:5] if mesh_terms else ["Medicine"],
                    published=pub_date,
                    updated=pub_date,
                    keywords_matched=["PubMed"],
                )

                # 附加元数据
                paper._citation_count = citation_count
                paper._venue = journal
                paper._year = year
                paper._doi = doi
                paper._pubmed_id = pubmed_id
                paper._s2_id = ""
                paper._source = "pubmed"

                papers.append(paper)

            except Exception as e:
                logger.warning(f"PubMed 论文解析失败: {e}")
                continue

        return papers


def test_pubmed():
    """快速测试 PubMed API 是否可用"""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from .utils import load_config

    config = load_config()
    fetcher = PubMedFetcher(config)

    print("测试1: 搜索 cancer immunotherapy")
    papers = fetcher.search("cancer immunotherapy", limit=5)
    print(f"  找到 {len(papers)} 篇")
    for p in papers[:3]:
        print(f"  - {p.title}")
        print(f"    {', '.join(p.authors[:3])}")

    print("\n测试2: 搜索中医药骨质疏松")
    papers = fetcher.search("traditional Chinese medicine osteoporosis", limit=5)
    print(f"  找到 {len(papers)} 篇")
    for p in papers[:3]:
        print(f"  - {p.title}")

    print("\n测试3: 判断医学查询")
    test_queries = [
        "cancer immunotherapy", "robot manipulation", "中医药治疗骨质疏松",
        "spacecraft trajectory", "tumor microenvironment", "deep learning",
    ]
    for q in test_queries:
        print(f"  '{q}' → {'医学' if is_medical_query(q) else '非医学'}")


if __name__ == "__main__":
    import os
    test_pubmed()
