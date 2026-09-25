"""本地自检（不依赖网络）：存储、模板、BotFather 解析、用户名校验。

用法：python selftest.py
"""
import os
import sys
import tempfile

# 隔离数据目录 + 跳过 Telegram 连接，避免污染正式数据
_tmp = tempfile.mkdtemp(prefix="factory_test_")
os.environ["FACTORY_DATA_DIR"] = _tmp
os.environ["FACTORY_NO_TG"] = "1"

import botfather
import storage
import templates


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        sys.exit(1)


def test_storage():
    print("[1] 存储（SQLite 增删改查）")
    storage.init_db()
    key = storage.add_bot("my_demo_bot", "演示", "111:AAA", 42, "alice",
                          "print('hi')", "echo", "2026-01-01 00:00:00")
    check("add_bot 返回编辑密钥", bool(key))
    rec = storage.get_bot("my_demo_bot")
    check("get_bot 字段完整", rec and rec["username"] == "my_demo_bot" and rec["token"] == "111:AAA")
    check("username_taken 生效", storage.username_taken("my_demo_bot"))
    check("重复 add 返回 None", storage.add_bot("my_demo_bot", "x", "1:Y", 42, "a", "c", "echo", "t") is None)
    storage.update_bot("my_demo_bot", code="print('hi2')", template="custom")
    check("update_bot 生效", storage.get_bot("my_demo_bot")["template"] == "custom")
    check("list_by_owner 生效", len(storage.list_bots_by_owner(42)) == 1)
    storage.delete_bot("my_demo_bot")
    check("delete_bot 生效", storage.get_bot("my_demo_bot") is None)


def test_templates():
    print("[2] 模板（全部可编译为完整程序）")
    check("有 4 个模板", len(templates.TEMPLATES) == 4)
    for name, t in templates.TEMPLATES.items():
        compile(t["code"], f"tpl_{name}", "exec")
    check("所有模板 compile 通过", True)
    for name, t in templates.TEMPLATES.items():
        for token in ("app.run_polling", "os.environ", "Application.builder"):
            check(f"{name} 含 {token}", token in t["code"])


def test_botfather_parser():
    print("[3] BotFather 消息解析")
    ok, err = botfather.validate_username("my_fun_bot")
    check("合法用户名 my_fun_bot", ok)
    ok, err = botfather.validate_username("myfunbot")
    check("合法用户名 myfunbot", ok)
    ok, err = botfather.validate_username("abc")
    check("过短用户名被拒", not ok)
    ok, err = botfather.validate_username("1bad_bot")
    check("数字开头被拒", not ok)
    ok, err = botfather.validate_username("my_fun")
    check("不以 bot 结尾被拒", not ok)

    success_msg = (
        "Done! Congratulations on your new bot. You will find it at t.me/new_demo_bot. "
        "You can now add a description, about section and avatar. "
        "Use this token to access the HTTP API:\n"
        "7123456789:AAHabcdefghijklmnopqrstuvwxyz0123456789\n"
        "Keep your token secure, store it safely and do not share it with anyone."
    )
    kind, tok = botfather.parse_reply(success_msg)
    check("成功消息识别", kind == "success" and tok == "7123456789:AAHabcdefghijklmnopqrstuvwxyz0123456789")

    kind, tok = botfather.parse_reply("Sorry, this username is already taken. Please try a different one.")
    check("用户名占用识别", kind == "username_taken")

    kind, tok = botfather.parse_reply("The name must not be longer than 64 characters.")
    check("名字过长识别", kind == "name_invalid")

    check("普通文本无 token", botfather.extract_token("hello world") is None)
    check("token 直接提取", botfather.extract_token("token: 123456:AAabcdefghijklmnopqrstuvwxyz0123456789")
          == "123456:AAabcdefghijklmnopqrstuvwxyz0123456789")


def test_intent():
    print("[4] 创建意图检测")
    import re
    pat = re.compile(
        r"(?:创建|新建|做一个|帮我做|帮我建|帮我搞|申请|开一个|整一个|我要做|想做一个|弄一个|需要创建).{0,12}(?:机器人|机器|bot)",
        re.I,
    )
    for s in ["创建机器人", "帮我做一个机器人", "我要做bot", "需要创建机器人", "申请一个机器人"]:
        check(f"命中意图：{s}", bool(pat.search(s)))
    check("普通消息不误伤", not pat.search("今天天气不错") and not pat.search("机器人真可爱"))


if __name__ == "__main__":
    test_storage()
    test_templates()
    test_botfather_parser()
    test_intent()
    print("\n全部通过 🎉")
