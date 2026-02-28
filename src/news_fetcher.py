"""
全球财经新闻模块 - 使用 DuckDuckGo 搜索 + AI 分析生成每日财经早报

功能:
  1. 通过 DuckDuckGo 搜索全球财经新闻
  2. 通过 yfinance 获取主要市场行情数据
  3. 使用 DeepSeek AI 汇总分析，生成结构化财经早报
"""

import logging
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    """新闻条目"""
    title: str
    body: str
    url: str
    source: str
    published: str
    category: str = ""  # economy, market, policy, etc.


@dataclass
class MarketData:
    """市场行情数据"""
    name: str
    symbol: str
    price: float = 0.0
    change: float = 0.0
    change_pct: float = 0.0
    volume: str = ""
    status: str = ""  # up, down, flat


@dataclass
class FinanceReport:
    """财经早报"""
    title: str
    date_str: str
    markets: List[MarketData]
    news_items: List[NewsItem]
    ai_summary: str  # AI 生成的综合分析
    market_analysis: str  # AI 生成的市场分析


class NewsFetcher:
    """全球财经新闻抓取器"""

    def __init__(self, config: dict):
        self.config = config
        self.channel_config = config.get("channels", {}).get("finance", {})
        self.search_queries = self.channel_config.get("search_queries", [
            "global economy news today",
            "stock market analysis today",
        ])
        self.markets_config = self.channel_config.get("markets", [])
        self.max_news = self.channel_config.get("max_news", 15)

        # AI 配置
        ai_config = config.get("ai", {})
        self.ai_api_key = ai_config.get("api_key", "")
        self.ai_base_url = ai_config.get("base_url", "https://api.deepseek.com")
        self.ai_model = ai_config.get("model", "deepseek-chat")

    def fetch_all(self) -> FinanceReport:
        """
        获取完整的财经早报数据

        Returns:
            FinanceReport 包含市场数据、新闻、AI 分析
        """
        date_str = datetime.now().strftime("%Y年%m月%d日")
        logger.info(f"📈 开始获取财经数据 - {date_str}")

        # 1. 获取市场行情
        markets = self._fetch_market_data()
        logger.info(f"  市场行情: {len(markets)} 个指数")

        # 2. 搜索新闻
        news_items = self._fetch_news()
        logger.info(f"  财经新闻: {len(news_items)} 条")

        # 3. AI 分析
        ai_summary, market_analysis = self._generate_ai_analysis(markets, news_items)

        # 4. 生成标题
        title = self._generate_title(markets, date_str)

        report = FinanceReport(
            title=title,
            date_str=date_str,
            markets=markets,
            news_items=news_items,
            ai_summary=ai_summary,
            market_analysis=market_analysis,
        )

        logger.info(f"✅ 财经早报准备完毕: {title}")
        return report

    def _fetch_market_data(self) -> List[MarketData]:
        """获取主要市场行情"""
        markets = []

        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance 未安装，跳过市场行情获取。pip install yfinance")
            return markets

        for market_cfg in self.markets_config:
            name = market_cfg.get("name", "")
            symbol = market_cfg.get("symbol", "")
            if not symbol:
                continue

            try:
                ticker = yf.Ticker(symbol)
                # 获取最近2天的数据
                hist = ticker.history(period="5d")
                if hist.empty or len(hist) < 2:
                    logger.warning(f"  {name} ({symbol}): 无数据")
                    continue

                latest = hist.iloc[-1]
                prev = hist.iloc[-2]

                price = float(latest["Close"])
                change = price - float(prev["Close"])
                change_pct = (change / float(prev["Close"])) * 100
                volume = f"{int(latest['Volume']):,}" if latest["Volume"] > 0 else ""

                status = "up" if change > 0 else "down" if change < 0 else "flat"

                markets.append(MarketData(
                    name=name,
                    symbol=symbol,
                    price=round(price, 2),
                    change=round(change, 2),
                    change_pct=round(change_pct, 2),
                    volume=volume,
                    status=status,
                ))
                logger.debug(f"  {name}: {price:.2f} ({change_pct:+.2f}%)")

            except Exception as e:
                logger.warning(f"  {name} ({symbol}) 行情获取失败: {e}")

        return markets

    def _fetch_news(self) -> List[NewsItem]:
        """搜索财经新闻"""
        all_news = []

        try:
            from duckduckgo_search import DDGS
        except ImportError:
            logger.warning("duckduckgo-search 未安装，跳过新闻搜索。pip install duckduckgo-search")
            return all_news

        ddgs = DDGS()

        for query in self.search_queries:
            try:
                results = ddgs.news(
                    keywords=query,
                    region="wt-wt",  # 全球
                    max_results=5,
                    timelimit="d",  # 最近一天
                )
                for r in results:
                    news = NewsItem(
                        title=r.get("title", ""),
                        body=r.get("body", ""),
                        url=r.get("url", ""),
                        source=r.get("source", ""),
                        published=r.get("date", ""),
                    )
                    all_news.append(news)
                logger.debug(f"  搜索 [{query}]: {len(results)} 条")
            except Exception as e:
                logger.warning(f"  搜索 [{query}] 失败: {e}")

        # 去重（按标题）
        seen_titles = set()
        unique_news = []
        for n in all_news:
            title_key = n.title.lower().strip()[:50]
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique_news.append(n)

        return unique_news[:self.max_news]

    def _generate_ai_analysis(self, markets: List[MarketData],
                               news_items: List[NewsItem]) -> tuple:
        """使用 DeepSeek 生成 AI 分析"""
        try:
            from openai import OpenAI
        except ImportError:
            return ("AI 分析不可用", "AI 分析不可用")

        client = OpenAI(
            api_key=self.ai_api_key,
            base_url=self.ai_base_url,
            timeout=120.0,
        )

        # 构建市场数据摘要
        market_text = "## 今日市场行情\n"
        for m in markets:
            emoji = "🔴" if m.status == "down" else "🟢" if m.status == "up" else "⚪"
            market_text += f"- {emoji} {m.name}: {m.price} ({m.change_pct:+.2f}%)\n"

        # 构建新闻摘要
        news_text = "## 今日财经新闻\n"
        for i, n in enumerate(news_items[:15], 1):
            news_text += f"{i}. [{n.source}] {n.title}\n   {n.body[:150]}\n\n"

        prompt = f"""你是一位资深的全球财经分析师。请根据以下市场数据和新闻，生成一份专业的财经早报分析。

{market_text}

{news_text}

请分两部分输出（使用JSON格式）:

{{
  "summary": "综合新闻摘要（400字以内）：提炼今日最重要的3-5条财经要闻，简明扼要地说明每条新闻的核心要点和潜在影响",
  "market_analysis": "市场分析（500字以内）：\n1. 各主要市场走势分析（A股、美股、日股、港股）\n2. 关键驱动因素分析\n3. 后市展望和风险提示\n4. 投资者关注要点"
}}

要求:
- 数据准确，分析客观
- 中文撰写，专业但易懂
- 突出重要信息，避免泛泛而谈
- 只输出JSON，不要其他内容"""

        try:
            response = client.chat.completions.create(
                model=self.ai_model,
                messages=[
                    {"role": "system", "content": "你是资深全球财经分析师，只输出JSON格式的分析报告。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4,
                max_tokens=3000,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)
            summary = result.get("summary", "暂无分析")
            analysis = result.get("market_analysis", "暂无分析")
            return (summary, analysis)

        except Exception as e:
            logger.error(f"AI 财经分析生成失败: {e}")
            return ("AI 分析生成失败", "AI 分析生成失败")

    def _generate_title(self, markets: List[MarketData], date_str: str) -> str:
        """生成财经早报标题"""
        # 简洁地用市场涨跌信息生成标题
        up_count = sum(1 for m in markets if m.status == "up")
        down_count = sum(1 for m in markets if m.status == "down")

        if up_count > down_count:
            mood = "全球市场偏暖"
        elif down_count > up_count:
            mood = "全球市场承压"
        else:
            mood = "全球市场分化"

        # 找涨跌幅最大的
        if markets:
            biggest = max(markets, key=lambda m: abs(m.change_pct))
            return f"{mood} | {biggest.name}{biggest.change_pct:+.1f}% · {date_str}"
        else:
            return f"全球财经早报 · {date_str}"

    def generate_dingtalk_message(self, report: FinanceReport) -> str:
        """生成钉钉推送的 Markdown 消息"""
        lines = []
        lines.append(f"## 📈 {report.title}")
        lines.append("")

        # 市场行情表格
        if report.markets:
            lines.append("### 💹 主要市场")
            lines.append("")
            for m in report.markets:
                emoji = "🔴" if m.status == "down" else "🟢" if m.status == "up" else "⚪"
                lines.append(f"> {emoji} **{m.name}** {m.price:,.2f}  {m.change_pct:+.2f}%")
            lines.append("")

        # 新闻摘要
        if report.ai_summary:
            lines.append("### 📰 要闻速递")
            lines.append("")
            lines.append(report.ai_summary)
            lines.append("")

        # 市场分析
        if report.market_analysis:
            lines.append("### 📊 市场分析")
            lines.append("")
            lines.append(report.market_analysis)
            lines.append("")

        lines.append("---")
        lines.append("🤖 AI自动生成 · 数据仅供参考，不构成投资建议")

        return "\n".join(lines)
