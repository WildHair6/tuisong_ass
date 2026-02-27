# 📰 论文推送工作流 (Paper Push Workflow)

> 每日自动抓取 arXiv 最新论文 → AI智能分析筛选 → 生成微信公众号文章 → 邮件推送

## ✨ 功能特性

- 🔍 **智能抓取**: 自动从 arXiv 获取指定领域（航天器、机器人等）的最新论文
- 🤖 **AI评审**: 使用 DeepSeek 大模型对每篇论文进行评分、摘要生成和创新点分析
- 🔥 **热点分析**: 综合当日论文，提炼研究热点趋势和前沿方向
- 📝 **公众号排版**: 自动生成可直接粘贴到微信公众号编辑器的精美HTML文章
- 📧 **邮件推送**: 每日定时将论文日报推送到指定邮箱
- 🎛️ **灵活配置**: 支持自定义领域、关键词、筛选阈值等参数

## 📁 项目结构

```
paper_tuisong/
├── main.py                 # 主程序入口
├── config.yaml             # 配置文件（⚠️需填写API密钥）
├── requirements.txt        # Python依赖
├── setup_cron.sh           # 云服务器部署脚本
├── src/
│   ├── __init__.py
│   ├── fetcher.py          # 论文抓取模块 (arXiv API)
│   ├── analyzer.py         # AI分析模块 (DeepSeek)
│   ├── template.py         # 公众号文章生成器
│   ├── pusher.py           # 邮件/钉钉/企微推送
│   └── utils.py            # 工具函数
├── templates/
│   └── wechat_article.html # 公众号HTML模板
├── output/                 # 生成的文章（自动创建）
└── logs/                   # 日志文件（自动创建）
```

## 🚀 快速开始

### 1. 安装依赖

```bash
# 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate    # Linux/Mac
# venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置

编辑 `config.yaml`，填写以下必要信息：

#### DeepSeek API Key
1. 访问 [DeepSeek 开放平台](https://platform.deepseek.com)
2. 注册并创建 API Key
3. 填入 `config.yaml` 的 `ai.api_key` 字段

#### 邮箱 SMTP 配置

**QQ 邮箱（推荐）:**
1. 登录 QQ 邮箱 → 设置 → 账户
2. 开启 POP3/SMTP 服务
3. 生成授权码
4. 填入配置:
   ```yaml
   email:
     smtp_server: "smtp.qq.com"
     smtp_port: 465
     sender_email: "你的QQ邮箱"
     sender_password: "授权码（不是登录密码）"
   ```

**163 邮箱:**
```yaml
email:
  smtp_server: "smtp.163.com"
  smtp_port: 465
  sender_email: "你的163邮箱"
  sender_password: "授权码"
```

**Gmail:**
```yaml
email:
  smtp_server: "smtp.gmail.com"
  smtp_port: 465
  sender_email: "你的Gmail"
  sender_password: "应用专用密码"  # 需在Google账户安全设置中生成
```

#### 也可以用环境变量（更安全）
```bash
export DEEPSEEK_API_KEY="sk-xxx"
export SMTP_EMAIL="your@email.com"
export SMTP_PASSWORD="your-auth-code"
```

### 3. 试运行

```bash
# 试运行（只生成文章，不发邮件）
python main.py --dry-run

# 正式运行
python main.py

# 获取最近3天的论文
python main.py --days 3

# 使用自定义配置
python main.py --config my_config.yaml
```

### 4. 部署定时任务（云服务器）

```bash
# 一键部署
chmod +x setup_cron.sh
./setup_cron.sh
```

这会自动配置 crontab，每天早上 8:00 执行推送。

## ⚙️ 自定义配置

### 修改研究领域

编辑 `config.yaml` 中的 `research` 部分：

```yaml
research:
  arxiv_categories:
    - "cs.RO"          # 机器人学
    - "cs.AI"          # 人工智能
    - "cs.CV"          # 计算机视觉
    - "astro-ph.IM"    # 航天仪器与方法
  keywords:
    - "spacecraft"
    - "robot"
    - "deep learning"
```

**常用 arXiv 分类代码:**
| 代码 | 领域 |
|------|------|
| cs.RO | 机器人学 |
| cs.AI | 人工智能 |
| cs.CV | 计算机视觉 |
| cs.CL | 计算语言学/NLP |
| cs.LG | 机器学习 |
| cs.SY | 系统与控制 |
| eess.SY | 电气系统 |
| astro-ph.IM | 天体仪器方法 |
| astro-ph.EP | 地球与行星 |
| physics.space-ph | 空间物理 |

### 调整筛选标准

```yaml
research:
  max_papers: 10          # 每日推送论文数上限
  score_threshold: 6      # 评分阈值（1-10）
```

### 文章风格

```yaml
article:
  style: "academic"       # academic(学术), popular(科普), brief(简报)
  include_trends: true    # 是否包含研究热点板块
```

## 📊 工作流程图

```
┌─────────────┐
│  定时触发    │  cron 每天 8:00
│  (crontab)  │
└──────┬──────┘
       ▼
┌─────────────┐
│  论文抓取    │  arXiv API → 按领域+关键词过滤
│  (fetcher)  │  获取最近2天的论文
└──────┬──────┘
       ▼
┌─────────────┐
│  AI分析筛选  │  DeepSeek → 评分+中文摘要+创新点
│  (analyzer) │  过滤低分论文，保留Top N
└──────┬──────┘
       ▼
┌─────────────┐
│  热点分析    │  DeepSeek → 趋势洞察+技术展望
│  (analyzer) │
└──────┬──────┘
       ▼
┌─────────────┐
│  生成文章    │  Jinja2模板 → 公众号HTML + 纯文本
│  (template) │  保存到 output/ 目录
└──────┬──────┘
       ▼
┌─────────────┐
│  邮件推送    │  SMTP → 发送到配置的邮箱
│  (pusher)   │
└─────────────┘
```

## 💰 运行成本

| 项目 | 费用 |
|------|------|
| arXiv API | 免费 |
| DeepSeek API | ~¥0.01-0.05/次 (约 ≤¥1.5/月) |
| 云服务器 | 视选择而定 (最低~¥30/月) |
| SMTP邮件 | 免费 |

## 🔧 常见问题

**Q: 为什么没有抓到论文？**
- 检查 `arxiv_categories` 和 `keywords` 配置是否正确
- 尝试增大 `--days` 参数
- arXiv 周末不更新论文

**Q: AI分析报错？**
- 确认 DeepSeek API Key 有效且有余额
- 检查网络连接是否正常

**Q: 邮件发送失败？**
- 确认使用的是**授权码**而非登录密码
- 确认 SMTP 服务已开启
- 检查 smtp_server 和 smtp_port 是否匹配

**Q: 如何添加钉钉/企微推送？**
- 在钉钉群/企微群创建自定义机器人
- 获取 Webhook URL
- `pusher.py` 中已预留 `DingTalkPusher` 和 `WeComPusher` 类，在 `main.py` 中启用即可

## 📜 License

MIT
