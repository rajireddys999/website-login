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

        CREATE TABLE IF NOT EXISTS payments (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id               INTEGER NOT NULL,
            merchant_transaction_id  TEXT    UNIQUE NOT NULL,
            amount                   INTEGER NOT NULL,
            status                   TEXT    NOT NULL DEFAULT 'pending',
            phonepe_response         TEXT,
            created_at               TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at               TEXT    NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_students_email    ON students(email);
        CREATE INDEX IF NOT EXISTS idx_students_phone    ON students(phone);
        CREATE INDEX IF NOT EXISTS idx_instructors_email ON instructors(email);
        CREATE INDEX IF NOT EXISTS idx_lessons_topic     ON lessons(topic);
        CREATE INDEX IF NOT EXISTS idx_lessons_instructor ON lessons(instructor_id);
        CREATE INDEX IF NOT EXISTS idx_payments_txn      ON payments(merchant_transaction_id);
        CREATE INDEX IF NOT EXISTS idx_payments_student  ON payments(student_id);
    """)

    # Migrate sessions table to support instructor role if needed
    _migrate_sessions(conn)

    _migrate_payment_status(conn)
    _migrate_lessons_course(conn)
    _migrate_email_verification(conn)
    _migrate_password_resets(conn)
    _migrate_lesson_progress(conn)
    _migrate_enrollments(conn)
    conn.commit()
    conn.close()
    print("  [OK] Tables ready: students, admins, instructors, sessions, lessons, enquiries, password_resets, lesson_progress, course_enrollments, course_pricing")

def _migrate_payment_status(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(students)").fetchall()]
    if 'payment_status' not in cols:
        conn.execute("ALTER TABLE students ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'paid'")
        print("  [OK] students.payment_status column added")

def _migrate_lessons_course(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(lessons)").fetchall()]
    if 'course' not in cols:
        conn.execute("ALTER TABLE lessons ADD COLUMN course TEXT NOT NULL DEFAULT 'all'")
        print("  [OK] lessons.course column added")

def _migrate_password_resets(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS password_resets (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            token      TEXT    UNIQUE NOT NULL,
            expires_at TEXT    NOT NULL,
            used       INTEGER NOT NULL DEFAULT 0,
            created_at TEXT    NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_pr_token   ON password_resets(token);
        CREATE INDEX IF NOT EXISTS idx_pr_student ON password_resets(student_id);
    """)

def _migrate_lesson_progress(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS lesson_progress (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id      INTEGER NOT NULL,
            lesson_id       INTEGER NOT NULL,
            watched         INTEGER NOT NULL DEFAULT 0,
            completed       INTEGER NOT NULL DEFAULT 0,
            watched_seconds INTEGER NOT NULL DEFAULT 0,
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE(student_id, lesson_id),
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY (lesson_id)  REFERENCES lessons(id)  ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_lp_student ON lesson_progress(student_id);
        CREATE INDEX IF NOT EXISTS idx_lp_lesson  ON lesson_progress(lesson_id);
    """)

def _migrate_email_verification(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(students)").fetchall()]
    if 'email_verified' not in cols:
        conn.execute("ALTER TABLE students ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
        # Mark existing students as already verified so they aren't locked out
        conn.execute("UPDATE students SET email_verified = 1")
        print("  [OK] students.email_verified column added")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS email_verifications (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            token      TEXT    UNIQUE NOT NULL,
            expires_at TEXT    NOT NULL,
            used       INTEGER NOT NULL DEFAULT 0,
            created_at TEXT    NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_ev_token      ON email_verifications(token);
        CREATE INDEX IF NOT EXISTS idx_ev_student    ON email_verifications(student_id);
    """)

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

def _migrate_enrollments(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS course_pricing (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            course      TEXT    NOT NULL,
            plan        TEXT    NOT NULL,
            amount      INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE(course, plan)
        );

        CREATE TABLE IF NOT EXISTS course_enrollments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id  INTEGER NOT NULL,
            course      TEXT    NOT NULL,
            plan        TEXT    NOT NULL DEFAULT '6 Months',
            amount      INTEGER NOT NULL DEFAULT 0,
            status      TEXT    NOT NULL DEFAULT 'active',
            enrolled_at TEXT    NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_ce_student ON course_enrollments(student_id);
        CREATE INDEX IF NOT EXISTS idx_ce_course  ON course_enrollments(course);
    """)

    # Seed default pricing if empty
    count = conn.execute("SELECT COUNT(*) FROM course_pricing").fetchone()[0]
    if count == 0:
        defaults = [
            ('Physics Foundation', '1 Month',  2500),
            ('Physics Foundation', '3 Months', 6500),
            ('Physics Foundation', '6 Months',   99),
            ('Physics Foundation', '12 Months',18000),
            ('JEE Mains',          '1 Month',  3000),
            ('JEE Mains',          '3 Months', 8000),
            ('JEE Mains',          '6 Months',   99),
            ('JEE Mains',          '12 Months',22000),
            ('JEE Advanced',       '1 Month',  3500),
            ('JEE Advanced',       '3 Months', 9500),
            ('JEE Advanced',       '6 Months',   99),
            ('JEE Advanced',       '12 Months',26000),
            ('NEET',               '1 Month',  3000),
            ('NEET',               '3 Months', 8000),
            ('NEET',               '6 Months',   99),
            ('NEET',               '12 Months',22000),
            ('EAMCET',             '1 Month',  2500),
            ('EAMCET',             '3 Months', 6500),
            ('EAMCET',             '6 Months',   99),
            ('EAMCET',             '12 Months',18000),
            ('Class 11 Physics',   '1 Month',  2000),
            ('Class 11 Physics',   '3 Months', 5500),
            ('Class 11 Physics',   '6 Months',   99),
            ('Class 11 Physics',   '12 Months',15000),
            ('Class 12 Physics',   '1 Month',  2000),
            ('Class 12 Physics',   '3 Months', 5500),
            ('Class 12 Physics',   '6 Months',   99),
            ('Class 12 Physics',   '12 Months',15000),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO course_pricing (course, plan, amount) VALUES (?,?,?)",
            defaults
        )
        print("  [OK] Default course pricing seeded")
    else:
        # Sync 6-Month to ₹99 and restore 1-Month to original prices
        conn.executescript("""
            UPDATE course_pricing SET amount = 99 WHERE plan = '6 Months';
            UPDATE course_pricing SET amount = 2500 WHERE plan = '1 Month' AND course IN ('Physics Foundation','EAMCET');
            UPDATE course_pricing SET amount = 3000 WHERE plan = '1 Month' AND course IN ('JEE Mains','NEET');
            UPDATE course_pricing SET amount = 3500 WHERE plan = '1 Month' AND course = 'JEE Advanced';
            UPDATE course_pricing SET amount = 2000 WHERE plan = '1 Month' AND course IN ('Class 11 Physics','Class 12 Physics');
        """)
        print("  [OK] 6-Month pricing synced to ₹99")

    # Migrate existing students into course_enrollments if not already there
    students = conn.execute("SELECT id, course, plan FROM students").fetchall()
    for s in students:
        existing = conn.execute(
            "SELECT id FROM course_enrollments WHERE student_id=? AND course=?",
            (s['id'], s['course'])
        ).fetchone()
        if not existing and s['course']:
            pricing = conn.execute(
                "SELECT amount FROM course_pricing WHERE course=? AND plan=?",
                (s['course'], s['plan'])
            ).fetchone()
            amount = pricing['amount'] if pricing else 0
            conn.execute(
                "INSERT INTO course_enrollments (student_id, course, plan, amount) VALUES (?,?,?,?)",
                (s['id'], s['course'], s['plan'], amount)
            )
