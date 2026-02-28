# 📰 多频道智能推送 + AI 研究助理 (v2.0)

> 每日自动推送三大频道日报到钉钉群 + 支持钉钉群内 AI 文献调研助理

## ✨ 功能特性

### 📡 三大早报频道（每天自动推送）
- 🚀 **航天前沿日报**: Semantic Scholar 抓取航天器、卫星、空间探测等领域最新文献
- 🤖 **机器人与AI日报**: Semantic Scholar 抓取机器人学、深度学习、具身智能等领域最新文献
- 📈 **全球财经早报**: DuckDuckGo 搜索财经新闻 + Yahoo Finance 市场行情 + AI 分析

### 🤖 钉钉 AI 研究助理（随时互动）
- 📚 **文献调研**: 在钉钉群中 @机器人 即可搜索 Semantic Scholar 文献
- 📖 **文献综述**: 自动生成指定主题的文献综述报告
- 📦 **文献导出**: 导出 BibTeX / CSV 文件，提供下载链接
- 👤 **作者查询**: 查询学者信息、论文列表、H-index
- ❓ **研究问答**: 回答科研相关问题

## 📁 项目结构

```
paper_tuisong/
├── main.py                     # 多频道推送主程序
├── dingtalk_bot_server.py      # 钉钉 AI 助理服务
├── review_server.py            # 论文审核 Web 面板
├── config.yaml                 # 配置文件（⚠️需填写密钥）
├── requirements.txt            # Python 依赖
├── src/
│   ├── semantic_scholar.py     # Semantic Scholar 主数据源
│   ├── news_fetcher.py         # 财经新闻抓取 + AI 分析
│   ├── research_assistant.py   # AI 研究助理（意图解析+处理）
│   ├── literature_export.py    # 文献导出（BibTeX/CSV）
│   ├── analyzer.py             # AI 论文分析与筛选
│   ├── template.py             # 公众号文章生成器
│   ├── pusher.py               # 钉钉/邮件/企微推送
│   ├── fetcher.py              # Paper 数据结构 + arXiv（可选）
│   ├── cache.py                # 缓存去重
│   └── utils.py                # 工具函数
├── templates/                  # HTML 模板
├── exports/                    # 导出的 BibTeX/CSV 文件
├── output/                     # 生成的文章
└── logs/                       # 日志文件
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

编辑 `config.yaml`，填写必要信息：

#### 必填项
- **DeepSeek API Key**: 在 [platform.deepseek.com](https://platform.deepseek.com) 获取，填入 `ai.api_key`
- **钉钉 Webhook**: 已配置（用于推送早报）

#### 可选项
- **Semantic Scholar API Key**: [申请地址](https://www.semanticscholar.org/product/api)（提高速率限制）
- **钉钉企业内部应用**: 用于 AI 助理双向交互（见下方说明）

### 3. 推送早报

```bash
# 推送全部3个频道
python main.py

# 仅推送某个频道
python main.py --channel aerospace   # 航天
python main.py --channel robotics    # 机器人AI
python main.py --channel finance     # 财经

# 试运行（不发送）
python main.py --dry-run

# 增加文献回溯天数
python main.py --days 14
```

### 4. 启动 AI 助理

```bash
# 方式一: Stream 模式（需要钉钉企业内部应用）
python dingtalk_bot_server.py

# 方式二: Web 界面模式（不需要钉钉应用，可在浏览器使用）
python dingtalk_bot_server.py --webhook-only
```

### 5. 定时推送（crontab）

```bash
# 每天早上 8:00 推送三个频道
0 8 * * * cd /path/to/paper_tuisong && python main.py >> logs/cron.log 2>&1
```

## 🔧 钉钉 AI 助理配置指南

### 方式一: Web 模式（快速体验）
无需额外配置，直接运行:
```bash
python dingtalk_bot_server.py --webhook-only
```
然后访问 `http://localhost:5680` 即可在浏览器中使用 AI 研究助理。

### 方式二: Stream 模式（在钉钉群中使用）

1. 访问 [钉钉开放平台](https://open-dev.dingtalk.com)
2. 应用开发 → 企业内部应用 → 创建应用
3. 在「机器人」页面启用机器人功能
4. 在「消息推送」中选择 **Stream 模式**
5. 在「版本管理与发布」中发布应用
6. 在钉钉群中添加该机器人
7. 将 AppKey 和 AppSecret 填入 `config.yaml`:

```yaml
dingtalk_bot:
  app_key: "your-app-key"
  app_secret: "your-app-secret"
```

8. 启动: `python dingtalk_bot_server.py`
9. 在钉钉群中 @机器人 即可开始使用

### AI 助理使用示例

在钉钉群中 @机器人 发送:
- `搜索关于机器人抓取的最新论文`
- `帮我写一篇空间碎片主动清除技术的文献综述`
- `导出spacecraft formation flying相关文献的BibTeX`
- `查询作者 Yoshua Bengio 的信息`
- `强化学习和模仿学习有什么区别？`
- `帮助` - 查看完整使用指南

## 💰 运行成本

| 项目 | 费用 |
|------|------|
| Semantic Scholar API | 免费（100次/5分钟）|
| DuckDuckGo 搜索 | 免费 |
| Yahoo Finance 行情 | 免费 |
| DeepSeek API | ~¥0.05-0.1/天（约 ≤¥3/月）|
| 钉钉机器人 | 免费 |

## 📜 License

MIT

