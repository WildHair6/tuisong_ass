#!/usr/bin/env python3
"""
钉钉 AI 助理机器人 - 基于 Stream 模式（长连接）

功能:
  1. 接收钉钉群内 @机器人 的消息
  2. 调用 AI 研究助理处理用户请求
  3. 返回文献搜索、综述、导出等结果
  4. 提供文件下载服务（BibTeX/CSV）

前置条件:
  1. 在钉钉开放平台创建「企业内部应用」
  2. 启用「机器人」功能，选择 Stream 模式
  3. 将 AppKey 和 AppSecret 填入 config.yaml

使用方式:
  python dingtalk_bot_server.py                     # 启动机器人
  python dingtalk_bot_server.py --port 5679         # 指定文件服务端口
  python dingtalk_bot_server.py --webhook-only       # 仅使用 Webhook 推送模式（不需要企业应用）
"""

import os
import sys
import argparse
import logging
import asyncio
import json
import threading
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, send_from_directory, jsonify
from src.utils import load_config
from src.research_assistant import ResearchAssistant

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# 全局配置
EXPORTS_DIR = os.path.join(os.path.dirname(__file__), "exports")

# ============================================================
# Flask 文件下载服务
# ============================================================

file_app = Flask(__name__)


@file_app.route("/download/<filename>")
def download_file(filename):
    """提供导出文件的下载服务（exports + chat_logs）"""
    safe_name = os.path.basename(filename)
    # 先在 exports 目录中找
    filepath = os.path.join(EXPORTS_DIR, safe_name)
    if os.path.exists(filepath):
        return send_from_directory(EXPORTS_DIR, safe_name, as_attachment=True)
    # 再在 chat_logs 目录中找
    chat_logs_dir = os.path.join(os.path.dirname(__file__), "chat_logs")
    filepath2 = os.path.join(chat_logs_dir, safe_name)
    if os.path.exists(filepath2):
        return send_from_directory(chat_logs_dir, safe_name, as_attachment=True)
    return jsonify({"error": "文件不存在"}), 404


@file_app.route("/exports")
def list_exports():
    """列出可下载的文件"""
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    files = []
    for f in sorted(os.listdir(EXPORTS_DIR), reverse=True):
        filepath = os.path.join(EXPORTS_DIR, f)
        if os.path.isfile(filepath):
            size = os.path.getsize(filepath)
            files.append({"name": f, "size": size, "url": f"/download/{f}"})
    return jsonify(files)


def start_file_server(port: int):
    """在后台线程中启动文件下载服务"""
    file_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# ============================================================
# 钉钉 Stream 模式机器人
# ============================================================

class DingTalkBotStream:
    """
    钉钉 Stream 模式机器人

    使用长连接（WebSocket）与钉钉服务器通信，
    不需要公网IP或域名，适合本地/内网部署。
    """

    def __init__(self, config: dict):
        self.config = config
        bot_config = config.get("dingtalk_bot", {})
        self.app_key = bot_config.get("app_key", "")
        self.app_secret = bot_config.get("app_secret", "")
        self.file_server_url = bot_config.get("file_server_url", "http://127.0.0.1:5679")

        if not self.app_key or not self.app_secret:
            raise ValueError(
                "钉钉 AI 助理需要企业内部应用的 AppKey 和 AppSecret。\n"
                "请在 config.yaml 的 dingtalk_bot 部分填入。\n"
                "创建应用: https://open-dev.dingtalk.com → 应用开发 → 企业内部应用"
            )

        self.assistant = ResearchAssistant(config)

    def start(self):
        """启动 Stream 模式机器人"""
        try:
            import dingtalk_stream
            from dingtalk_stream import AckMessage
        except ImportError:
            logger.error(
                "dingtalk-stream 未安装。请运行: pip install dingtalk-stream\n"
                "文档: https://github.com/open-dingtalk/dingtalk-stream-sdk-python"
            )
            sys.exit(1)

        credential = dingtalk_stream.Credential(self.app_key, self.app_secret)
        client = dingtalk_stream.DingTalkStreamClient(credential)

        # 创建聊天机器人消息处理器（继承 SDK 的 ChatbotHandler）
        handler = MyChatbotHandler(self.assistant, self.config)

        # 注册消息回调
        client.register_callback_handler(
            dingtalk_stream.ChatbotMessage.TOPIC,
            handler
        )

        logger.info("🤖 钉钉 AI 助理启动中（Stream 模式）...")
        logger.info(f"   AppKey: {self.app_key[:8]}...")
        client.start_forever()


class MyChatbotHandler:
    """
    聊天机器人消息处理器

    继承 dingtalk_stream.ChatbotHandler 以使用内置的 reply_text / reply_markdown 方法。
    注意: 实际继承在 _create_handler_class() 中动态完成（避免顶层 import）。
    这里先定义为一个代理类，在 __init__ 中动态转换。
    """

    def __new__(cls, assistant, config):
        """动态创建继承自 dingtalk_stream.ChatbotHandler 的实例"""
        import dingtalk_stream

        # 动态创建子类
        class _Handler(dingtalk_stream.ChatbotHandler):
            def __init__(self, _assistant, _config):
                super().__init__()
                self._assistant = _assistant
                self._config = _config

            async def process(self, callback):
                from dingtalk_stream import AckMessage, ChatbotMessage
                incoming_message = ChatbotMessage.from_dict(callback.data)

                # 提取文本内容
                text_list = self.extract_text_from_incoming_message(incoming_message)
                user_message = " ".join(text_list).strip() if text_list else ""
                user_id = incoming_message.sender_id or ""
                sender_nick = getattr(incoming_message, 'sender_nick', '') or ''

                logger.info(f"收到钉钉消息 [{sender_nick}({user_id})]: {user_message[:100]}")

                if not user_message:
                    self.reply_text("请输入您的问题或指令。发送「帮助」查看使用指南。",
                                    incoming_message)
                    return AckMessage.STATUS_OK, "OK"

                try:
                    # 先发送"处理中"提示
                    self.reply_text("🔍 正在处理您的请求，请稍候...", incoming_message)

                    # 调用 AI 研究助理（handle_message 是 async）
                    result = await self._assistant.handle_message(user_message, user_id)

                    reply_text = result.get("text", "")
                    files = result.get("files", [])

                    # 如果有文件，附加下载链接
                    if files:
                        file_server = self._config.get("dingtalk_bot", {}).get(
                            "file_server_url", "http://127.0.0.1:5679")
                        reply_text += "\n\n---\n📥 **文件下载:**\n"
                        for f in files:
                            url = f.get("url", "")
                            if url and not url.startswith("http"):
                                url = f"{file_server}{url}"
                            reply_text += f"- [{f['name']}]({url})\n"

                    # 回复 Markdown 消息
                    self.reply_markdown("AI 助理回复", reply_text[:20000], incoming_message)

                except Exception as e:
                    logger.error(f"处理消息失败: {e}", exc_info=True)
                    self.reply_text(f"❌ 处理消息时发生错误: {str(e)[:200]}", incoming_message)

                return AckMessage.STATUS_OK, "OK"

        return _Handler(assistant, config)


# ============================================================
# Webhook-only 模式（仅推送，不接收消息）
# 适用于只有自定义 Webhook 机器人的情况
# ============================================================

class DingTalkBotWebhookOnly:
    """
    仅 Webhook 推送模式

    当用户还没有配置企业内部应用时，可以先用这个模式。
    提供 HTTP 接口，用户可以通过浏览器/curl 发送查询。
    """

    def __init__(self, config: dict):
        self.config = config
        self.assistant = ResearchAssistant(config)
        self.app = Flask(__name__)
        self._setup_routes()

    def _setup_routes(self):
        @self.app.route("/")
        def index():
            return """
            <html><head><title>AI 研究助理</title></head>
            <body style="font-family: sans-serif; max-width: 800px; margin: 50px auto; padding: 20px;">
            <h1>🤖 AI 研究助理</h1>
            <p>使用 API 接口发送查询:</p>
            <pre>POST /api/ask
Content-Type: application/json
{"message": "搜索机器人抓取相关的论文"}</pre>
            <p>或直接在下方输入:</p>
            <form id="askForm">
                <textarea id="msg" rows="3" style="width:100%;font-size:16px;" placeholder="输入你的问题..."></textarea>
                <button type="submit" style="margin-top:10px;padding:10px 30px;font-size:16px;">提交</button>
            </form>
            <div id="result" style="margin-top:20px;white-space:pre-wrap;"></div>
            <script>
            document.getElementById('askForm').onsubmit = async (e) => {
                e.preventDefault();
                const msg = document.getElementById('msg').value;
                document.getElementById('result').textContent = '处理中...';
                const resp = await fetch('/api/ask', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: msg})
                });
                const data = await resp.json();
                document.getElementById('result').textContent = data.text || JSON.stringify(data);
            };
            </script>
            </body></html>
            """

        @self.app.route("/api/ask", methods=["POST"])
        def api_ask():
            from flask import request
            data = json.loads(request.data) if request.data else {}
            message = data.get("message", "")
            if not message:
                return jsonify({"error": "请提供 message 参数"})

            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    self.assistant.handle_message(message)
                )
                return jsonify(result)
            except Exception as e:
                return jsonify({"error": str(e)})
            finally:
                loop.close()

    def start(self, host: str = "0.0.0.0", port: int = 5680):
        logger.info(f"🤖 AI 研究助理（Web 模式）启动: http://{host}:{port}")
        self.app.run(host=host, port=port, debug=False)


# ============================================================
# 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="钉钉 AI 助理机器人")
    parser.add_argument("--port", type=int, default=5679,
                        help="文件下载服务端口 (默认: 5679)")
    parser.add_argument("--webhook-only", action="store_true",
                        help="仅使用 Webhook 推送模式（提供 Web 界面，不需要企业应用）")
    parser.add_argument("--web-port", type=int, default=5680,
                        help="Web 模式端口 (默认: 5680)")
    parser.add_argument("--config", type=str, default=None,
                        help="配置文件路径")
    args = parser.parse_args()

    # 加载配置
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"❌ 配置文件加载失败: {e}")
        sys.exit(1)

    os.makedirs(EXPORTS_DIR, exist_ok=True)

    # 设置 stdout/stderr 编码（Windows GBK 兼容）
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    mode_str = "Webhook (Web界面)" if args.webhook_only else "Stream (钉钉长连接)"
    print(f"""
========================================
  DingTalk AI Research Assistant
========================================
  File Server : http://0.0.0.0:{args.port}
  Mode        : {mode_str}
========================================
    """)

    # 启动文件下载服务（后台线程）
    file_thread = threading.Thread(
        target=start_file_server,
        args=(args.port,),
        daemon=True
    )
    file_thread.start()
    logger.info(f"📂 文件下载服务已启动: http://0.0.0.0:{args.port}")

    if args.webhook_only:
        # Web 模式
        bot = DingTalkBotWebhookOnly(config)
        bot.start(port=args.web_port)
    else:
        # Stream 模式
        try:
            bot = DingTalkBotStream(config)
            bot.start()
        except ValueError as e:
            logger.error(str(e))
            logger.info("\n💡 提示: 如果还没有配置企业内部应用，可以先用 --webhook-only 模式:")
            logger.info("   python dingtalk_bot_server.py --webhook-only")
            sys.exit(1)


if __name__ == "__main__":
    main()
