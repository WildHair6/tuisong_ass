"""
公众号文章模板生成器 - 将分析结果转换为可直接发布的HTML文章
"""

import os
import re
import logging
import markdown
from datetime import datetime
from typing import List
from jinja2 import Environment, FileSystemLoader

from .fetcher import Paper

logger = logging.getLogger(__name__)


class ArticleGenerator:
    """生成微信公众号格式的HTML文章"""

    def __init__(self, config: dict):
        article_config = config.get("article", {})
        self.account_name = article_config.get("account_name", "AI科研前沿")
        self.author = article_config.get("author", "AI助手")
        self.output_dir = article_config.get("output_dir", "./output")
        self.save_html = article_config.get("save_html", True)

        # 初始化 Jinja2 模板引擎
        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
        self.env = Environment(loader=FileSystemLoader(template_dir))

    def generate(
        self,
        papers: List[Paper],
        trends: str,
        title: str,
        total_fetched: int,
        date_str: str = None
    ) -> str:
        """
        生成公众号文章HTML

        Args:
            papers: 筛选后的论文列表
            trends: 研究热点分析文本（Markdown）
            title: 文章标题
            total_fetched: 今日总抓取论文数
            date_str: 日期字符串

        Returns:
            完整的HTML文章内容
        """
        if date_str is None:
            date_str = datetime.now().strftime("%Y年%m月%d日")

        # 将Markdown热点分析转为HTML
        trends_html = self._markdown_to_html(trends) if trends else ""

        # 计算平均分
        avg_score = "%.1f" % (sum(p.score for p in papers) / len(papers)) if papers else "0.0"

        # 渲染模板
        template = self.env.get_template("wechat_article.html")
        html = template.render(
            title=title,
            account_name=self.account_name,
            author=self.author,
            date_str=date_str,
            papers=papers,
            trends=trends,
            trends_html=trends_html,
            total_fetched=total_fetched,
            paper_count=len(papers),
            avg_score=avg_score
        )

        # 保存文件
        if self.save_html:
            filepath = self._save_html(html, date_str)
            logger.info(f"公众号文章已保存: {filepath}")

        return html

    def generate_plain_text(self, papers: List[Paper], trends: str, title: str, date_str: str = None) -> str:
        """
        生成纯文本版本（用于邮件正文/钉钉推送）

        Returns:
            格式化的纯文本内容
        """
        if date_str is None:
            date_str = datetime.now().strftime("%Y年%m月%d日")

        lines = []
        lines.append(f"{'=' * 50}")
        lines.append(f"📰 {title}")
        lines.append(f"📅 {date_str} · {self.account_name}")
        lines.append(f"{'=' * 50}")
        lines.append("")

        # 研究热点
        if trends:
            lines.append("🔥 今日研究热点")
            lines.append("-" * 30)
            lines.append(trends)
            lines.append("")

        # 论文列表
        lines.append("📄 精选论文详解")
        lines.append("-" * 30)

        for idx, paper in enumerate(papers, 1):
            lines.append(f"\n【TOP {idx}】评分: {paper.score:.1f}/10")
            lines.append(f"📌 {paper.title}")
            lines.append(f"👤 {', '.join(paper.authors[:3])}")
            lines.append(f"📝 {paper.summary_zh}")
            lines.append(f"💡 创新点: {paper.innovation}")
            lines.append(f"🔗 相关性: {paper.relevance}")
            lines.append(f"🛠️ 应用价值: {paper.practical_value}")
            lines.append(f"📎 链接: {paper.url}")
            if paper.keywords_matched:
                lines.append(f"🏷️ 关键词: {', '.join(paper.keywords_matched)}")
            lines.append("")

        lines.append(f"{'=' * 50}")
        lines.append(f"🤖 本文由AI自动生成 · 数据来源: arXiv")
        lines.append(f"论文评分仅供参考，建议阅读原文进行深入了解")

        return "\n".join(lines)

    def _markdown_to_html(self, md_text: str) -> str:
        """将Markdown转换为HTML（微信兼容）"""
        try:
            html = markdown.markdown(md_text, extensions=["extra", "nl2br"])
            # 微信公众号编辑器会去掉class，这里用inline style
            html = html.replace("<strong>", '<strong style="color: #e17055; font-weight: 600;">')
            html = html.replace("<h3>", '<h3 style="margin: 15px 0 8px; font-size: 15px; color: #2d3436; font-weight: 700;">')
            html = html.replace("<li>", '<li style="margin: 5px 0; color: #555;">')
            html = html.replace("<p>", '<p style="font-size: 14px; color: #555; line-height: 2;">')
            return html
        except Exception:
            # 降级：直接返回纯文本
            return f"<p>{md_text}</p>"

    def _save_html(self, html: str, date_str: str) -> str:
        """保存HTML文件"""
        os.makedirs(self.output_dir, exist_ok=True)
        # 文件名使用日期
        safe_date = re.sub(r'[年月]', '-', date_str).replace('日', '')
        filename = f"paper_daily_{safe_date}.html"
        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

        return filepath
