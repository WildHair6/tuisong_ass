"""
Semantic Scholar 数据源 - 主数据源（替代 arXiv）

功能:
  1. 按频道关键词搜索最新论文
  2. 支持高级搜索（领域过滤、引用数排序等）
  3. 文献调研：根据用户查询搜索相关文献
  4. 文献详情查询、引用关系追踪

API文档: https://api.semanticscholar.org/api-docs/
免费配额: 100次/5分钟（有API Key可提升至更高）
"""

import requests
import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

from .fetcher import Paper

logger = logging.getLogger(__name__)

# 默认官方 API（可通过 config 覆盖为代理）
DEFAULT_S2_API = "https://api.semanticscholar.org/graph/v1"
PAPER_FIELDS = "title,authors,abstract,externalIds,url,publicationDate,citationCount,influentialCitationCount,fieldsOfStudy,openAccessPdf,venue,year,referenceCount"


class SemanticScholarFetcher:
    """
    Semantic Scholar 主数据源

    用于:
    - 每日频道推送（航天 / 机器人AI）
    - AI助理文献调研
    - 文献综述数据采集

    支持:
    - 官方 API (api.semanticscholar.org)
    - 中转代理 (如 ai4scholar.net)，Bearer Token 认证
    """

    def __init__(self, config: dict):
        self.config = config
        s2_config = config.get("semantic_scholar", {})

        self.api_key = s2_config.get("api_key", "")
        self.auth_type = s2_config.get("auth_type", "apikey")  # "bearer" or "apikey"
        self.max_per_request = min(s2_config.get("max_results_per_request", 100), 100)
        self.max_total = s2_config.get("max_results_total", 1000)

        # 构造 API 基地址
        custom_base = s2_config.get("base_url", "").rstrip("/")
        self._use_proxy = bool(custom_base)
        if custom_base:
            self.api_base = f"{custom_base}/graph/v1"
            logger.info(f"使用 Semantic Scholar 代理: {custom_base}")
        else:
            self.api_base = DEFAULT_S2_API

        # 是否已自动降级到官方API
        self._fallback_active = False

        self.session = requests.Session()
        self._setup_session_headers()

        # 速率控制（代理一般不限速，官方无key 3.5s 间隔）
        self._last_request_time = 0
        self._min_interval = 0.5 if (self.api_key and custom_base) else (1.0 if self.api_key else 3.5)

    def _setup_session_headers(self):
        """设置请求头（根据当前api_base状态）"""
        self.session.headers["User-Agent"] = "PaperPush/2.0 (research-bot)"
        if self._fallback_active:
            # 官方 API 不需要认证头（免费配额）
            self.session.headers.pop("Authorization", None)
            self.session.headers.pop("x-api-key", None)
        elif self.api_key:
            if self.auth_type == "bearer":
                self.session.headers["Authorization"] = f"Bearer {self.api_key}"
            else:
                self.session.headers["x-api-key"] = self.api_key

    def _activate_fallback(self):
        """代理不可用时（402等），自动降级到官方Semantic Scholar API"""
        if self._fallback_active or not self._use_proxy:
            return  # 已经降级了或没有用代理
        logger.warning("⚠ 代理 API 额度不足(402)，自动降级到官方 Semantic Scholar API（速率较低）")
        self._fallback_active = True
        self.api_base = DEFAULT_S2_API
        self._min_interval = 3.5  # 官方免费配额速率限制
        # 重建 session
        self.session.close()
        self.session = requests.Session()
        self._setup_session_headers()

    def _rate_limit(self):
        """遵守 API 速率限制"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def _get(self, endpoint: str, params: dict = None, timeout: int = 30, max_retries: int = 3) -> dict:
        """带速率限制和自动重试的 GET 请求

        Args:
            endpoint: API 路径（如 /paper/search），会自动拼接 api_base
                      如果是完整 URL (http开头) 则直接使用
            max_retries: 最大重试次数（针对网络/SSL/5xx 错误）

        支持:
            - 429 限流 → 指数等待重试
            - 5xx 服务端错误 → 等待重试
            - 402 代理额度不足 → 自动降级到官方 API 并重试
            - SSL/连接错误 → 重建 session 并重试
        """
        self._rate_limit()
        url = endpoint if endpoint.startswith("http") else f"{self.api_base}{endpoint}"

        for attempt in range(max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=timeout)

                # 代理额度不足 → 自动降级到官方 API
                if response.status_code == 402 and self._use_proxy and not self._fallback_active:
                    self._activate_fallback()
                    # 用新的 api_base 重新构造 URL 并重试
                    url = endpoint if endpoint.startswith("http") else f"{self.api_base}{endpoint}"
                    self._rate_limit()
                    response = self.session.get(url, params=params, timeout=timeout)

                if response.status_code == 429:
                    wait = 10 * (attempt + 1)
                    logger.warning(f"API 限流，等待 {wait}s 后重试 ({attempt+1}/{max_retries})...")
                    time.sleep(wait)
                    continue
                if response.status_code >= 500:
                    wait = 5 * (attempt + 1)
                    logger.warning(f"服务端错误 {response.status_code}，等待 {wait}s 后重试...")
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                return response.json()
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < max_retries:
                    wait = 5 * (attempt + 1)
                    logger.warning(f"连接错误，等待 {wait}s 后重试 ({attempt+1}/{max_retries}): {type(e).__name__}")
                    time.sleep(wait)
                    # 重建 session 解决 SSL 连接池问题
                    self.session.close()
                    self.session = requests.Session()
                    self._setup_session_headers()
                else:
                    logger.error(f"Semantic Scholar API 请求失败 (重试 {max_retries} 次后): {e}")
                    raise
            except requests.exceptions.HTTPError as e:
                # 402 在降级后仍然失败（官方API也402）→ 不重试
                if hasattr(e, 'response') and e.response is not None and e.response.status_code == 402:
                    logger.error(f"Semantic Scholar API 请求失败 (402): {e}")
                    raise
                logger.error(f"Semantic Scholar API 请求失败: {e}")
                raise
            except requests.exceptions.RequestException as e:
                logger.error(f"Semantic Scholar API 请求失败: {e}")
                raise

        raise requests.exceptions.RequestException(f"请求失败，已重试 {max_retries} 次")

    # ================================================================
    # 每日推送：按频道关键词获取最新论文
    # ================================================================

    def fetch_channel_papers(self, channel_config: dict, days: int = 7) -> List[Paper]:
        """
        为指定频道获取最新论文

        Args:
            channel_config: 频道配置（含 keywords, fields_of_study, max_papers 等）
            days: 回溯天数（S2索引有延迟，建议 >= 7）

        Returns:
            去重后的论文列表
        """
        keywords = channel_config.get("keywords", [])
        fields_of_study = channel_config.get("fields_of_study", [])
        max_papers = channel_config.get("max_papers", 10)

        all_papers = []
        # 限制关键词数以避免超频
        search_keywords = keywords[:8]

        # 每个关键词只取 100 篇（1 次 API 调用），而不是 1000 篇（10次调用）
        # 8个关键词 × 1次 = 8 次调用/频道，合理使用额度
        per_keyword_limit = 100

        for keyword in search_keywords:
            try:
                papers = self._search_papers(
                    query=keyword,
                    days=days,
                    fields_of_study=fields_of_study,
                    limit=per_keyword_limit
                )
                all_papers.extend(papers)
                logger.info(f"  S2 [{keyword}]: {len(papers)} 篇")
            except Exception as e:
                logger.warning(f"  S2 [{keyword}] 搜索失败: {e}")

        # 去重
        unique = self._deduplicate(all_papers)
        logger.info(f"  S2 频道共获取 {len(unique)} 篇去重论文")
        return unique

    def fetch_recent_papers(self, days: int = 7) -> List[Paper]:
        """
        兼容旧接口：使用全局 research.keywords 搜索
        """
        keywords = self.config.get("research", {}).get("keywords", [])
        all_papers = []
        for keyword in keywords[:5]:
            try:
                papers = self._search_papers(query=keyword, days=days, limit=100)
                all_papers.extend(papers)
                logger.info(f"S2 [{keyword}]: {len(papers)} 篇")
                time.sleep(1)
            except Exception as e:
                logger.warning(f"S2 [{keyword}] 搜索失败: {e}")
        return self._deduplicate(all_papers)

    # ================================================================
    # AI 助理：文献调研
    # ================================================================

    def research_query(self, query: str, limit: int = 20,
                       year_from: int = None, year_to: int = None,
                       fields_of_study: List[str] = None,
                       sort_by: str = "relevance") -> List[Paper]:
        """
        AI助理的文献调研接口 - 根据用户自然语言查询搜索文献

        Args:
            query: 搜索查询（支持自然语言）
            limit: 返回数量上限
            year_from: 起始年份
            year_to: 截止年份
            fields_of_study: 学科领域过滤
            sort_by: 排序方式 - "relevance"(相关性) 或 "citationCount"(引用数)

        Returns:
            论文列表
        """
        logger.info(f"AI助理文献调研: '{query}' (limit={limit})")

        all_papers = []
        offset = 0
        page_size = self.max_per_request

        while offset < limit:
            current_limit = min(page_size, limit - offset)
            params = {
                "query": query,
                "limit": current_limit,
                "offset": offset,
                "fields": PAPER_FIELDS,
            }

            # 年份过滤
            if year_from and year_to:
                params["year"] = f"{year_from}-{year_to}"
            elif year_from:
                params["year"] = f"{year_from}-"
            elif year_to:
                params["year"] = f"-{year_to}"

            # 学科过滤
            if fields_of_study:
                params["fieldsOfStudy"] = ",".join(fields_of_study)

            # 排序（S2 API 支持按引用数排序）
            if sort_by == "citationCount":
                params["sort"] = "citationCount:desc"

            try:
                data = self._get("/paper/search", params=params)
                batch = self._parse_results(data, source_tag="research")
                all_papers.extend(batch)

                if len(batch) < current_limit:
                    break
                offset += current_limit
            except Exception as e:
                logger.error(f"文献调研分页失败 (offset={offset}): {e}")
                break

        logger.info(f"  调研结果: {len(all_papers)} 篇")
        return all_papers

    def get_paper_details(self, paper_id: str) -> Optional[Dict[str, Any]]:
        """
        获取论文详细信息（含引用、参考文献等）

        Args:
            paper_id: S2 Paper ID, DOI, 或 ArXiv ID

        Returns:
            论文详情字典
        """
        url = f"/paper/{paper_id}"
        params = {
            "fields": f"{PAPER_FIELDS},references.title,references.authors,references.year,references.citationCount,citations.title,citations.authors,citations.year,citations.citationCount"
        }
        try:
            return self._get(url, params=params)
        except Exception:
            return None

    def get_paper_citations(self, paper_id: str, limit: int = 50) -> List[Dict]:
        """获取论文的引用列表"""
        url = f"/paper/{paper_id}/citations"
        params = {
            "fields": "title,authors,year,citationCount,url",
            "limit": limit
        }
        try:
            data = self._get(url, params=params)
            return data.get("data", [])
        except Exception:
            return []

    def get_paper_references(self, paper_id: str, limit: int = 50) -> List[Dict]:
        """获取论文的参考文献列表"""
        url = f"/paper/{paper_id}/references"
        params = {
            "fields": "title,authors,year,citationCount,url,venue",
            "limit": limit
        }
        try:
            data = self._get(url, params=params)
            return data.get("data", [])
        except Exception:
            return []

    def get_author_papers(self, author_id: str, limit: int = 100) -> List[Dict]:
        """根据作者 ID 获取其论文列表（支持分页，最多500篇）"""
        all_papers = []
        offset = 0
        page_size = min(limit, 100)

        while offset < limit:
            current_limit = min(page_size, limit - offset)
            url = f"/author/{author_id}/papers"
            params = {
                "fields": "title,year,citationCount,url,venue,abstract",
                "limit": current_limit,
                "offset": offset,
            }
            try:
                data = self._get(url, params=params)
                batch = data.get("data", [])
                all_papers.extend(batch)
                if len(batch) < current_limit:
                    break
                offset += current_limit
            except Exception:
                break

        return all_papers

    def search_authors(self, name: str) -> List[Dict]:
        """搜索作者"""
        url = "/author/search"
        params = {
            "query": name,
            "fields": "name,affiliations,paperCount,citationCount,hIndex",
            "limit": 5
        }
        try:
            data = self._get(url, params=params)
            return data.get("data", [])
        except Exception:
            return []

    # ================================================================
    # 内部方法
    # ================================================================

    def _search_papers(self, query: str, days: int = 7,
                       fields_of_study: List[str] = None,
                       limit: int = 1000) -> List[Paper]:
        """按关键词搜索最近的论文（自动分页，最多获取 limit 篇）"""
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        date_to = datetime.now().strftime("%Y-%m-%d")

        all_papers = []
        offset = 0
        page_size = self.max_per_request  # 每页最多 100

        while offset < limit:
            current_limit = min(page_size, limit - offset)
            params = {
                "query": query,
                "limit": current_limit,
                "offset": offset,
                "fields": PAPER_FIELDS,
                "publicationDateOrYear": f"{date_from}:{date_to}",
            }
            if fields_of_study:
                params["fieldsOfStudy"] = ",".join(fields_of_study)

            try:
                data = self._get("/paper/search", params=params)
                batch = self._parse_results(data, source_tag=query)
                all_papers.extend(batch)

                # 没有更多结果了
                if len(batch) < current_limit:
                    break

                offset += current_limit
            except Exception as e:
                logger.warning(f"分页获取失败 (offset={offset}): {e}")
                break

        return all_papers

    def _parse_results(self, data: dict, source_tag: str = "") -> List[Paper]:
        """解析 S2 API 返回的论文数据"""
        papers = []
        for item in data.get("data", []):
            if not item.get("abstract"):
                continue  # 跳过无摘要的

            external_ids = item.get("externalIds") or {}
            arxiv_id = external_ids.get("ArXiv", "")
            doi = external_ids.get("DOI", "")
            s2_id = item.get("paperId", "")

            # 构建唯一 ID（优先用 DOI，其次 arXiv，最后 S2 ID）
            paper_id = doi or arxiv_id or s2_id
            unique_id = f"s2-{paper_id}"

            # PDF 链接
            pdf_info = item.get("openAccessPdf") or {}
            pdf_url = pdf_info.get("url", "")
            if not pdf_url and arxiv_id:
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

            # 论文链接
            paper_url = item.get("url", "")
            if not paper_url:
                if arxiv_id:
                    paper_url = f"https://arxiv.org/abs/{arxiv_id}"
                elif doi:
                    paper_url = f"https://doi.org/{doi}"
                else:
                    paper_url = f"https://www.semanticscholar.org/paper/{s2_id}"

            # 日期
            pub_date_str = item.get("publicationDate", "")
            try:
                pub_date = datetime.strptime(pub_date_str, "%Y-%m-%d") if pub_date_str else datetime.now()
            except ValueError:
                pub_date = datetime.now()

            # 作者
            authors = [a.get("name", "") for a in (item.get("authors") or [])[:10]]

            paper = Paper(
                title=item.get("title", "").strip(),
                authors=authors,
                abstract=item.get("abstract", "").strip(),
                arxiv_id=unique_id,
                url=paper_url,
                pdf_url=pdf_url,
                categories=item.get("fieldsOfStudy") or [],
                published=pub_date,
                updated=pub_date,
                keywords_matched=[source_tag] if source_tag else [],
            )

            # 附加元数据（挂在 paper 对象上，便于后续使用）
            paper._citation_count = item.get("citationCount", 0)
            paper._venue = item.get("venue", "")
            paper._year = item.get("year")
            paper._doi = doi
            paper._arxiv_id_raw = arxiv_id
            paper._s2_id = s2_id
            paper._reference_count = item.get("referenceCount", 0)

            papers.append(paper)

        return papers

    def _deduplicate(self, papers: List[Paper]) -> List[Paper]:
        """去重"""
        seen = set()
        unique = []
        for p in papers:
            key = p.title.lower().strip()[:80]  # 用标题前80字符去重
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique

    def enrich_paper_metadata(self, arxiv_id: str) -> Optional[dict]:
        """用 S2 补充论文的引用数等元数据（兼容旧接口）"""
        try:
            url = f"/paper/ArXiv:{arxiv_id}"
            params = {
                "fields": "citationCount,influentialCitationCount,referenceCount,fieldsOfStudy"
            }
            data = self._get(url, params=params)
            return data
        except Exception as e:
            logger.debug(f"元数据补充失败 [{arxiv_id}]: {e}")
            return None

