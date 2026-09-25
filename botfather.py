"""BotFather 交互模块。

Telegram 规定：机器人只能由用户本人账号在 @BotFather 中创建，任何程序都无法
代替用户操作（除非非法接管账号，本工具不提供）。因此本模块做两件事：

1. 校验用户提供的机器人名字/用户名是否符合规则；
2. 【自动捕获模式】当用户按引导在 @BotFather 里完成创建时，用 BOTFATHER_TOKEN
   监听该用户与 BotFather 的对话，自动提取新机器人的 token 并入库——
   用户无需复制粘贴 token。该模式需要环境变量 BOTFATHER_TOKEN（实验性，
   留空则关闭，走"用户手动粘贴 token"兜底路径）。

隐私说明：监听只处理"正在进行创建的用户的对话"，其他对话一律跳过、不解析。
"""
import asyncio
import logging
import re
import time

from telegram import Bot

import config
import storage

log = logging.getLogger("botfather")

# 进行中的创建请求：user_id -> {"name", "username", "chat_id", "ts"}
PENDING = {}

# BotFather 成功消息里的 token：形如 1234567890:AAHxxxxxxxxxxxxxxxxxxxx
_TOKEN_RE = re.compile(r"\b(\d{6,12}:[A-Za-z0-9_-]{30,60})\b")

_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")

PENDING_TTL = 300  # 秒


def validate_username(username: str):
    """校验机器人用户名，返回 (是否合法, 错误说明)。"""
    username = (username or "").strip().lstrip("@")
    if not _USERNAME_RE.match(username):
        return False, "用户名只能由英文字母、数字、下划线组成，长度 5~32 位，且不能以数字开头。"
    if not username.lower().endswith("bot"):
        return False, "Telegram 要求机器人用户名必须以 bot 结尾（例如 my_fun_bot）。"
    return True, ""


def extract_token(text: str):
    """从文本中提取 BotFather 返回的 token。"""
    if not text:
        return None
    m = _TOKEN_RE.search(text)
    return m.group(1) if m else None


def parse_reply(text: str):
    """解析 BotFather 的回复。

    返回 (kind, token)，kind ∈ success / username_taken / name_invalid / other。
    """
    if not text:
        return "other", None
    tok = extract_token(text)
    if tok or "congratulations on your new bot" in text.lower():
        return "success", tok
    low = text.lower()
    if "already taken" in low or "not available" in low or "sorry, this username" in low:
        return "username_taken", None
    if "too long" in low or "more than 64" in low or "longer than 64" in low or "invalid" in low:
        return "name_invalid", None
    return "other", None


async def run_watcher(factory_bot: Bot):
    """后台任务：监听进行中创建对话，自动捕获 token。"""
    if not config.BOTFATHER_TOKEN:
        log.info("BOTFATHER_TOKEN 未配置，自动捕获模式关闭（走手动粘贴 token 兜底）。")
        return
    try:
        bf = Bot(config.BOTFATHER_TOKEN)
        await bf.get_me()
        log.info("BotFather 自动捕获模式已启动。")
    except Exception as e:
        log.warning("BotFather 令牌不可用，自动捕获模式关闭：%s", e)
        return

    offset = 0
    while True:
        try:
            updates = await bf.get_updates(
                offset=offset, timeout=20, allowed_updates=["message", "edited_message"]
            )
            for u in updates:
                offset = u.update_id + 1
                msg = getattr(u, "message", None) or getattr(u, "edited_message", None)
                if not msg or not getattr(msg, "text", None):
                    continue
                uid = msg.chat_id  # 与 BotFather 的私聊中 chat_id == 用户 id
                pending = PENDING.get(uid)
                if not pending:
                    continue  # 只处理正在创建的用户的对话
                kind, tok = parse_reply(msg.text)
                if kind == "success" and tok:
                    _complete(pending, tok, uid, factory_bot)
                elif kind == "username_taken":
                    _notify(uid, factory_bot,
                            "⚠️ @BotFather 提示该用户名已被占用。请重新输入一个新用户名，或发送 /cancel 放弃。")
                    PENDING.pop(uid, None)
                    _reset_flow(uid)
                elif kind == "name_invalid":
                    _notify(uid, factory_bot,
                            "⚠️ @BotFather 提示名字或用户名不符合要求。名字请控制在 64 字以内，用户名以 bot 结尾。")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("BotFather 监听异常，稍后重试：%s", e)
            await asyncio.sleep(3)
        finally:
            # 过期清理
            now = time.time()
            for uid in [u for u, p in PENDING.items() if now - p.get("ts", 0) > PENDING_TTL]:
                _notify(uid, factory_bot,
                        "⏳ 创建超时（5 分钟未在 @BotFather 中完成）。可以随时再对我说「创建机器人」重新开始，或直接把 BotFather 给的 token 发给我。")
                PENDING.pop(uid, None)
                _reset_flow(uid)


def _complete(pending, token, uid, factory_bot):
    """捕获成功：写入数据库并通知用户。"""
    from factory import after_bot_created  # 延迟导入避免循环依赖

    username, name = pending["username"], pending["name"]
    try:
        key = storage.add_bot(
            username, name, token, uid, pending.get("owner_name", ""),
            "", "echo", time.strftime("%Y-%m-%d %H:%M:%S")
        )
    except Exception as e:
        _notify(uid, factory_bot, f"❌ 保存机器人信息失败：{e}")
        return
    PENDING.pop(uid, None)
    _reset_flow(uid)
    if key is None:
        _notify(uid, factory_bot, f"⚠️ 用户名 @{username} 已经被本平台创建过，请换一个用户名。")
        return
    asyncio.create_task(after_bot_created(uid, username))


def _notify(uid, factory_bot, text):
    try:
        asyncio.create_task(factory_bot.send_message(chat_id=uid, text=text))
    except Exception as e:
        log.warning("通知失败 uid=%s: %s", uid, e)


def _reset_flow(uid):
    """通知 factory 清除该用户的内存状态机。"""
    from factory import FLOW  # 延迟导入
    FLOW.pop(uid, None)
