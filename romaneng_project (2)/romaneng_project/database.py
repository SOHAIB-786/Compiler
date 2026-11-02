"""
DATABASE FILE - SQL Server 2022 (pyodbc)
Tables:  Users, LoginLog, CompileHistory
"""
import re
from contextlib import contextmanager

import pyodbc
from werkzeug.security import generate_password_hash

import config


# ───────────── connection ─────────────
def _driver():
    found = [d for d in pyodbc.drivers() if "SQL Server" in d]
    new = [d for d in found if "ODBC Driver" in d]
    if new:  # newest "ODBC Driver NN for SQL Server"
        return sorted(new, key=lambda d: int(re.search(r"(\d+)", d).group(1)))[-1]
    if found:
        return found[-1]
    raise RuntimeError("No SQL Server ODBC driver found. "
                       "Install 'ODBC Driver 18 for SQL Server' from the Microsoft website.")


def _conn_str(database):
    drv = _driver()
    s = f"DRIVER={{{drv}}};SERVER={config.DB_SERVER};DATABASE={database};"
    if config.DB_USER:
        s += f"UID={config.DB_USER};PWD={config.DB_PASSWORD};"
    else:
        s += "Trusted_Connection=yes;"
    if "ODBC Driver" in drv:
        s += "Encrypt=yes;TrustServerCertificate=yes;"
    return s


@contextmanager
def connect(use_db=True, autocommit=False):
    conn = pyodbc.connect(_conn_str(config.DB_NAME if use_db else "master"),
                          autocommit=autocommit, timeout=5)
    try:
        yield conn
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()


# ───────────── setup (database + tables + default user) ─────────────
TABLES = [
    """IF OBJECT_ID(N'dbo.Users', N'U') IS NULL
       CREATE TABLE dbo.Users (
           id            INT IDENTITY(1,1) PRIMARY KEY,
           username      NVARCHAR(50)  NOT NULL UNIQUE,
           password_hash NVARCHAR(255) NOT NULL,
           created_at    DATETIME2     NOT NULL DEFAULT SYSDATETIME())""",
    """IF OBJECT_ID(N'dbo.LoginLog', N'U') IS NULL
       CREATE TABLE dbo.LoginLog (
           id         INT IDENTITY(1,1) PRIMARY KEY,
           username   NVARCHAR(50)  NULL,
           ip         NVARCHAR(64)  NULL,
           success    BIT           NOT NULL,
           created_at DATETIME2     NOT NULL DEFAULT SYSDATETIME())""",
    """IF OBJECT_ID(N'dbo.CompileHistory', N'U') IS NULL
       CREATE TABLE dbo.CompileHistory (
           id         INT IDENTITY(1,1) PRIMARY KEY,
           user_id    INT           NOT NULL REFERENCES dbo.Users(id),
           source     NVARCHAR(MAX) NOT NULL,
           status     NVARCHAR(20)  NOT NULL,
           created_at DATETIME2     NOT NULL DEFAULT SYSDATETIME())""",
]


def init_db():
    with connect(use_db=False, autocommit=True) as c:
        c.execute(f"IF DB_ID(N'{config.DB_NAME}') IS NULL CREATE DATABASE [{config.DB_NAME}]")
    with connect() as c:
        cur = c.cursor()
        for sql in TABLES:
            cur.execute(sql)
        cur.execute("SELECT 1 FROM dbo.Users WHERE username = ?", config.DEFAULT_USERNAME)
        if not cur.fetchone():
            cur.execute("INSERT INTO dbo.Users (username, password_hash) VALUES (?, ?)",
                        config.DEFAULT_USERNAME, generate_password_hash(config.DEFAULT_PASSWORD))


# ───────────── users / login log ─────────────
def get_user(username):
    with connect() as c:
        row = c.cursor().execute(
            "SELECT id, username, password_hash FROM dbo.Users WHERE username = ?", username).fetchone()
    return {"id": row[0], "username": row[1], "password_hash": row[2]} if row else None


def create_user(username, password_hash):
    """Create a user. Returns None if the username already exists."""
    if get_user(username):
        return None
    try:
        with connect() as c:
            c.cursor().execute("INSERT INTO dbo.Users (username, password_hash) VALUES (?, ?)",
                               username, password_hash)
    except pyodbc.IntegrityError:
        return None
    return get_user(username)["id"]


def log_login(username, ip, success):
    with connect() as c:
        c.cursor().execute("INSERT INTO dbo.LoginLog (username, ip, success) VALUES (?, ?, ?)",
                           (username or "")[:50], (ip or "")[:64], 1 if success else 0)


def recent_failures(ip, seconds):
    with connect() as c:
        return c.cursor().execute(
            "SELECT COUNT(*) FROM dbo.LoginLog WHERE ip = ? AND success = 0 "
            "AND created_at > DATEADD(SECOND, ?, SYSDATETIME())", ip or "", -int(seconds)).fetchone()[0]


# ───────────── compile history ─────────────
def save_history(user_id, source, status):
    with connect() as c:
        c.cursor().execute("INSERT INTO dbo.CompileHistory (user_id, source, status) VALUES (?, ?, ?)",
                           user_id, source, status)


def get_history(user_id, limit=20):
    with connect() as c:
        rows = c.cursor().execute(
            f"SELECT TOP {int(limit)} id, source, status, created_at FROM dbo.CompileHistory "
            "WHERE user_id = ? ORDER BY id DESC", user_id).fetchall()
    return [{"id": r[0], "source": r[1], "status": r[2], "time": r[3].strftime("%d-%b-%Y %H:%M")} for r in rows]


def clear_history(user_id):
    with connect() as c:
        c.cursor().execute("DELETE FROM dbo.CompileHistory WHERE user_id = ?", user_id)
