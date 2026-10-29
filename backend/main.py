import os
import sqlite3
from fastapi import FastAPI, HTTPException, Request
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.auth.transport import requests
from google.oauth2 import id_token
from pydantic import BaseModel

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
if not CLIENT_ID:
    raise RuntimeError("請在後端 .env 設定 GOOGLE_CLIENT_ID")

DB_PATH = Path(os.getenv("DATABASE_PATH", "app.db"))
if not DB_PATH.is_absolute():
    DB_PATH = Path(__file__).resolve().parent / DB_PATH

app = FastAPI()
SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    raise RuntimeError("請在後端 .env 設定 SESSION_SECRET")

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    max_age=86400,       # 24 小時
    same_site="lax",
    https_only=False,    # 僅供目前 localhost 的 HTTP 測試
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = connect_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS login_users (
                id INTEGER PRIMARY KEY,
                email TEXT,
                name TEXT
            );

            CREATE TABLE IF NOT EXISTS login_identities (
                provider TEXT NOT NULL,
                provider_sub TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (provider, provider_sub),
                FOREIGN KEY (user_id) REFERENCES login_users(id)
            );
        """)
        conn.commit()
    finally:
        conn.close()


init_db()


class GoogleLoginRequest(BaseModel):
    credential: str


@app.post("/api/auth/google")
def google_login(body: GoogleLoginRequest, request: Request):
    try:
        info = id_token.verify_oauth2_token(
            body.credential,
            requests.Request(),
            CLIENT_ID,
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Google 憑證無效")

    conn = connect_db()
    try:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            """
            SELECT user_id
            FROM login_identities
            WHERE provider = ? AND provider_sub = ?
            """,
            ("google", info["sub"]),
        ).fetchone()

        if row:
            # 這個 Google 帳號以前登入過
            user_id = row[0]
        else:
            # 第一次登入：建立網站使用者
            cursor = conn.execute(
                "INSERT INTO login_users (email, name) VALUES (?, ?)",
                (info.get("email"), info.get("name")),
            )
            user_id = cursor.lastrowid

            conn.execute(
                """
                INSERT INTO login_identities
                    (provider, provider_sub, user_id)
                VALUES (?, ?, ?)
                """,
                ("google", info["sub"], user_id),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    request.session.clear()
    request.session["user_id"] = user_id
    return {
        "verified": True,
        "user_id": user_id,
        "email": info.get("email"),
        "name": info.get("name"),
    }
@app.get("/api/me")
def get_me(request: Request):
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="尚未登入")

    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT id, email, name FROM login_users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(status_code=401, detail="找不到使用者")

    return {"user_id": row[0], "email": row[1], "name": row[2]}


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"message": "已登出"}