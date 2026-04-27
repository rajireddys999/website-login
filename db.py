import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'laxmi_academy.db')

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS students (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name   TEXT    NOT NULL,
            email       TEXT    UNIQUE NOT NULL,
            phone       TEXT    UNIQUE NOT NULL,
            password    TEXT    NOT NULL,
            course      TEXT    NOT NULL DEFAULT 'Physics Foundation',
            plan        TEXT    NOT NULL DEFAULT '6 Months',
            is_active   INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS admins (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            email       TEXT    UNIQUE NOT NULL,
            password    TEXT    NOT NULL,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            token       TEXT    UNIQUE NOT NULL,
            user_id     INTEGER NOT NULL,
            role        TEXT    NOT NULL CHECK(role IN ('student','admin')),
            created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            expires_at  TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS enquiries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name   TEXT    NOT NULL,
            email       TEXT,
            phone       TEXT,
            course      TEXT,
            message     TEXT,
            status      TEXT    NOT NULL DEFAULT 'new',
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
        CREATE INDEX IF NOT EXISTS idx_students_email ON students(email);
        CREATE INDEX IF NOT EXISTS idx_students_phone ON students(phone);
    """)

    conn.commit()
    conn.close()
    print("  [OK] Tables created: students, admins, sessions, enquiries")
