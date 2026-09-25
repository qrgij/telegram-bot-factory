"""子机器人运行管理：把代码写入磁盘，并以独立子进程方式启动/停止。"""
import os
import signal
import subprocess
import sys
import time

import config
import storage


def bot_dir(username):
    return os.path.join(config.DATA_DIR, "bots", username)


def log_path(username):
    return os.path.join(config.DATA_DIR, "logs", f"{username}.log")


def write_bot_files(username, code):
    d = bot_dir(username)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "bot_main.py"), "w", encoding="utf-8") as f:
        f.write(code)


def is_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    # 僵尸进程（未被回收的已死进程）视为已停止
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            state = f.read().rsplit(")", 1)[-1].split()[0]
            return state != "Z"
    except Exception:
        return True


def start_bot(username):
    """启动子机器人进程，返回 (pid, error)。"""
    rec = storage.get_bot(username)
    if not rec:
        return None, "未找到该机器人"
    if rec["status"] == "running" and is_alive(rec["pid"]):
        return rec["pid"], None  # 已在运行

    os.makedirs(os.path.dirname(log_path(username)), exist_ok=True)
    write_bot_files(username, rec["code"])

    env = {**os.environ, "BOT_TOKEN": rec["token"], "PYTHONUNBUFFERED": "1"}
    with open(log_path(username), "ab") as logf:
        proc = subprocess.Popen(
            [sys.executable, "bot_main.py"],
            cwd=bot_dir(username),
            env=env,
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    storage.update_bot(username, status="running", pid=proc.pid)
    return proc.pid, None


def stop_bot(username):
    """停止子机器人进程：先 SIGTERM 优雅退出，超时后强制 SIGKILL。"""
    rec = storage.get_bot(username)
    if not rec:
        return "未找到该机器人"
    pid = rec.get("pid")
    if pid and is_alive(pid):
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        # 优雅退出窗口约 5 秒（子进程可能卡在断网重连上）
        for _ in range(20):
            time.sleep(0.25)
            if not is_alive(pid):
                break
        if is_alive(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        # 回收子进程，避免残留僵尸
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
    storage.update_bot(username, status="stopped", pid=0)
    return "已停止"


def cleanup_stale():
    """服务重启后，旧的 pid 全部失效，统一标记为 stopped。"""
    for rec in storage.all_bots():
        if rec["status"] == "running":
            storage.update_bot(rec["username"], status="stopped", pid=0)
