import os
import pymysql
from contextlib import contextmanager

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "Xyz1343!!!"),  # besser via .env
    "database": os.getenv("DB_NAME", "ticketsystemabkoo1"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": False,
}

@contextmanager
def get_conn():
    conn = pymysql.connect(**DB_CONFIG)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def query_fetchall(sql: str, params: tuple = ()):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

def query_execute(sql: str, params: tuple = ()):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return getattr(cur, "lastrowid", 0) or 0
