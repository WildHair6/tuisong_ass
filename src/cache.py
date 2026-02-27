"""
论文缓存模块 - 避免重复推送已推过的论文
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import List, Set

from .fetcher import Paper

logger = logging.getLogger(__name__)


class PaperCache:
    """
    基于JSON文件的论文缓存
    记录已推送过的论文ID，避免重复推送
    """

    def __init__(self, cache_dir: str = "./cache", retention_days: int = 30):
        """
        Args:
            cache_dir: 缓存文件目录
            retention_days: 缓存保留天数（超过后自动清理）
        """
        self.cache_dir = cache_dir
        self.cache_file = os.path.join(cache_dir, "pushed_papers.json")
        self.retention_days = retention_days
        os.makedirs(cache_dir, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        """加载缓存文件"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"缓存文件损坏，重新创建: {e}")
        return {"papers": {}, "stats": {"total_pushed": 0}}

    def _save(self):
        """保存缓存文件"""
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def filter_new(self, papers: List[Paper]) -> List[Paper]:
        """
        过滤出未推送过的论文
        
        Args:
            papers: 待过滤的论文列表
            
        Returns:
            仅包含新论文的列表
        """
        pushed_ids = set(self._data.get("papers", {}).keys())
        new_papers = [p for p in papers if p.arxiv_id not in pushed_ids]
        
        filtered_count = len(papers) - len(new_papers)
        if filtered_count > 0:
            logger.info(f"缓存去重: 过滤掉 {filtered_count} 篇已推送论文")
        
        return new_papers

    def mark_pushed(self, papers: List[Paper]):
        """
        标记论文为已推送
        
        Args:
            papers: 已推送的论文列表
        """
        now = datetime.now().isoformat()
        for paper in papers:
            self._data["papers"][paper.arxiv_id] = {
                "title": paper.title,
                "score": paper.score,
                "pushed_at": now
            }
        
        self._data["stats"]["total_pushed"] = len(self._data["papers"])
        self._data["stats"]["last_push"] = now
        self._save()
        logger.info(f"缓存更新: 新增 {len(papers)} 篇，总计 {len(self._data['papers'])} 篇")

    def cleanup(self):
        """清理过期缓存"""
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        cutoff_str = cutoff.isoformat()
        
        old_count = len(self._data.get("papers", {}))
        self._data["papers"] = {
            k: v for k, v in self._data.get("papers", {}).items()
            if v.get("pushed_at", "") > cutoff_str
        }
        new_count = len(self._data["papers"])
        
        if old_count > new_count:
            removed = old_count - new_count
            logger.info(f"缓存清理: 移除 {removed} 条过期记录")
            self._save()

    def get_stats(self) -> dict:
        """获取缓存统计信息"""
        return {
            "total_cached": len(self._data.get("papers", {})),
            "total_pushed": self._data.get("stats", {}).get("total_pushed", 0),
            "last_push": self._data.get("stats", {}).get("last_push", "从未推送"),
        }
