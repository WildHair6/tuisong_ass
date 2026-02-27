"""
工具函数模块
"""

import os
import yaml
import logging
import logging.handlers
from datetime import datetime


def load_config(config_path: str = None) -> dict:
    """
    加载配置文件
    
    Args:
        config_path: 配置文件路径，默认为项目根目录下的 config.yaml
    
    Returns:
        配置字典
    """
    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "config.yaml"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 支持环境变量覆盖敏感配置
    env_overrides = {
        "ai.api_key": "DEEPSEEK_API_KEY",
        "email.sender_email": "SMTP_EMAIL",
        "email.sender_password": "SMTP_PASSWORD",
    }

    for key_path, env_var in env_overrides.items():
        env_value = os.environ.get(env_var)
        if env_value:
            keys = key_path.split(".")
            d = config
            for k in keys[:-1]:
                d = d[k]
            d[keys[-1]] = env_value

    return config


def setup_logging(config: dict):
    """
    配置日志系统
    
    Args:
        config: 配置字典
    """
    log_config = config.get("logging", {})
    log_level = getattr(logging, log_config.get("level", "INFO").upper())
    log_file = log_config.get("log_file", "./logs/paper_push.log")
    max_size = log_config.get("max_size_mb", 10) * 1024 * 1024
    backup_count = log_config.get("backup_count", 7)

    # 确保日志目录存在
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # 配置根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 清除已有的处理器
    root_logger.handlers.clear()

    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(console_format)
    root_logger.addHandler(console_handler)

    # 文件输出（自动轮转）
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=max_size,
        backupCount=backup_count,
        encoding="utf-8"
    )
    file_handler.setLevel(log_level)
    file_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
    )
    file_handler.setFormatter(file_format)
    root_logger.addHandler(file_handler)


def get_date_str() -> str:
    """获取当前日期字符串"""
    return datetime.now().strftime("%Y年%m月%d日")
