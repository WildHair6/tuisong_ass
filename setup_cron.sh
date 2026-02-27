#!/bin/bash
# ============================================================
# 论文推送工作流 - 云服务器 cron 部署脚本
# 
# 使用方法:
#   chmod +x setup_cron.sh
#   ./setup_cron.sh
# ============================================================

set -e

echo "🚀 论文推送工作流 - 部署脚本"
echo "================================="

# 1. 获取项目路径
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "📁 项目目录: $PROJECT_DIR"

# 2. 创建Python虚拟环境
echo ""
echo "📦 Step 1: 创建Python虚拟环境..."
if [ ! -d "$PROJECT_DIR/venv" ]; then
    python3 -m venv "$PROJECT_DIR/venv"
    echo "✅ 虚拟环境创建成功"
else
    echo "ℹ️  虚拟环境已存在，跳过"
fi

# 3. 安装依赖
echo ""
echo "📦 Step 2: 安装Python依赖..."
source "$PROJECT_DIR/venv/bin/activate"
pip install -r "$PROJECT_DIR/requirements.txt" -q
echo "✅ 依赖安装完成"

# 4. 创建必要目录
echo ""
echo "📁 Step 3: 创建目录..."
mkdir -p "$PROJECT_DIR/output"
mkdir -p "$PROJECT_DIR/logs"
echo "✅ 目录创建完成"

# 5. 创建运行脚本
RUN_SCRIPT="$PROJECT_DIR/run.sh"
cat > "$RUN_SCRIPT" << EOF
#!/bin/bash
# 论文推送 - 定时运行脚本
cd "$PROJECT_DIR"
source "$PROJECT_DIR/venv/bin/activate"

# 设置环境变量（也可以在config.yaml中直接配置）
# export DEEPSEEK_API_KEY="your-key-here"
# export SMTP_EMAIL="your-email@qq.com"
# export SMTP_PASSWORD="your-authorization-code"

python main.py >> "$PROJECT_DIR/logs/cron.log" 2>&1
EOF
chmod +x "$RUN_SCRIPT"
echo "✅ 运行脚本创建: $RUN_SCRIPT"

# 6. 配置 crontab
echo ""
echo "⏰ Step 4: 配置定时任务..."
CRON_JOB="0 8 * * * $RUN_SCRIPT"

# 检查是否已存在
(crontab -l 2>/dev/null | grep -v "$RUN_SCRIPT"; echo "$CRON_JOB") | crontab -
echo "✅ Crontab 已配置: 每天早上 8:00 执行"
echo "   $CRON_JOB"

# 7. 验证
echo ""
echo "================================="
echo "🎉 部署完成！"
echo ""
echo "📋 接下来请完成以下配置:"
echo "  1. 编辑 config.yaml 填写 DeepSeek API Key"
echo "     获取地址: https://platform.deepseek.com"
echo ""
echo "  2. 编辑 config.yaml 填写邮箱SMTP信息"
echo "     QQ邮箱授权码: 设置 → 账户 → POP3/SMTP → 生成授权码"
echo ""
echo "  3. 可选: 在 run.sh 中配置环境变量"
echo ""
echo "📝 手动测试: "
echo "   cd $PROJECT_DIR"
echo "   source venv/bin/activate"
echo "   python main.py --dry-run"
echo ""
echo "📊 查看日志:"
echo "   tail -f $PROJECT_DIR/logs/paper_push.log"
echo ""
echo "⏰ 查看cron任务:"
echo "   crontab -l"
