"""全局配置：全部从环境变量读取，绝不把密钥写进代码或仓库。"""
import os

# 主机器人（机器人工厂）的 Bot Token —— 必填
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# 可选：BotFather 自动捕获模式使用的监听令牌（实验性，留空则自动捕获关闭）
BOTFATHER_TOKEN = os.environ.get("BOTFATHER_TOKEN", "")

# 部署后的服务地址（网页编辑器调用后端 API 用），例如 https://xxx.onrender.com
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")

# 网页编辑器页面地址（GitHub Pages 托管）
EDITOR_URL = os.environ.get(
    "EDITOR_URL", "https://qrgij.github.io/telegram-bot-factory/editor.html"
)

# HTTP 服务端口（Render 会自动注入 PORT）
PORT = int(os.environ.get("PORT", "8000"))

# 同时允许运行的最多子机器人数量（保护免费实例内存）
MAX_BOTS = int(os.environ.get("MAX_BOTS", "4"))

# 数据目录（SQLite、子机器人代码、日志）
DATA_DIR = os.environ.get(
    "FACTORY_DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
)

# 本地测试模式：跳过 Telegram 连接，只起 HTTP 服务（验证 API 用）
NO_TG = os.environ.get("FACTORY_NO_TG", "") == "1"


def ensure_dirs():
    import os
    for sub in ("", "logs", "bots"):
        os.makedirs(os.path.join(DATA_DIR, sub), exist_ok=True)


if not BOT_TOKEN and not NO_TG:
    raise SystemExit(
        "错误：未设置 BOT_TOKEN 环境变量。\n"
        "部署到 Render 时在环境变量中配置；本地运行请 export BOT_TOKEN=xxx 后重试。"
    )
