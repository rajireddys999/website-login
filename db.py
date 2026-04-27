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

        CREATE TABLE IF NOT EXISTS instructors (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            email       TEXT    UNIQUE NOT NULL,
            phone       TEXT,
            password    TEXT    NOT NULL,
            subject     TEXT    NOT NULL DEFAULT 'Physics',
            bio         TEXT,
            is_active   INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS lessons (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            instructor_id   INTEGER NOT NULL,
            topic           TEXT    NOT NULL,
            title           TEXT    NOT NULL,
            description     TEXT,
            video_type      TEXT    NOT NULL DEFAULT 'youtube',
            video_url       TEXT    NOT NULL,
            duration        TEXT,
            order_num       INTEGER NOT NULL DEFAULT 0,
            is_published    INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (instructor_id) REFERENCES instructors(id) ON DELETE CASCADE
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

        CREATE INDEX IF NOT EXISTS idx_students_email    ON students(email);
        CREATE INDEX IF NOT EXISTS idx_students_phone    ON students(phone);
        CREATE INDEX IF NOT EXISTS idx_instructors_email ON instructors(email);
        CREATE INDEX IF NOT EXISTS idx_lessons_topic     ON lessons(topic);
        CREATE INDEX IF NOT EXISTS idx_lessons_instructor ON lessons(instructor_id);
    """)

    # Migrate sessions table to support instructor role if needed
    _migrate_sessions(conn)

    _migrate_lessons_course(conn)
    conn.commit()
    conn.close()
    print("  [OK] Tables ready: students, admins, instructors, sessions, lessons, enquiries")

def _migrate_lessons_course(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(lessons)").fetchall()]
    if 'course' not in cols:
        conn.execute("ALTER TABLE lessons ADD COLUMN course TEXT NOT NULL DEFAULT 'all'")
        print("  [OK] lessons.course column added")

def _migrate_sessions(conn):
    # Check if sessions table exists with old constraint (student|admin only)
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='sessions'"
    ).fetchone()

    if row is None:
        # Create fresh with all 3 roles
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                token       TEXT    UNIQUE NOT NULL,
                user_id     INTEGER NOT NULL,
                role        TEXT    NOT NULL,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                expires_at  TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
        """)
    elif 'instructor' not in (row['sql'] or ''):
        # Old table exists without instructor — recreate it
        conn.executescript("""
            CREATE TABLE sessions_new (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                token       TEXT    UNIQUE NOT NULL,
                user_id     INTEGER NOT NULL,
                role        TEXT    NOT NULL,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                expires_at  TEXT    NOT NULL
            );
            INSERT OR IGNORE INTO sessions_new
                SELECT id, token, user_id, role, created_at, expires_at FROM sessions;
            DROP TABLE sessions;
            ALTER TABLE sessions_new RENAME TO sessions;
            CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
        """)
        print("  [OK] Sessions table migrated to support instructor role")
