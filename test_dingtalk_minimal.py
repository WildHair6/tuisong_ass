#!/usr/bin/env python3
"""
最小化钉钉 Stream 测试脚本 — 仅测试消息接收
"""
import sys
import logging
import asyncio
import json
import yaml

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test")

# 读取配置
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

app_key = config["dingtalk_bot"]["app_key"]
app_secret = config["dingtalk_bot"]["app_secret"]

print(f"\n[TEST] AppKey: {app_key}")
print(f"[TEST] Starting minimal DingTalk Stream test...")
print(f"[TEST] Will print ALL WebSocket frames received\n")

import dingtalk_stream
from dingtalk_stream import AckMessage

class TestHandler(dingtalk_stream.ChatbotHandler):
    """最简单的消息处理器 — 只打印收到的消息"""
    
    async def process(self, callback):
        logger.info(f"[CALLBACK] ===== RECEIVED MESSAGE =====")
        logger.info(f"[CALLBACK] callback.data = {json.dumps(callback.data, ensure_ascii=False)[:500]}")
        logger.info(f"[CALLBACK] callback.headers = {callback.headers}")
        
        incoming_message = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        text_list = self.extract_text_from_incoming_message(incoming_message)
        text = " ".join(text_list).strip() if text_list else ""
        logger.info(f"[CALLBACK] Text: {text}")
        logger.info(f"[CALLBACK] Sender: {incoming_message.sender_id}")
        
        # 尝试回复
        try:
            result = self.reply_text(f"[TEST] 收到消息: {text}", incoming_message)
            logger.info(f"[CALLBACK] reply result: {result}")
        except Exception as e:
            logger.error(f"[CALLBACK] reply failed: {e}")
        
        return AckMessage.STATUS_OK, "OK"

# 也注册一个通用处理器来捕获所有消息
class GenericHandler(dingtalk_stream.CallbackHandler):
    async def process(self, callback):
        logger.info(f"[GENERIC] ===== RECEIVED GENERIC CALLBACK =====")
        logger.info(f"[GENERIC] topic={callback.headers.topic}")
        logger.info(f"[GENERIC] data={json.dumps(callback.data, ensure_ascii=False)[:500]}")
        return AckMessage.STATUS_OK, "OK"


credential = dingtalk_stream.Credential(app_key, app_secret)
client = dingtalk_stream.DingTalkStreamClient(credential)

# 注册 chatbot handler
handler = TestHandler()
client.register_callback_handler(
    dingtalk_stream.ChatbotMessage.TOPIC,
    handler
)

logger.info(f"[TEST] Registered topic: {dingtalk_stream.ChatbotMessage.TOPIC}")
logger.info(f"[TEST] callback_handler_map keys: {list(client.callback_handler_map.keys())}")
logger.info(f"[TEST] Starting client.start_forever()...")

client.start_forever()
