"""
PDF下载模块 - 下载论文PDF到本地
"""

import os
import re
import logging
import requests
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from .fetcher import Paper

logger = logging.getLogger(__name__)


class PDFDownloader:
    """论文PDF批量下载器"""

    def __init__(self, config: dict):
        self.output_dir = config.get("article", {}).get("output_dir", "./output")
        self.pdf_dir = os.path.join(self.output_dir, "pdfs")
        self.max_workers = 3  # 并发下载数
        self.timeout = 60     # 下载超时(秒)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; PaperPushBot/1.0)"
        })

    def download_papers(self, papers: List[Paper]) -> dict:
        """
        批量下载论文PDF
        
        Args:
            papers: 论文列表
            
        Returns:
            {arxiv_id: local_path} 成功下载的映射
        """
        os.makedirs(self.pdf_dir, exist_ok=True)
        
        results = {}
        download_tasks = []
        
        for paper in papers:
            if not paper.pdf_url:
                logger.debug(f"跳过无PDF链接: {paper.arxiv_id}")
                continue
            download_tasks.append(paper)

        if not download_tasks:
            logger.info("没有可下载的PDF")
            return results

        logger.info(f"开始下载 {len(download_tasks)} 篇PDF...")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._download_single, paper): paper 
                for paper in download_tasks
            }
            
            for future in as_completed(futures):
                paper = futures[future]
                try:
                    path = future.result()
                    if path:
                        results[paper.arxiv_id] = path
                        logger.info(f"✅ 已下载: {paper.arxiv_id}")
                except Exception as e:
                    logger.warning(f"❌ 下载失败 [{paper.arxiv_id}]: {e}")

        logger.info(f"PDF下载完成: {len(results)}/{len(download_tasks)} 成功")
        return results

    def _download_single(self, paper: Paper) -> Optional[str]:
        """下载单篇PDF"""
        # 生成安全的文件名
        safe_title = re.sub(r'[^\w\s-]', '', paper.title[:60]).strip()
        safe_title = re.sub(r'\s+', '_', safe_title)
        filename = f"{paper.arxiv_id.replace('/', '_')}_{safe_title}.pdf"
        filepath = os.path.join(self.pdf_dir, filename)

        # 如果已存在则跳过
        if os.path.exists(filepath) and os.path.getsize(filepath) > 1000:
            logger.debug(f"PDF已存在，跳过: {filename}")
            return filepath

        try:
            response = self.session.get(
                paper.pdf_url, 
                timeout=self.timeout,
                stream=True
            )
            response.raise_for_status()

            # 验证是PDF
            content_type = response.headers.get("Content-Type", "")
            if "pdf" not in content_type and "octet-stream" not in content_type:
                logger.warning(f"非PDF响应 [{paper.arxiv_id}]: {content_type}")
                return None

            # 流式写入
            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # 验证文件大小
            file_size = os.path.getsize(filepath)
            if file_size < 1000:  # 小于1KB可能是错误页面
                os.remove(filepath)
                return None

            return filepath

        except requests.exceptions.Timeout:
            logger.warning(f"下载超时 [{paper.arxiv_id}]")
            return None
        except Exception as e:
            # 清理不完整的文件
            if os.path.exists(filepath):
                os.remove(filepath)
            raise

    def get_total_size(self) -> str:
        """获取已下载PDF的总大小"""
        if not os.path.exists(self.pdf_dir):
            return "0 MB"
        
        total = sum(
            os.path.getsize(os.path.join(self.pdf_dir, f))
            for f in os.listdir(self.pdf_dir)
            if f.endswith(".pdf")
        )
        
        if total < 1024 * 1024:
            return f"{total / 1024:.1f} KB"
        return f"{total / (1024 * 1024):.1f} MB"
