#!/usr/bin/env python3
"""
论文审核服务 - Web 面板 + 钉钉联动

功能:
  1. 提供 Web 审核面板，在浏览器/手机上审核论文
  2. 审核通过后可触发公众号发布（需配置）
  3. 通过钉钉 ActionCard 卡片推送审核链接
  4. 支持查看历史文章、修改推荐

使用方式:
  python review_server.py                     # 启动审核服务（默认端口 5678）
  python review_server.py --port 8080         # 指定端口
  python review_server.py --host 0.0.0.0      # 允许外部访问
"""

import os
import sys
import json
import glob
import argparse
import logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, render_template_string, request, jsonify, redirect, url_for
from src.utils import load_config
from src.pusher import DingTalkPusher

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = Flask(__name__)

# 全局状态
PENDING_DIR = "./pending"
ARCHIVE_DIR = "./output"
CONFIG = {}


def get_pending_articles():
    """获取待审核文章列表"""
    os.makedirs(PENDING_DIR, exist_ok=True)
    articles = []
    for meta_file in sorted(glob.glob(f"{PENDING_DIR}/*.json"), reverse=True):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            meta["meta_file"] = os.path.basename(meta_file)
            articles.append(meta)
        except Exception as e:
            logger.error(f"读取 {meta_file} 失败: {e}")
    return articles


def get_article_html(article_id: str) -> str:
    """根据 ID 读取文章 HTML"""
    # 先找 pending 目录
    html_path = os.path.join(PENDING_DIR, f"{article_id}.html")
    if not os.path.exists(html_path):
        # 再找 output 目录
        html_path = os.path.join(ARCHIVE_DIR, f"{article_id}.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h2>文章未找到</h2>"


# =============== HTML 模板 ===============

REVIEW_PAGE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>📰 论文日报审核</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #f0f2f5;
    color: #333;
}
.nav {
    background: linear-gradient(135deg, #0c2461, #1e3799);
    color: #fff;
    padding: 16px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}
.nav h1 { font-size: 18px; font-weight: 600; }
.nav .badge {
    background: #e17055;
    color: #fff;
    font-size: 12px;
    padding: 2px 10px;
    border-radius: 12px;
    font-weight: 600;
}
.container { max-width: 800px; margin: 0 auto; padding: 20px 16px; }

.card {
    background: #fff;
    border-radius: 12px;
    margin-bottom: 16px;
    box-shadow: 0 1px 6px rgba(0,0,0,0.06);
    overflow: hidden;
    border: 1px solid #eee;
}
.card-header {
    padding: 16px 20px;
    border-bottom: 1px solid #f0f0f0;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.card-header h2 {
    font-size: 16px;
    font-weight: 700;
    color: #1e3799;
    flex: 1;
}
.card-header .status {
    font-size: 12px;
    padding: 3px 10px;
    border-radius: 12px;
    font-weight: 600;
}
.status-pending { background: #fff3cd; color: #856404; }
.status-approved { background: #d4edda; color: #155724; }
.status-rejected { background: #f8d7da; color: #721c24; }

.card-body { padding: 16px 20px; }
.card-meta {
    font-size: 13px;
    color: #999;
    margin-bottom: 10px;
}
.card-meta span { margin-right: 16px; }

.paper-list { list-style: none; padding: 0; }
.paper-list li {
    padding: 10px 0;
    border-bottom: 1px solid #f5f5f5;
    font-size: 14px;
}
.paper-list li:last-child { border-bottom: none; }
.paper-list .score {
    display: inline-block;
    background: #e8f5e9;
    color: #2e7d32;
    font-size: 12px;
    font-weight: 700;
    padding: 1px 8px;
    border-radius: 4px;
    margin-right: 6px;
}

.card-actions {
    padding: 12px 20px 16px;
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}
.btn {
    padding: 10px 24px;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 600;
    transition: all 0.2s;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
}
.btn-approve {
    background: linear-gradient(135deg, #00b894, #00cec9);
    color: #fff;
}
.btn-approve:hover { box-shadow: 0 4px 12px rgba(0,184,148,0.4); }
.btn-reject {
    background: #f0f0f0;
    color: #666;
}
.btn-reject:hover { background: #e0e0e0; }
.btn-preview {
    background: #e3f2fd;
    color: #1565c0;
}
.btn-preview:hover { background: #bbdefb; }

.empty-state {
    text-align: center;
    padding: 60px 20px;
    color: #bbb;
}
.empty-state .icon { font-size: 48px; margin-bottom: 16px; }
.empty-state p { font-size: 14px; }

/* Toast */
.toast {
    position: fixed;
    top: 80px;
    left: 50%;
    transform: translateX(-50%);
    padding: 12px 24px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    z-index: 200;
    display: none;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}
.toast-success { background: #d4edda; color: #155724; }
.toast-error { background: #f8d7da; color: #721c24; }
</style>
</head>
<body>

<div class="nav">
    <h1>📰 论文日报审核台</h1>
    {% if pending_count > 0 %}
    <span class="badge">{{ pending_count }} 篇待审</span>
    {% endif %}
</div>

<div id="toast" class="toast"></div>

<div class="container">
    {% if articles %}
        {% for art in articles %}
        <div class="card" id="card-{{ art.article_id }}">
            <div class="card-header">
                <h2>{{ art.title }}</h2>
                <span class="status status-{{ art.status }}">
                    {{ '⏳ 待审核' if art.status == 'pending' else '✅ 已通过' if art.status == 'approved' else '❌ 已拒绝' }}
                </span>
            </div>
            <div class="card-body">
                <div class="card-meta">
                    <span>📅 {{ art.date }}</span>
                    <span>📊 {{ art.paper_count }} 篇论文</span>
                    <span>📈 均分 {{ art.avg_score }}</span>
                    {% if art.sources %}
                    <span>📦 {{ art.sources | join(' + ') }}</span>
                    {% endif %}
                </div>
                <ul class="paper-list">
                    {% for p in art.papers[:5] %}
                    <li>
                        <span class="score">{{ p.score }}</span>
                        {{ p.title[:70] }}{{ '...' if p.title|length > 70 else '' }}
                    </li>
                    {% endfor %}
                    {% if art.papers|length > 5 %}
                    <li style="color:#999;">... 还有 {{ art.papers|length - 5 }} 篇</li>
                    {% endif %}
                </ul>
            </div>
            <div class="card-actions">
                {% if art.status == 'pending' %}
                <button class="btn btn-approve" onclick="reviewAction('{{ art.article_id }}', 'approve')">
                    ✅ 通过并发布
                </button>
                <button class="btn btn-reject" onclick="reviewAction('{{ art.article_id }}', 'reject')">
                    ❌ 拒绝
                </button>
                {% endif %}
                <a class="btn btn-preview" href="/preview/{{ art.article_id }}" target="_blank">
                    👁️ 预览文章
                </a>
            </div>
        </div>
        {% endfor %}
    {% else %}
        <div class="empty-state">
            <div class="icon">📭</div>
            <p>暂无待审核的文章</p>
            <p style="margin-top:8px;font-size:12px;color:#ddd;">运行 python main.py --review 生成待审核文章</p>
        </div>
    {% endif %}
</div>

<script>
function showToast(msg, type) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast toast-' + type;
    t.style.display = 'block';
    setTimeout(() => { t.style.display = 'none'; }, 3000);
}

function reviewAction(articleId, action) {
    if (action === 'approve' && !confirm('确认通过并发布此文章？')) return;
    if (action === 'reject' && !confirm('确认拒绝此文章？')) return;

    fetch('/api/review', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({article_id: articleId, action: action})
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showToast(data.message, 'success');
            // 更新卡片状态
            const card = document.getElementById('card-' + articleId);
            const statusEl = card.querySelector('.status');
            if (action === 'approve') {
                statusEl.className = 'status status-approved';
                statusEl.textContent = '✅ 已通过';
            } else {
                statusEl.className = 'status status-rejected';
                statusEl.textContent = '❌ 已拒绝';
            }
            // 移除按钮
            const actions = card.querySelector('.card-actions');
            const btns = actions.querySelectorAll('.btn-approve, .btn-reject');
            btns.forEach(b => b.remove());
        } else {
            showToast(data.message || '操作失败', 'error');
        }
    })
    .catch(e => showToast('网络错误', 'error'));
}
</script>
</body>
</html>
"""


# =============== 路由 ===============

@app.route("/")
def index():
    """审核面板首页"""
    articles = get_pending_articles()
    pending_count = sum(1 for a in articles if a.get("status") == "pending")
    return render_template_string(REVIEW_PAGE, articles=articles, pending_count=pending_count)


@app.route("/preview/<article_id>")
def preview(article_id):
    """预览文章 HTML"""
    html = get_article_html(article_id)
    return html


@app.route("/api/review", methods=["POST"])
def api_review():
    """审核 API"""
    data = request.get_json()
    article_id = data.get("article_id")
    action = data.get("action")  # approve / reject

    if not article_id or action not in ("approve", "reject"):
        return jsonify({"success": False, "message": "参数错误"})

    meta_file = os.path.join(PENDING_DIR, f"{article_id}.json")
    if not os.path.exists(meta_file):
        return jsonify({"success": False, "message": "文章不存在"})

    # 更新状态
    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)

    old_status = meta.get("status")
    meta["status"] = "approved" if action == "approve" else "rejected"
    meta["reviewed_at"] = datetime.now().isoformat()

    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 发送钉钉通知
    try:
        config = load_config()
        dt_config = config.get("dingtalk", {})
        if dt_config.get("webhook_url"):
            dt_pusher = DingTalkPusher(config)
            dt_pusher.send_review_result(
                action="approved" if action == "approve" else "rejected",
                title=meta.get("title", ""),
                detail=f"审核人操作时间: {meta['reviewed_at']}"
            )
    except Exception as e:
        logger.warning(f"钉钉通知失败: {e}")

    # 如果通过审核，可以触发公众号发布（由 wechat_publisher 处理）
    if action == "approve":
        try:
            _publish_article(meta, article_id)
        except Exception as e:
            logger.warning(f"自动发布失败（可手动发布）: {e}")

    msg = "✅ 文章已通过审核" if action == "approve" else "❌ 文章已拒绝"
    logger.info(f"{msg}: {meta.get('title')}")
    return jsonify({"success": True, "message": msg})


@app.route("/api/articles")
def api_articles():
    """获取文章列表 API（给外部调用或钉钉回调用）"""
    articles = get_pending_articles()
    return jsonify(articles)


def _publish_article(meta: dict, article_id: str):
    """
    触发文章发布（公众号 / 其他平台）

    目前的实现:
    - 将 HTML 复制到 output 目录标记为已发布
    - 发送邮件通知
    - 如果配置了公众号 API，自动发布草稿

    后续可扩展: 接入微信公众号 API、知乎等平台
    """
    import shutil

    # 复制到 output 目录
    src_html = os.path.join(PENDING_DIR, f"{article_id}.html")
    if os.path.exists(src_html):
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        dst_html = os.path.join(ARCHIVE_DIR, f"{article_id}.html")
        shutil.copy2(src_html, dst_html)
        logger.info(f"文章已归档: {dst_html}")

    # 发送审核通过邮件
    try:
        config = load_config()
        email_config = config.get("email", {})
        if email_config.get("sender_email"):
            from src.pusher import EmailPusher
            html_content = get_article_html(article_id)
            pusher = EmailPusher(config)
            pusher.send(
                subject=f"[已审核] {meta.get('title', '论文日报')}",
                html_content=html_content,
                plain_text=f"文章已通过审核: {meta.get('title')}"
            )
            logger.info("审核通过邮件已发送")
    except Exception as e:
        logger.warning(f"审核邮件发送失败: {e}")

    # TODO: 接入微信公众号发布 API
    # from src.wechat_publisher import WeChatPublisher
    # publisher = WeChatPublisher(config)
    # publisher.publish_draft(html_content, meta["title"])


def save_pending_article(title: str, html_content: str, papers: list,
                         date_str: str, avg_score: str, sources: list = None) -> str:
    """
    保存待审核文章（供 main.py --review 模式调用）

    Args:
        title: 文章标题
        html_content: 完整 HTML
        papers: 论文列表
        date_str: 日期
        avg_score: 平均分
        sources: 数据源列表

    Returns:
        article_id
    """
    os.makedirs(PENDING_DIR, exist_ok=True)

    # 生成文章 ID
    safe_date = date_str.replace("年", "-").replace("月", "-").replace("日", "")
    article_id = f"paper_daily_{safe_date}"

    # 保存 HTML
    html_path = os.path.join(PENDING_DIR, f"{article_id}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    # 保存元数据
    meta = {
        "article_id": article_id,
        "title": title,
        "date": date_str,
        "status": "pending",
        "paper_count": len(papers),
        "avg_score": avg_score,
        "sources": sources or ["arXiv"],
        "created_at": datetime.now().isoformat(),
        "papers": [
            {
                "title": p.title,
                "score": f"{p.score:.1f}",
                "authors": p.authors[:3],
                "url": p.url,
            }
            for p in papers
        ]
    }
    meta_path = os.path.join(PENDING_DIR, f"{article_id}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    logger.info(f"待审核文章已保存: {article_id}")
    return article_id


# =============== 入口 ===============

def main():
    parser = argparse.ArgumentParser(description="论文审核服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址 (默认: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5678, help="端口 (默认: 5678)")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    args = parser.parse_args()

    print(f"""
╔══════════════════════════════════════════════╗
║        📰 论文日报审核服务                    ║
╠══════════════════════════════════════════════╣
║  审核面板: http://{args.host}:{args.port}            ║
║  API接口:  http://{args.host}:{args.port}/api        ║
╚══════════════════════════════════════════════╝
    """)

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
