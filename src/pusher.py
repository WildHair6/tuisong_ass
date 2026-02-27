"""
推送模块 - 邮件 / 钉钉 / 企业微信 推送论文日报
"""

import smtplib
import json
import time
import hmac
import hashlib
import base64
import urllib.parse
import logging
import requests
from typing import List, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

logger = logging.getLogger(__name__)


class EmailPusher:
    """通过 SMTP 发送邮件"""

    def __init__(self, config: dict):
        email_config = config["email"]
        self.smtp_server = email_config["smtp_server"]
        self.smtp_port = email_config["smtp_port"]
        self.use_ssl = email_config.get("use_ssl", True)
        self.sender_email = email_config["sender_email"]
        self.sender_password = email_config["sender_password"]
        self.receivers = email_config["receivers"]
        self.subject_prefix = email_config.get("subject_prefix", "【论文日报】")

    def send(self, subject: str, html_content: str, plain_text: str = None) -> bool:
        """
        发送邮件

        Args:
            subject: 邮件主题
            html_content: HTML格式的邮件内容
            plain_text: 纯文本内容（备用）

        Returns:
            是否发送成功
        """
        full_subject = f"{self.subject_prefix}{subject}"

        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = Header(f"论文日报 <{self.sender_email}>")
            msg["To"] = ", ".join(self.receivers)
            msg["Subject"] = Header(full_subject, "utf-8")

            # 添加纯文本版本（邮件客户端不支持HTML时显示）
            if plain_text:
                text_part = MIMEText(plain_text, "plain", "utf-8")
                msg.attach(text_part)

            # 添加HTML版本
            html_part = MIMEText(html_content, "html", "utf-8")
            msg.attach(html_part)

            # 连接SMTP服务器
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=30)
            else:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=30)
                server.starttls()

            server.login(self.sender_email, self.sender_password)
            server.sendmail(self.sender_email, self.receivers, msg.as_string())
            server.quit()

            logger.info(f"邮件发送成功: {full_subject} → {self.receivers}")
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"邮箱认证失败，请检查授权码: {e}")
            return False
        except smtplib.SMTPConnectError as e:
            logger.error(f"无法连接SMTP服务器 {self.smtp_server}:{self.smtp_port}: {e}")
            return False
        except Exception as e:
            logger.error(f"邮件发送失败: {e}")
            return False


class DingTalkPusher:
    """
    钉钉机器人推送 - 支持富文本卡片消息 + 审核摘要
    配置方式: 钉钉群 → 群设置 → 智能群助手 → 添加自定义机器人
    """

    def __init__(self, config: dict):
        dt_config = config.get("dingtalk", {})
        self.webhook_url = dt_config.get("webhook_url", "")
        self.secret = dt_config.get("secret", "")

    def _sign_url(self) -> str:
        """生成带签名的 Webhook URL"""
        if not self.secret:
            return self.webhook_url
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        return f"{self.webhook_url}&timestamp={timestamp}&sign={sign}"

    def _post(self, data: dict) -> bool:
        """发送消息到钉钉"""
        try:
            url = self._sign_url()
            resp = requests.post(url, json=data, timeout=30)
            result = resp.json()
            if result.get("errcode") == 0:
                logger.info("钉钉消息发送成功")
                return True
            else:
                logger.error(f"钉钉消息发送失败: {result}")
                return False
        except Exception as e:
            logger.error(f"钉钉推送异常: {e}")
            return False

    def send(self, title: str, content: str) -> bool:
        """发送 Markdown 消息"""
        data = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": content}
        }
        return self._post(data)

    def send_paper_card(self, title: str, papers: list, trends: str = "",
                        date_str: str = "", review_url: str = "") -> bool:
        """
        发送论文日报 ActionCard 卡片消息（手机上显示为精美卡片）

        Args:
            title: 文章标题
            papers: 精选论文列表
            trends: 研究热点概要
            date_str: 日期
            review_url: 审核页面地址（如有）
        """
        # 构建 Markdown 内容
        lines = []
        lines.append(f"## 📰 {title}")
        lines.append(f"")
        lines.append(f"**{date_str}** · 精选 **{len(papers)}** 篇高质量论文")
        lines.append(f"")

        # 热点摘要（只取前200字）
        if trends:
            short_trends = trends[:200].replace("\n", " ").strip()
            lines.append(f"### 🔥 研究热点")
            lines.append(f"> {short_trends}...")
            lines.append(f"")

        # 论文列表
        lines.append(f"### 📄 论文清单")
        lines.append(f"")
        for i, p in enumerate(papers, 1):
            score_emoji = "🌟" if p.score >= 9 else "⭐" if p.score >= 8 else "★"
            # 来源标识
            if hasattr(p, 'arxiv_id'):
                if p.arxiv_id.startswith('cr-'):
                    src = "期刊"
                elif p.arxiv_id.startswith('oa-'):
                    src = "OpenAlex"
                elif p.arxiv_id.startswith('s2-'):
                    src = "S2"
                else:
                    src = "arXiv"
            else:
                src = "arXiv"

            lines.append(f"**{i}. {p.title[:60]}{'...' if len(p.title) > 60 else ''}**")
            lines.append(f"> {score_emoji} {p.score:.1f}分 | {src} | {', '.join(p.authors[:2])}")

            # 摘要只取前80字
            if p.summary_zh:
                short_summary = p.summary_zh[:80].strip()
                lines.append(f"> 📝 {short_summary}...")
            lines.append(f"")

        lines.append(f"---")
        lines.append(f"🤖 AI自动分析 | 评分仅供参考")

        md_text = "\n".join(lines)

        # 根据是否有审核URL决定消息类型
        if review_url:
            # ActionCard 带按钮
            data = {
                "msgtype": "actionCard",
                "actionCard": {
                    "title": f"📰 {title}",
                    "text": md_text,
                    "btnOrientation": "1",  # 按钮横向排列
                    "btns": [
                        {
                            "title": "✅ 查看详情 & 审核",
                            "actionURL": review_url
                        },
                        {
                            "title": "📥 查看原文",
                            "actionURL": papers[0].url if papers else "https://arxiv.org"
                        }
                    ]
                }
            }
        else:
            # 普通 ActionCard（单按钮）
            data = {
                "msgtype": "actionCard",
                "actionCard": {
                    "title": f"📰 {title}",
                    "text": md_text,
                    "singleTitle": "📖 查看完整日报",
                    "singleURL": papers[0].url if papers else "https://arxiv.org"
                }
            }

        return self._post(data)

    def send_review_result(self, action: str, title: str, detail: str = "") -> bool:
        """
        发送审核结果通知

        Args:
            action: "approved" / "rejected"
            title: 文章标题
            detail: 附加说明
        """
        if action == "approved":
            text = f"## ✅ 已通过审核\n\n**{title}**\n\n{detail}\n\n> 文章即将发布"
        else:
            text = f"## ❌ 审核未通过\n\n**{title}**\n\n{detail}\n\n> 本期不发布"

        data = {
            "msgtype": "markdown",
            "markdown": {"title": f"审核结果: {title[:20]}", "text": text}
        }
        return self._post(data)


class WeComPusher:
    """
    企业微信机器人推送（预留接口）
    使用方法: 在企业微信群中添加机器人，获取Webhook URL
    """

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, content: str) -> bool:
        import requests

        data = {
            "msgtype": "markdown",
            "markdown": {
                "content": content[:4096]  # 企业微信限制4096字节
            }
        }

        try:
            resp = requests.post(self.webhook_url, json=data, timeout=10)
            result = resp.json()
            if result.get("errcode") == 0:
                logger.info("企业微信消息发送成功")
                return True
            else:
                logger.error(f"企业微信消息发送失败: {result}")
                return False
        except Exception as e:
            logger.error(f"企业微信推送异常: {e}")
            return False
