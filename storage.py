"""SQLite 存储：机器人记录的新增/查询/更新/删除。"""
import os
import sqlite3
import threading
import secrets

import config

_LOCK = threading.Lock()
DB_PATH = os.path.join(config.DATA_DIR, "factory.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bots (
    username    TEXT PRIMARY KEY,     -- @用户名（唯一）
    name        TEXT,                 -- 显示名字
    token       TEXT,                 -- 该机器人的 Bot Token
    owner_id    INTEGER,              -- 创建者 Telegram user id
    owner_name  TEXT,
    created_at  TEXT,
    code        TEXT,                 -- 当前运行的代码（完整程序）
    template    TEXT,                 -- 使用的模板名 / custom
    edit_key    TEXT,                 -- 网页编辑器编辑密钥
    status      TEXT DEFAULT 'stopped',  -- stopped | running
    pid         INTEGER DEFAULT 0,
    updated_at  TEXT
);
"""


def _conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    config.ensure_dirs()
    with _LOCK:
        conn = _conn()
        conn.execute(_SCHEMA)
        conn.commit()
        conn.close()


def _row_to_dict(row):
    return dict(row) if row else None


def add_bot(username, name, token, owner_id, owner_name, code, template, created_at):
    key = secrets.token_urlsafe(16)
    with _LOCK:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO bots (username,name,token,owner_id,owner_name,created_at,code,template,edit_key,status,pid,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (username, name, token, owner_id, owner_name, created_at, code, template,
                 key, "stopped", 0, created_at),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return None  # 用户名已存在
        finally:
            conn.close()
    return key


def get_bot(username):
    with _LOCK:
        conn = _conn()
        row = conn.execute("SELECT * FROM bots WHERE username=?", (username,)).fetchone()
        conn.close()
    return _row_to_dict(row)


def get_bot_by_token(token):
    with _LOCK:
        conn = _conn()
        row = conn.execute("SELECT * FROM bots WHERE token=?", (token,)).fetchone()
        conn.close()
    return _row_to_dict(row)


def list_bots_by_owner(owner_id):
    with _LOCK:
        conn = _conn()
        rows = conn.execute(
            "SELECT * FROM bots WHERE owner_id=? ORDER BY created_at DESC", (owner_id,)
        ).fetchall()
        conn.close()
    return [_row_to_dict(r) for r in rows]


def all_bots():
    with _LOCK:
        conn = _conn()
        rows = conn.execute("SELECT * FROM bots").fetchall()
        conn.close()
    return [_row_to_dict(r) for r in rows]


def update_bot(username, **fields):
    if not fields:
        return
    fields["updated_at"] = _now()
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [username]
    with _LOCK:
        conn = _conn()
        conn.execute(f"UPDATE bots SET {sets} WHERE username=?", vals)
        conn.commit()
        conn.close()


def delete_bot(username):
    with _LOCK:
        conn = _conn()
        conn.execute("DELETE FROM bots WHERE username=?", (username,))
        conn.commit()
        conn.close()


def username_taken(username):
    with _LOCK:
        conn = _conn()
        row = conn.execute("SELECT 1 FROM bots WHERE username=?", (username,)).fetchone()
        conn.close()
    return row is not None


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
