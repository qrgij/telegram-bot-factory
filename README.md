# 🤖 机器人工厂（Telegram Bot Factory）

一个能"造机器人"的 Telegram 机器人：用户说出名字和用户名，平台自动对接
@BotFather 创建新机器人，并提供**功能模板**、**网页代码编辑器**和**一键启动**，
让不会编程的人也能快速拥有自己的 Telegram 机器人。

## 功能

| 能力 | 说明 |
|---|---|
| 🆕 自动创建 | 对机器人说「创建机器人」或 `/newbot`，输入名字和用户名，平台对接 @BotFather 完成创建并**自动捕获 token**（无需复制粘贴） |
| 🧩 内置模板 | 复读机、信息助手、选择题问答、群欢迎，一键套用 |
| ✏️ 网页编辑器 | 在浏览器里写 Python 代码（python-telegram-bot v21），保存后机器人端直接生效 |
| ▶️ 一键启停 | 每个子机器人作为独立进程运行，随时 `/startbot` / `/stopbot` |
| 📊 管理 | 列表、日志、删除、Token 查看、编辑密钥重发 |

## 命令

```
/newbot           开始创建机器人（或直接说「创建机器人」）
/mybots           我的机器人列表
/template <用户名>  套用内置模板
/code <用户名>      在聊天里粘贴完整 Python 代码
/editor <用户名>    打开网页代码编辑器
/startbot <用户名>  启动机器人
/stopbot <用户名>   停止机器人
/logs <用户名>      查看运行日志
/delbot <用户名>    删除机器人
/token <用户名>     查看 Token
/key <用户名>       重新生成编辑密钥
/cancel           取消当前操作
```

## 创建机器人流程

1. 用户对机器人发送「创建机器人」或 `/newbot`
2. 机器人询问【名字】→【用户名】（必须 `bot` 结尾）
3. 用户到 @BotFather 依次发送 `/newbot`、名字、用户名
4. **平台自动检测到 BotFather 的成功回复并保存 token**（`BOTFATHER_TOKEN` 已配置时）；
   未配置时，用户把 BotFather 回复的 token 粘贴给机器人即可
5. 选模板 / 写代码 → `/startbot` 启动 ✅

> 说明：Telegram 平台规定，机器人只能由用户**本人账号**在 @BotFather 里创建，
> 任何程序都无法代替用户操作。因此"自动"体现在：平台自动捕获 token、自动入库、
> 自动提供后续的全部功能，用户无需复制粘贴任何东西。

## 部署（Render）

1. Fork/推送本仓库到你的 GitHub（**密钥一律走环境变量，绝不入库**）
2. Render 新建 Web Service（Public Git Repository → 本仓库）
3. 环境变量：

| 变量 | 必填 | 说明 |
|---|---|---|
| `BOT_TOKEN` | ✅ | 主机器人（机器人工厂）的 token，来自 @BotFather |
| `BASE_URL` | ✅ | 部署后的服务地址，例如 `https://xxx.onrender.com` |
| `BOTFATHER_TOKEN` | ❌ | 可选，开启 BotFather 自动捕获（实验性） |
| `MAX_BOTS` | ❌ | 同时运行子机器人上限，默认 4 |
| `EDITOR_URL` | ❌ | 网页编辑器地址，默认指向本仓库的 GitHub Pages |

4. 免费套餐即可；建议配一个 UptimeRobot 每 5 分钟 ping 保活，避免休眠

## 本地运行

```bash
export BOT_TOKEN=你的token
pip install -r requirements.txt
python factory.py
```

## 安全须知

- **Token 是密码**：`BOT_TOKEN` 与每个子机器人 token 都要保密，不要发给别人、不要入库
- 网页编辑器链接带编辑密钥，不要把带 `k=` 参数的链接公开
- 子机器人代码运行在你自己的服务器上，请只运行你信任的代码；平台不对用户编写的
  代码内容负责，滥用可能导致托管平台封号
- 本项目不提供、也不支持任何"接管他人账号 / 绕过平台规则"类功能

## 自检

```bash
python selftest.py   # 存储、模板、解析器、意图检测（不依赖网络）
```
