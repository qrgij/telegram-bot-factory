"""机器人工厂主程序：主机器人 + HTTP API（健康检查 / 网页编辑器后端）。

功能：
- 检测用户"想创建机器人"的意图，引导输入名字和用户名
- 通过 BotFather 自动捕获（或手动粘贴 token）创建机器人，保存到 SQLite
- 提供内置功能模板、网页代码编辑器、一键启动/停止子机器人
"""
import asyncio
import logging
import os
import re
import secrets
import time

from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import botfather
import config
import runner
import storage
import templates

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("factory")

# 创建/写码流程状态：chat_id -> {"step":..., "name":..., "username":...}
FLOW = {}

APP_BOT = None  # 主机器人实例（编辑器保存代码后通知用户用）
APP = None      # 主机器人 Application（webhook 处理更新用）

INTENT_RE = re.compile(
    r"(?:创建|新建|做一个|帮我做|帮我建|帮我搞|申请|开一个|整一个|我要做|想做一个|弄一个|需要创建).{0,12}(?:机器人|机器|bot)",
    re.I,
)

EDIT_KEY_HINT = "（编辑密钥在 /key 命令可重新生成；不要把带密钥的链接发给别人）"


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------

def utcnow():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def editor_link(username, key):
    return f"{config.EDITOR_URL}#u={username}&k={key}&api={config.BASE_URL}"


def owner_only(chat_id, rec):
    return rec and rec.get("owner_id") == chat_id


def bot_summary(rec):
    if rec["status"] == "running":
        status = "🟢 运行中" if runner.is_alive(rec.get("pid")) else "💀 已退出（可 /startbot 重启）"
    else:
        status = "⚪ 已停止"
    return (
        f"🤖 {rec['name']}\n"
        f"👤 @{rec['username']}\n"
        f"🧩 功能：{rec['template']}\n"
        f"📊 状态：{status}\n"
        f"🕐 创建于：{rec.get('created_at')}"
    )


def summary_keyboard(username):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🧩 选模板", callback_data=f"tpl:{username}"),
                InlineKeyboardButton("✏️ 网页编辑器", callback_data=f"edit:{username}"),
            ],
            [
                InlineKeyboardButton("▶️ 启动", callback_data=f"start:{username}"),
                InlineKeyboardButton("⏹ 停止", callback_data=f"stop:{username}"),
                InlineKeyboardButton("🗑 删除", callback_data=f"del:{username}"),
            ],
        ]
    )


# --------------------------------------------------------------------------
# 命令处理器
# --------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 我是【机器人工厂】！你可以在我这里创建和管理自己的 Telegram 机器人。\n\n"
        "🆕 创建机器人：直接对我说「创建机器人」，或发送 /newbot\n"
        "　→ 我会引导你输入名字和用户名，并自动对接 @BotFather 完成创建\n\n"
        "其他命令：\n"
        "/newbot - 创建机器人\n"
        "/mybots - 我的机器人列表\n"
        "/template &lt;用户名&gt; - 套用功能模板\n"
        "/code &lt;用户名&gt; - 直接在聊天里粘贴代码\n"
        "/editor &lt;用户名&gt; - 打开网页代码编辑器\n"
        "/startbot &lt;用户名&gt; - 启动机器人\n"
        "/stopbot &lt;用户名&gt; - 停止机器人\n"
        "/logs &lt;用户名&gt; - 查看运行日志\n"
        "/delbot &lt;用户名&gt; - 删除机器人\n"
        "/token &lt;用户名&gt; - 查看 Token\n"
        "/key &lt;用户名&gt; - 重新生成编辑密钥\n"
        "/cancel - 取消当前操作\n"
        "/help - 帮助"
    )


cmd_help = cmd_start


async def cmd_newbot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args or []
    if len(args) >= 2:
        # /newbot 名字 用户名 直接进入
        FLOW[chat_id] = {"step": "await_username", "name": args[0], "username": ""}
        await _ask_username(update, args[0])
        return
    FLOW[chat_id] = {"step": "await_name", "name": "", "username": ""}
    await update.message.reply_text(
        "🆕 好的，开始创建机器人！\n\n"
        "第 1 步：请告诉我机器人的【名字】（显示名称，随便起，例如：我的小助手）"
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    FLOW.pop(chat_id, None)
    botfather.PENDING.pop(chat_id, None)
    await update.message.reply_text("已取消当前操作。")


async def cmd_mybots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    recs = storage.list_bots_by_owner(chat_id)
    if not recs:
        await update.message.reply_text("你还没有创建过机器人。对我说「创建机器人」开始吧！")
        return
    lines = []
    for r in recs:
        if r["status"] == "running":
            st = "🟢" if runner.is_alive(r.get("pid")) else "💀"
        else:
            st = "⚪"
        lines.append(f"{st} @{r['username']}（{r['name']} · {r['template']}）")
    await update.message.reply_text(
        "📋 我的机器人：\n\n" + "\n".join(lines) + "\n\n用 /template、/editor、/startbot 等命令管理对应机器人（命令后跟用户名）。"
    )


async def cmd_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text("用法：/template &lt;机器人用户名&gt;，例如 /template my_fun_bot")
        return
    username = args[0].lstrip("@")
    rec = storage.get_bot(username)
    if not owner_only(chat_id, rec):
        await update.message.reply_text("未找到该机器人，或它不是你的。")
        return
    await _send_template_picker(update, username)


async def _send_template_picker(update_or_query, username):
    buttons = [
        [InlineKeyboardButton(f"{k}：{v['desc']}", callback_data=f"tplset:{username}:{k}")]
        for k, v in templates.TEMPLATES.items()
    ]
    kb = InlineKeyboardMarkup(buttons)
    target = getattr(update_or_query, "message", None) or update_or_query.effective_chat
    await target.send_message(f"🧩 为 @{username} 选择一个功能模板：", reply_markup=kb)


async def cmd_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text("用法：/code &lt;机器人用户名&gt;，例如 /code my_fun_bot")
        return
    username = args[0].lstrip("@")
    rec = storage.get_bot(username)
    if not owner_only(chat_id, rec):
        await update.message.reply_text("未找到该机器人，或它不是你的。")
        return
    FLOW[chat_id] = {"step": "await_code", "username": username}
    await update.message.reply_text(
        f"📝 请把 @{username} 的完整 Python 代码发给我。\n\n"
        "代码要求（python-telegram-bot v21）：\n"
        "• 用 os.environ['BOT_TOKEN'] 读取自己的令牌\n"
        "• 最后调用 app.run_polling()\n"
        "• 建议先 /template 选个模板，再在它基础上改\n\n"
        "发送 /cancel 可取消。"
    )


async def cmd_editor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text("用法：/editor &lt;机器人用户名&gt;")
        return
    username = args[0].lstrip("@")
    rec = storage.get_bot(username)
    if not owner_only(chat_id, rec):
        await update.message.reply_text("未找到该机器人，或它不是你的。")
        return
    link = editor_link(username, rec["edit_key"])
    await update.message.reply_text(
        f"✏️ 打开网页编辑器编写 @{username} 的代码：\n{link}\n\n{EDIT_KEY_HINT}",
        disable_web_page_preview=True,
    )


async def cmd_startbot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text("用法：/startbot &lt;机器人用户名&gt;")
        return
    username = args[0].lstrip("@")
    rec = storage.get_bot(username)
    if not owner_only(chat_id, rec):
        await update.message.reply_text("未找到该机器人，或它不是你的。")
        return
    running = [r for r in storage.all_bots() if r["status"] == "running"]
    if len(running) >= config.MAX_BOTS:
        await update.message.reply_text(f"⚠️ 同时运行的机器人已达上限（{config.MAX_BOTS} 个）。请先停止其他机器人。")
        return
    pid, err = runner.start_bot(username)
    if err:
        await update.message.reply_text(f"❌ {err}")
        return
    await update.message.reply_text(f"✅ @{username} 已启动（PID {pid}）。运行日志可用 /logs {username} 查看。")


async def cmd_stopbot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text("用法：/stopbot &lt;机器人用户名&gt;")
        return
    username = args[0].lstrip("@")
    rec = storage.get_bot(username)
    if not owner_only(chat_id, rec):
        await update.message.reply_text("未找到该机器人，或它不是你的。")
        return
    msg = runner.stop_bot(username)
    await update.message.reply_text(f"⏹ @{username} {msg}。")


async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text("用法：/logs &lt;机器人用户名&gt;")
        return
    username = args[0].lstrip("@")
    rec = storage.get_bot(username)
    if not owner_only(chat_id, rec):
        await update.message.reply_text("未找到该机器人，或它不是你的。")
        return
    path = runner.log_path(username)
    if not os.path.exists(path):
        await update.message.reply_text("暂无日志（机器人可能还没运行过）。")
        return
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()[-3000:]
    await update.message.reply_text(f"📄 @{username} 最近日志：\n\n{content or '（空）'}")


async def cmd_delbot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text("用法：/delbot &lt;机器人用户名&gt;")
        return
    username = args[0].lstrip("@")
    rec = storage.get_bot(username)
    if not owner_only(chat_id, rec):
        await update.message.reply_text("未找到该机器人，或它不是你的。")
        return
    await update.message.reply_text(
        f"⚠️ 确认删除 @{username}？删除后平台上的代码和记录将清空。\n"
        "（如需释放该用户名，还需你本人在 @BotFather 里对它发送 /deletebot）",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("确认删除", callback_data=f"del_yes:{username}")]]
        ),
    )


async def cmd_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text("用法：/token &lt;机器人用户名&gt;")
        return
    username = args[0].lstrip("@")
    rec = storage.get_bot(username)
    if not owner_only(chat_id, rec):
        await update.message.reply_text("未找到该机器人，或它不是你的。")
        return
    await update.message.reply_text(
        f"🔑 @{username} 的 Token：\n<code>{rec['token']}</code>\n\n"
        "请务必保密：任何人拿到它都能完全控制这个机器人。",
        parse_mode="HTML",
    )


async def cmd_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text("用法：/key &lt;机器人用户名&gt;")
        return
    username = args[0].lstrip("@")
    rec = storage.get_bot(username)
    if not owner_only(chat_id, rec):
        await update.message.reply_text("未找到该机器人，或它不是你的。")
        return
    new_key = secrets.token_urlsafe(16)
    storage.update_bot(username, edit_key=new_key)
    link = editor_link(username, new_key)
    await update.message.reply_text(
        f"🔐 已重新生成 @{username} 的编辑密钥，新的编辑器链接：\n{link}\n\n{EDIT_KEY_HINT}",
        disable_web_page_preview=True,
    )


# --------------------------------------------------------------------------
# 文本消息处理（流程状态机 + 意图检测 + token 粘贴）
# --------------------------------------------------------------------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    step = FLOW.get(chat_id, {}).get("step")

    if step == "await_name":
        FLOW[chat_id]["name"] = text[:64]
        await _ask_username(update, text[:64])
        return

    if step == "await_username":
        await _handle_username(update, text)
        return

    if step == "await_token":
        tok = botfather.extract_token(text)
        if tok:
            await _complete_by_token(chat_id, tok)
        else:
            await update.message.reply_text(
                "没有识别到 token（形如 123456789:AAxxxxxxxx）。请把 @BotFather 回复的整段文字复制给我，或发送 /cancel。"
            )
        return

    if step == "await_code":
        await _handle_code(chat_id, update, text)
        return

    # 无流程时：意图检测
    if INTENT_RE.search(text) or text.lower().startswith("newbot"):
        await cmd_newbot(update, context)
        return

    # 兜底：如果用户正在创建但发来了 token（自动捕获失败的情况）
    tok = botfather.extract_token(text)
    if tok:
        pending = botfather.PENDING.get(chat_id)
        if pending:
            await _complete_by_token(chat_id, tok)
            return


async def _ask_username(update, name):
    chat_id = update.effective_chat.id
    FLOW[chat_id] = {"step": "await_username", "name": name}
    await update.message.reply_text(
        f"✅ 名字：{name}\n\n"
        "第 2 步：请告诉我机器人的【用户名】（@ 后面的部分，创建后不可改）：\n"
        "• 只含英文字母、数字、下划线，5~32 位\n"
        "• 必须以 bot 结尾\n"
        "• 例如：my_fun_bot"
    )


async def _handle_username(update, text):
    chat_id = update.effective_chat.id
    username = text.strip().lstrip("@")
    ok, err = botfather.validate_username(username)
    if not ok:
        await update.message.reply_text(f"❌ {err}\n请重新输入用户名（或 /cancel 放弃）。")
        return
    if storage.username_taken(username):
        await update.message.reply_text("❌ 这个用户名已被本平台创建过。请换一个（或 /cancel 放弃）。")
        return
    name = FLOW[chat_id]["name"]
    user = update.effective_user
    botfather.PENDING[chat_id] = {
        "name": name,
        "username": username,
        "chat_id": chat_id,
        "owner_name": user.username or user.full_name or "",
        "ts": time.time(),
    }
    FLOW[chat_id] = {"step": "await_token", "name": name, "username": username}
    await update.message.reply_text(
        f"👌 都齐了！\n名字：{name}\n用户名：@{username}\n\n"
        "现在请在 Telegram 里打开 @BotFather（如果还没开始过，先点一次 Start），依次发送：\n\n"
        f"1️⃣ /newbot\n2️⃣ {name}\n3️⃣ {username}\n\n"
        "完成后**不用做任何事**——我会自动检测 BotFather 的回复并保存你的新机器人 🤖\n"
        "如果 2 分钟内没自动检测到（自动捕获未开启时），直接把 BotFather 回复里的 token 粘贴给我即可。",
    )


async def _complete_by_token(chat_id, token):
    flow = FLOW.get(chat_id, {})
    name = flow.get("name", "")
    username = flow.get("username", "")
    if not username:
        await factory_bot_send(chat_id, "❌ 请先走 /newbot 流程再粘贴 token。")
        return
    # 验证 token 是否有效（getMe 由远端服务执行）
    from telegram import Bot as TGBot

    try:
        me = await TGBot(token).get_me()
        if not me or not me.username:
            raise ValueError("no username")
    except Exception:
        await factory_bot_send(chat_id, "❌ 这个 token 无效，BotFather 可能还在处理，请稍后重发一次。")
        return
    key = storage.add_bot(
        username, name, token, chat_id,
        flow.get("owner_name", ""), templates.TEMPLATES["echo"]["code"], "echo",
        utcnow(),
    )
    botfather.PENDING.pop(chat_id, None)
    FLOW.pop(chat_id, None)
    if key is None:
        await factory_bot_send(chat_id, f"⚠️ 用户名 @{username} 已经被本平台创建过，请换一个用户名重新创建。")
        return
    await after_bot_created(chat_id, username)


async def _handle_code(chat_id, update, text):
    username = FLOW[chat_id].get("username", "")
    rec = storage.get_bot(username)
    if not owner_only(chat_id, rec):
        await update.message.reply_text("❌ 找不到该机器人。")
        FLOW.pop(chat_id, None)
        return
    if len(text) > 200_000:
        await update.message.reply_text("❌ 代码太长（超过 20 万字符）。")
        return
    try:
        compile(text, f"bot_{username}", "exec")
    except SyntaxError as e:
        line = e.lineno or "?"
        await update.message.reply_text(f"❌ 代码语法错误：第 {line} 行：{e.msg}\n请修改后重新发送（/cancel 放弃）。")
        return
    storage.update_bot(username, code=text, template="custom")
    FLOW.pop(chat_id, None)
    await update.message.reply_text(
        f"✅ 代码已保存到 @{username}（自定义）。\n"
        f"启动：/startbot {username}\n"
        f"网页编辑器：/editor {username}"
    )


# --------------------------------------------------------------------------
# 按钮回调
# --------------------------------------------------------------------------

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data or ""
    action, _, rest = data.partition(":")
    username = rest.split(":")[0] if rest else ""

    if action == "tpl":
        rec = storage.get_bot(username)
        if not owner_only(chat_id, rec):
            return
        await _send_template_picker(query, username)
    elif action == "edit":
        rec = storage.get_bot(username)
        if not owner_only(chat_id, rec):
            return
        link = editor_link(username, rec["edit_key"])
        await query.message.reply_text(
            f"✏️ 网页编辑器：\n{link}\n\n{EDIT_KEY_HINT}", disable_web_page_preview=True
        )
    elif action == "tplset":
        tpl = rest.split(":")[1] if ":" in rest else ""
        rec = storage.get_bot(username)
        if not owner_only(chat_id, rec) or tpl not in templates.TEMPLATES:
            return
        storage.update_bot(username, code=templates.TEMPLATES[tpl]["code"], template=tpl)
        await query.message.reply_text(
            f"✅ 已为 @{username} 套用模板「{templates.TEMPLATES[tpl]['desc']}」。\n"
            f"启动：/startbot {username}；修改：/editor {username}"
        )
    elif action == "start":
        rec = storage.get_bot(username)
        if not owner_only(chat_id, rec):
            return
        running = [r for r in storage.all_bots() if r["status"] == "running"]
        if len(running) >= config.MAX_BOTS:
            await query.message.reply_text(f"⚠️ 同时运行上限 {config.MAX_BOTS} 个，请先停止其他机器人。")
            return
        pid, err = runner.start_bot(username)
        await query.message.reply_text(f"✅ @{username} 已启动（PID {pid}）。日志：/logs {username}" if not err else f"❌ {err}")
    elif action == "stop":
        rec = storage.get_bot(username)
        if not owner_only(chat_id, rec):
            return
        msg = runner.stop_bot(username)
        await query.message.reply_text(f"⏹ @{username} {msg}。")
    elif action == "del":
        rec = storage.get_bot(username)
        if not owner_only(chat_id, rec):
            return
        await query.message.reply_text(
            f"⚠️ 确认删除 @{username}？",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("确认删除", callback_data=f"del_yes:{username}")]]
            ),
        )
    elif action == "del_yes":
        rec = storage.get_bot(username)
        if not owner_only(chat_id, rec):
            return
        runner.stop_bot(username)
        storage.delete_bot(username)
        await query.message.reply_text(
            f"🗑 已删除 @{username} 的平台记录。如需释放用户名，请本人在 @BotFather 里对它发送 /deletebot。"
        )


# --------------------------------------------------------------------------
# 创建完成后的统一收尾
# --------------------------------------------------------------------------

async def factory_bot_send(chat_id, text):
    if APP_BOT:
        try:
            await APP_BOT.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            log.warning("send fail %s: %s", chat_id, e)


async def after_bot_created(chat_id, username):
    """机器人创建成功后：通知用户并展示操作按钮。"""
    rec = storage.get_bot(username)
    if not rec:
        return
    text = (
        "🎉 机器人创建成功！\n\n"
        f"🤖 名称：{rec['name']}\n"
        f"👤 用户名：@{rec['username']}\n"
        f"🔑 Token：<code>{rec['token']}</code>\n\n"
        "Token 请保密（/token 可随时查看）。接下来选个模板或打开网页编辑器写功能，然后一键启动："
    )
    if APP_BOT:
        await APP_BOT.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=summary_keyboard(username),
        )


# --------------------------------------------------------------------------
# HTTP API（健康检查 + 网页编辑器后端）
# --------------------------------------------------------------------------

def _cors_middleware():
    @web.middleware
    async def cors(request, handler):
        resp = await handler(request)
        if request.path.startswith("/api/"):
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    return cors


async def handle_health(request):
    return web.json_response(
        {"ok": True, "service": "telegram-bot-factory", "time": utcnow()}
    )


def _check_key(username, key):
    rec = storage.get_bot(username)
    if not rec or not key:
        return None
    if secrets.compare_digest(rec["edit_key"], key):
        return rec
    return None


async def handle_code(request):
    if request.method == "OPTIONS":
        return web.Response(status=200)
    username = (request.query.get("u") or "").strip()
    key = (request.query.get("k") or "").strip()
    rec = _check_key(username, key)
    if not rec:
        return web.json_response({"ok": False, "error": "用户名或编辑密钥不正确"}, status=403)

    if request.method == "GET":
        return web.json_response(
            {
                "ok": True,
                "name": rec["name"],
                "username": rec["username"],
                "code": rec["code"] or "",
                "template": rec["template"],
            }
        )

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "请求体必须是 JSON"}, status=400)
    code = data.get("code", "")
    if not isinstance(code, str) or len(code) > 200_000:
        return web.json_response({"ok": False, "error": "代码为空或超过 20 万字符"}, status=400)
    try:
        compile(code, f"bot_{rec['username']}", "exec")
    except SyntaxError as e:
        return web.json_response(
            {"ok": False, "error": f"语法错误：第 {e.lineno} 行：{e.msg}"}, status=400
        )
    storage.update_bot(rec["username"], code=code, template="custom")
    asyncio.create_task(
        factory_bot_send(
            rec["owner_id"],
            f"✅ 机器人 @{rec['username']} 的代码已通过网页编辑器保存。\n启动：/startbot {rec['username']}",
        )
    )
    return web.json_response({"ok": True})


async def handle_templates(request):
    return web.json_response(
        {"ok": True, "templates": [{"name": k, "desc": v["desc"]} for k, v in templates.TEMPLATES.items()]}
    )


async def handle_status(request):
    allb = storage.all_bots()
    return web.json_response(
        {
            "ok": True,
            "total_bots": len(allb),
            "running": [b["username"] for b in allb if b["status"] == "running"],
        }
    )


async def handle_options(request):
    return web.Response(status=200)


async def handle_webhook(request):
    """Telegram webhook 入口：接收官方推送的更新并交给主机器人处理。"""
    token = request.match_info.get("token", "")
    if not secrets.compare_digest(token, config.BOT_TOKEN):
        return web.Response(status=404)
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400)
    if APP is None:
        return web.Response(status=503)
    update = Update.de_json(data, APP.bot)
    await APP.process_update(update)
    return web.Response(status=200)


def build_web_app():
    app_ = web.Application(middlewares=[_cors_middleware()])
    app_.router.add_get("/", handle_health)
    app_.router.add_get("/health", handle_health)
    app_.router.add_post("/webhook/{token}", handle_webhook)
    app_.router.add_get("/api/code", handle_code)
    app_.router.add_post("/api/code", handle_code)
    app_.router.add_route("OPTIONS", "/api/code", handle_options)
    app_.router.add_get("/api/templates", handle_templates)
    app_.router.add_get("/api/status", handle_status)
    return app_


async def start_http():
    web_app = build_web_app()
    runner_ = web.AppRunner(web_app)
    await runner_.setup()
    site = web.TCPSite(runner_, host="0.0.0.0", port=config.PORT)
    await site.start()
    log.info("HTTP 服务已启动：0.0.0.0:%s", config.PORT)


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def build_application():
    app = Application.builder().token(config.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("newbot", cmd_newbot))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("mybots", cmd_mybots))
    app.add_handler(CommandHandler("template", cmd_template))
    app.add_handler(CommandHandler("code", cmd_code))
    app.add_handler(CommandHandler("editor", cmd_editor))
    app.add_handler(CommandHandler("startbot", cmd_startbot))
    app.add_handler(CommandHandler("stopbot", cmd_stopbot))
    app.add_handler(CommandHandler("logs", cmd_logs))
    app.add_handler(CommandHandler("delbot", cmd_delbot))
    app.add_handler(CommandHandler("token", cmd_token))
    app.add_handler(CommandHandler("key", cmd_key))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))
    return app


async def main():
    storage.init_db()
    runner.cleanup_stale()

    if config.NO_TG:
        # 本地验证模式：只起 HTTP 服务
        storage.add_bot(
            "test_demo_bot", "测试机器人", "123456789:AAxxxx", 1, "tester",
            templates.TEMPLATES["echo"]["code"], "echo", utcnow(),
        ) if not storage.get_bot("test_demo_bot") else None
        await start_http()
        log.info("NO_TG 模式：仅 HTTP 服务，等待中…")
        await asyncio.Event().wait()
        return

    app = build_application()
    global APP_BOT, APP
    APP_BOT = app.bot
    APP = app
    await app.initialize()
    await app.start()

    if config.BOT_MODE == "webhook":
        if not config.BASE_URL:
            raise SystemExit("BOT_MODE=webhook 需要设置 BASE_URL 环境变量（部署后的服务地址）")
        url = f"{config.BASE_URL}/webhook/{config.BOT_TOKEN}"
        await app.bot.set_webhook(url, allowed_updates=Update.ALL_TYPES)
        me = await app.bot.get_me()
        log.info("主机器人 @%s 已设置 webhook：%s", me.username, url)
    else:
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        me = await app.bot.get_me()
        log.info("主机器人 @%s 已开始轮询", me.username)

    asyncio.create_task(botfather.run_watcher(app.bot))
    await start_http()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
