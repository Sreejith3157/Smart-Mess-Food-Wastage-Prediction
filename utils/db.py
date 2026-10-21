"""SQLite persistence: users and prediction history."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from werkzeug.security import generate_password_hash

from .schema import DB_PATH, OUTPUT_DIR

PRED_COLUMNS = [
    "id", "created_at", "created_by", "meal_date", "meal_type", "day_type", "menu_type",
    "students_present", "food_prepared_kg", "predicted_wastage_kg", "est_consumption_kg",
    "wastage_pct", "recommendation", "notes", "model_trained_at", "dataset_source",
]


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables and seed the first admin user. Returns True if a default
    account was created (so the caller can warn about the password)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    created_default = False
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            meal_date TEXT NOT NULL,
            meal_type TEXT NOT NULL,
            day_type TEXT NOT NULL,
            menu_type TEXT NOT NULL,
            students_present INTEGER NOT NULL,
            food_prepared_kg REAL NOT NULL,
            predicted_wastage_kg REAL NOT NULL,
            est_consumption_kg REAL NOT NULL,
            wastage_pct REAL NOT NULL,
            recommendation TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            model_trained_at TEXT,
            dataset_source TEXT)""")
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            username = os.environ.get("ADMIN_USERNAME", "admin")
            password = os.environ.get("ADMIN_PASSWORD", "admin123")
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, generate_password_hash(password, method="pbkdf2:sha256"),
                 datetime.now().isoformat(timespec="seconds")))
            created_default = "ADMIN_PASSWORD" not in os.environ
    return created_default


def get_user(username):
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def add_prediction(rec):
    cols = [c for c in PRED_COLUMNS if c != "id"]
    rec = dict(rec, created_at=datetime.now().isoformat(timespec="seconds"))
    with connect() as conn:
        cur = conn.execute(
            f"INSERT INTO predictions ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [rec.get(c) for c in cols])
        return cur.lastrowid


def get_prediction(pred_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM predictions WHERE id = ?", (pred_id,)).fetchone()
    return dict(row) if row else None


def list_predictions(limit=None):
    sql = "SELECT * FROM predictions ORDER BY id DESC"
    params = ()
    if limit:
        sql += " LIMIT ?"
        params = (int(limit),)
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def prediction_stats():
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, AVG(wastage_pct) AS avg_pct, SUM(predicted_wastage_kg) AS total_kg, "
            "AVG(predicted_wastage_kg) AS avg_kg FROM predictions").fetchone()
    return {"count": row["n"], "avg_pct": row["avg_pct"], "total_kg": row["total_kg"],
            "avg_kg": row["avg_kg"]}
