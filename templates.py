"""内置机器人模板：每个模板都是一份完整、可独立运行的 python-telegram-bot v21 程序。

模板程序通过环境变量 BOT_TOKEN 读取自己的令牌，由 runner 模块写入
data/bots/<用户名>/bot_main.py 后以子进程方式运行。
"""

ECHO = r'''"""复读机：你发什么，它回什么。"""
import logging
import os

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
TOKEN = os.environ["BOT_TOKEN"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 我是复读机：直接把想说的话发给我，我会原样回给你。")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("直接发消息即可，我会复读。命令：/start /help")


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    await update.message.reply_text(text)


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
'''

START_HELP = r'''"""基础信息助手：打招呼 + 查看自己/群聊的信息。"""
import logging
import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
TOKEN = os.environ["BOT_TOKEN"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.full_name or user.username or "朋友"
    await update.message.reply_text(
        f"👋 你好，{name}！\n我是「信息助手」机器人。\n\n"
        "可用命令：\n"
        "/start - 开始\n"
        "/info - 查看对话信息\n"
        "/help - 帮助"
    )


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    text = (
        f"📋 对话信息\n"
        f"对话 ID：{chat.id}\\n"
        f"对话类型：{chat.type}\\n"
        f"你的 ID：{user.id}\\n"
        f"你的用户名：@{user.username if user.username else '未设置'}"
    )
    await update.message.reply_text(text)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("命令：/start /info /help")


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("help", help_cmd))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
'''

QUIZ = r'''"""选择题问答：内置题库 + 行内按钮作答。"""
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
TOKEN = os.environ["BOT_TOKEN"]

QUESTIONS = [
    {
        "q": "世界上面积最大的海洋是？",
        "options": ["大西洋", "印度洋", "太平洋", "北冰洋"],
        "answer": 2,
    },
    {
        "q": "Python 语言的作者是？",
        "options": ["Dennis Ritchie", "Guido van Rossum", "Bjarne Stroustrup", "James Gosling"],
        "answer": 1,
    },
    {
        "q": "太阳系中最大的行星是？",
        "options": ["地球", "木星", "土星", "海王星"],
        "answer": 1,
    },
]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎯 发送 /quiz 开始答题！")


async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["qidx"] = 0
    context.user_data["score"] = 0
    await _send_question(update, context, 0)


async def _send_question(update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int):
    q = QUESTIONS[idx]
    buttons = [
        [InlineKeyboardButton(opt, callback_data=f"ans:{i}")]
        for i, opt in enumerate(q["options"])
    ]
    await update.effective_chat.send_message(
        f"第 {idx + 1}/{len(QUESTIONS)} 题：{q['q']}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = context.user_data.get("qidx", 0)
    choice = int(query.data.split(":")[1])
    q = QUESTIONS[idx]
    if choice == q["answer"]:
        context.user_data["score"] = context.user_data.get("score", 0) + 1
        await query.edit_message_text(f"✅ 回答正确！当前得分 {context.user_data['score']}")
    else:
        await query.edit_message_text(
            f"❌ 回答错误，正确答案是：{q['options'][q['answer']]}（当前得分 {context.user_data.get('score', 0)}）"
        )
    if idx + 1 < len(QUESTIONS):
        context.user_data["qidx"] = idx + 1
        await _send_question(update, context, idx + 1)
    else:
        await update.effective_chat.send_message(
            f"🏁 答题结束！总分：{context.user_data['score']}/{len(QUESTIONS)}"
        )


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("quiz", quiz))
    app.add_handler(CallbackQueryHandler(answer, pattern=r"^ans:"))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
'''

GREET = r'''"""群欢迎：新成员加入时自动欢迎，@机器人进群时打招呼。"""
import logging
import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
TOKEN = os.environ["BOT_TOKEN"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 我是「群欢迎」机器人：把我拉进群并设为管理员，有新成员加入我会自动欢迎。"
    )


async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            await update.message.reply_text("大家好！我是本群新来的机器人 🤖 请把我设为管理员。")
        else:
            name = member.full_name or (f"@{member.username}" if member.username else f"ID {member.id}")
            await update.message.reply_text(f"🎉 欢迎 {name} 加入本群！")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("把机器人拉进群并设为管理员即可，新成员加入会自动欢迎。命令：/start /help")


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
'''

TEMPLATES = {
    "echo": {"desc": "复读机：发什么回什么", "code": ECHO},
    "start": {"desc": "信息助手：打招呼 + 查看对话信息", "code": START_HELP},
    "quiz": {"desc": "选择题问答：行内按钮答题", "code": QUIZ},
    "greet": {"desc": "群欢迎：新成员入群自动欢迎", "code": GREET},
}
