import os, re, bcrypt
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get('DATABASE_URL', '')

# ── Compatibility layer ────────────────────────────────────────────────────
# Makes psycopg2 behave like sqlite3 so server.py needs no query changes.

class _Row(dict):
    """dict that also supports integer index access (sqlite3.Row compat)."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class _Cursor:
    def __init__(self, cur, is_insert=False):
        self._c, self._is_insert, self._lid = cur, is_insert, None

    def fetchone(self):
        row = self._c.fetchone()
        return _Row(row) if row else None

    def fetchall(self):
        return [_Row(r) for r in (self._c.fetchall() or [])]

    @property
    def lastrowid(self):
        if self._lid is None:
            row = self._c.fetchone()
            self._lid = int(row['id']) if row else None
        return self._lid

    def __iter__(self):
        for row in self._c:
            yield _Row(row)

    def __getitem__(self, idx):
        return self.fetchall()[idx]


_OR_IGN = re.compile(r'\bINSERT\s+OR\s+IGNORE\s+INTO\b',  re.IGNORECASE)
_OR_REP = re.compile(r'\bINSERT\s+OR\s+REPLACE\s+INTO\b', re.IGNORECASE)

class PGConn:
    """Thin wrapper around psycopg2 matching sqlite3.Connection interface."""

    _SUBS = [
        ('?',                                 '%s'),
        ("datetime('now')",
         "to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS')"),
        ('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY'),
        ('integer primary key autoincrement', 'SERIAL PRIMARY KEY'),
    ]

    def __init__(self, conn):
        self._conn = conn

    def _adapt(self, sql):
        # Escape literal % first (LIKE wildcards etc.) so psycopg3 doesn't
        # treat them as parameter placeholders. Must happen before ?→%s.
        sql = sql.replace('%', '%%')
        for old, new in self._SUBS:
            sql = sql.replace(old, new)
        if _OR_IGN.search(sql):
            sql = _OR_IGN.sub('INSERT INTO', sql)
            sql = sql.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'
        elif _OR_REP.search(sql):
            sql = _OR_REP.sub('INSERT INTO', sql)
        return sql

    def execute(self, sql, params=()):
        sql = self._adapt(sql)
        is_ins = sql.strip().upper().startswith('INSERT')
        if is_ins and 'RETURNING' not in sql.upper():
            sql = sql.rstrip().rstrip(';') + ' RETURNING id'
        cur = self._conn.cursor()
        cur.execute(sql, params or ())
        return _Cursor(cur, is_ins)

    def executemany(self, sql, params_list):
        sql = self._adapt(sql)
        cur = self._conn.cursor()
        cur.executemany(sql, list(params_list))
        return _Cursor(cur)

    def executescript(self, sql):
        cur = self._conn.cursor()
        for stmt in sql.split(';'):
            stmt = self._adapt(stmt.strip())
            if stmt:
                cur.execute(stmt)
        return _Cursor(cur)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def get_conn():
    from urllib.parse import urlparse, unquote
    url = DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    p = urlparse(url)
    # Pass params individually so special chars in password need no URL-encoding
    conn = psycopg.connect(
        host=p.hostname,
        port=p.port or 5432,
        user=unquote(p.username or ''),
        password=unquote(p.password or ''),
        dbname=(p.path or '/postgres').lstrip('/') or 'postgres',
        sslmode='require',
        prepare_threshold=None,   # required for transaction-mode pooler
        row_factory=dict_row,
    )
    return PGConn(conn)


# ── Schema helpers ─────────────────────────────────────────────────────────

def _col_exists(conn, table, col):
    r = conn.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=? AND column_name=?",
        (table, col)
    ).fetchone()
    return r is not None

def _table_exists(conn, table):
    r = conn.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name=?",
        (table,)
    ).fetchone()
    return r is not None


# ── init_db ────────────────────────────────────────────────────────────────

def init_db():
    conn = get_conn()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS students (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name     TEXT    NOT NULL,
            email         TEXT    UNIQUE NOT NULL,
            phone         TEXT    UNIQUE NOT NULL,
            password      TEXT    NOT NULL,
            course        TEXT    NOT NULL DEFAULT 'Physics Foundation',
            plan          TEXT    NOT NULL DEFAULT '6 Months',
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS admins (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL,
            email      TEXT    UNIQUE NOT NULL,
            password   TEXT    NOT NULL,
            created_at TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS instructors (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL,
            email      TEXT    UNIQUE NOT NULL,
            phone      TEXT,
            password   TEXT    NOT NULL,
            subject    TEXT    NOT NULL DEFAULT 'Physics',
            bio        TEXT,
            is_active  INTEGER NOT NULL DEFAULT 1,
            created_at TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS lessons (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            instructor_id INTEGER NOT NULL,
            topic         TEXT    NOT NULL,
            title         TEXT    NOT NULL,
            description   TEXT,
            video_type    TEXT    NOT NULL DEFAULT 'youtube',
            video_url     TEXT    NOT NULL,
            duration      TEXT,
            order_num     INTEGER NOT NULL DEFAULT 0,
            is_published  INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (instructor_id) REFERENCES instructors(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS enquiries (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name  TEXT    NOT NULL,
            email      TEXT,
            phone      TEXT,
            course     TEXT,
            message    TEXT,
            status     TEXT    NOT NULL DEFAULT 'new',
            created_at TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS payments (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id              INTEGER NOT NULL,
            merchant_transaction_id TEXT    UNIQUE NOT NULL,
            amount                  INTEGER NOT NULL,
            status                  TEXT    NOT NULL DEFAULT 'pending',
            phonepe_response        TEXT,
            created_at              TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at              TEXT    NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_students_email     ON students(email);
        CREATE INDEX IF NOT EXISTS idx_students_phone     ON students(phone);
        CREATE INDEX IF NOT EXISTS idx_instructors_email  ON instructors(email);
        CREATE INDEX IF NOT EXISTS idx_lessons_topic      ON lessons(topic);
        CREATE INDEX IF NOT EXISTS idx_lessons_instructor ON lessons(instructor_id);
        CREATE INDEX IF NOT EXISTS idx_payments_txn       ON payments(merchant_transaction_id);
        CREATE INDEX IF NOT EXISTS idx_payments_student   ON payments(student_id)
    """)

    _migrate_sessions(conn)
    _migrate_payment_status(conn)
    _migrate_lessons_course(conn)
    _migrate_email_verification(conn)
    _migrate_password_resets(conn)
    _migrate_lesson_progress(conn)
    _migrate_enrollments(conn)
    _migrate_invoice_numbers(conn)
    _migrate_doubts(conn)
    _migrate_discount_codes(conn)
    _migrate_chatbot_knowledge(conn)
    _seed_default_admin(conn)
    _sync_payment_status(conn)
    conn.commit()
    conn.close()
    print("  [OK] Tables ready: students, admins, instructors, sessions, lessons, enquiries, password_resets, lesson_progress, course_enrollments, course_pricing, doubts, discount_codes, chatbot_knowledge")


def _migrate_sessions(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            token      TEXT    UNIQUE NOT NULL,
            user_id    INTEGER NOT NULL,
            role       TEXT    NOT NULL,
            created_at TEXT    NOT NULL DEFAULT (datetime('now')),
            expires_at TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token)
    """)


def _migrate_payment_status(conn):
    if not _col_exists(conn, 'students', 'payment_status'):
        conn.execute("ALTER TABLE students ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'paid'")
        print("  [OK] students.payment_status column added")


def _migrate_lessons_course(conn):
    if not _col_exists(conn, 'lessons', 'course'):
        conn.execute("ALTER TABLE lessons ADD COLUMN course TEXT NOT NULL DEFAULT 'all'")
        print("  [OK] lessons.course column added")


def _migrate_email_verification(conn):
    if not _col_exists(conn, 'students', 'email_verified'):
        conn.execute("ALTER TABLE students ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
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
        CREATE INDEX IF NOT EXISTS idx_ev_token   ON email_verifications(token);
        CREATE INDEX IF NOT EXISTS idx_ev_student ON email_verifications(student_id)
    """)


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
        CREATE INDEX IF NOT EXISTS idx_pr_student ON password_resets(student_id)
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
        CREATE INDEX IF NOT EXISTS idx_lp_lesson  ON lesson_progress(lesson_id)
    """)


def _migrate_invoice_numbers(conn):
    if not _col_exists(conn, 'payments', 'invoice_number'):
        conn.execute("ALTER TABLE payments ADD COLUMN invoice_number TEXT")
        rows = conn.execute("SELECT id, created_at FROM payments").fetchall()
        for r in rows:
            ym  = (r['created_at'] or '2026-01')[:7].replace('-', '')
            inv = f"INV-{ym}-{r['id']:04d}"
            conn.execute("UPDATE payments SET invoice_number=? WHERE id=?", (inv, r['id']))
        print("  [OK] payments.invoice_number column added")


def _migrate_enrollments(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS course_pricing (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            course     TEXT    NOT NULL,
            plan       TEXT    NOT NULL,
            amount     INTEGER NOT NULL DEFAULT 0,
            created_at TEXT    NOT NULL DEFAULT (datetime('now')),
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
        CREATE INDEX IF NOT EXISTS idx_ce_course  ON course_enrollments(course)
    """)

    count = conn.execute("SELECT COUNT(*) FROM course_pricing").fetchone()[0]
    if count == 0:
        defaults = [
            ('Physics Foundation', '1 Month',  2500),
            ('Physics Foundation', '3 Months', 6500),
            ('Physics Foundation', '6 Months',   99),
            ('Physics Foundation', '12 Months', 198),
            ('JEE Mains',          '1 Month',  3000),
            ('JEE Mains',          '3 Months', 8000),
            ('JEE Mains',          '6 Months',   99),
            ('JEE Mains',          '12 Months', 198),
            ('JEE Advanced',       '1 Month',  3500),
            ('JEE Advanced',       '3 Months', 9500),
            ('JEE Advanced',       '6 Months',   99),
            ('JEE Advanced',       '12 Months', 198),
            ('NEET',               '1 Month',  3000),
            ('NEET',               '3 Months', 8000),
            ('NEET',               '6 Months',   99),
            ('NEET',               '12 Months', 198),
            ('EAMCET',             '1 Month',  2500),
            ('EAMCET',             '3 Months', 6500),
            ('EAMCET',             '6 Months',   99),
            ('EAMCET',             '12 Months', 198),
            ('Class 11 Physics',   '1 Month',  2000),
            ('Class 11 Physics',   '3 Months', 5500),
            ('Class 11 Physics',   '6 Months',   99),
            ('Class 11 Physics',   '12 Months', 198),
            ('Class 12 Physics',   '1 Month',  2000),
            ('Class 12 Physics',   '3 Months', 5500),
            ('Class 12 Physics',   '6 Months',   99),
            ('Class 12 Physics',   '12 Months', 198),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO course_pricing (course, plan, amount) VALUES (?,?,?)",
            defaults
        )
        print("  [OK] Default course pricing seeded")
    else:
        conn.executescript("""
            UPDATE course_pricing SET amount = 99  WHERE plan = '6 Months';
            UPDATE course_pricing SET amount = 198 WHERE plan = '12 Months';
            UPDATE course_pricing SET amount = 2500 WHERE plan = '1 Month' AND course IN ('Physics Foundation','EAMCET');
            UPDATE course_pricing SET amount = 3000 WHERE plan = '1 Month' AND course IN ('JEE Mains','NEET');
            UPDATE course_pricing SET amount = 3500 WHERE plan = '1 Month' AND course = 'JEE Advanced';
            UPDATE course_pricing SET amount = 2000 WHERE plan = '1 Month' AND course IN ('Class 11 Physics','Class 12 Physics')
        """)
        print("  [OK] 6-Month=Rs.99, 12-Month=Rs.198 pricing synced")

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
                "INSERT OR IGNORE INTO course_enrollments (student_id, course, plan, amount) VALUES (?,?,?,?)",
                (s['id'], s['course'], s['plan'], amount)
            )


def _seed_default_admin(conn):
    existing = conn.execute("SELECT id FROM admins WHERE email='admin@laxmiacademy.com'").fetchone()
    if not existing:
        hashed = bcrypt.hashpw(b'Admin@123', bcrypt.gensalt()).decode()
        conn.execute(
            "INSERT INTO admins (name, email, password) VALUES ('Admin','admin@laxmiacademy.com',?)",
            (hashed,)
        )
        print("  [OK] Default admin seeded (admin@laxmiacademy.com / Admin@123)")


def _sync_payment_status(conn):
    conn.execute("""
        UPDATE students
        SET payment_status = CASE
            WHEN EXISTS (
                SELECT 1 FROM payments
                WHERE student_id = students.id AND status = 'pending'
            ) THEN 'pending'
            WHEN EXISTS (
                SELECT 1 FROM payments
                WHERE student_id = students.id AND status = 'paid'
            ) THEN 'paid'
            ELSE payment_status
        END
    """)


def _migrate_doubts(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS doubts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id   INTEGER NOT NULL,
            lesson_id    INTEGER,
            question     TEXT    NOT NULL,
            answer       TEXT,
            status       TEXT    NOT NULL DEFAULT 'open',
            answered_by  INTEGER,
            created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
            answered_at  TEXT,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY (lesson_id)  REFERENCES lessons(id)  ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_doubts_student ON doubts(student_id);
        CREATE INDEX IF NOT EXISTS idx_doubts_lesson  ON doubts(lesson_id);
        CREATE INDEX IF NOT EXISTS idx_doubts_status  ON doubts(status)
    """)


def _migrate_discount_codes(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS discount_codes (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            code             TEXT    UNIQUE NOT NULL,
            discount_percent INTEGER NOT NULL DEFAULT 10,
            max_uses         INTEGER NOT NULL DEFAULT 100,
            times_used       INTEGER NOT NULL DEFAULT 0,
            is_active        INTEGER NOT NULL DEFAULT 1,
            expires_at       TEXT,
            created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_dc_code ON discount_codes(code)
    """)


def _migrate_chatbot_knowledge(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chatbot_knowledge (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            category   TEXT    NOT NULL DEFAULT 'general',
            question   TEXT    NOT NULL,
            answer     TEXT    NOT NULL,
            is_active  INTEGER NOT NULL DEFAULT 1,
            created_at TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_ck_category ON chatbot_knowledge(category)
    """)
    # Seed default FAQs if table is empty
    existing = conn.execute("SELECT COUNT(*) FROM chatbot_knowledge").fetchone()[0]
    if existing == 0:
        faqs = [
            ('courses',    'What courses does Laxmi Academy offer?',
             'We offer Physics courses for NEET, JEE Mains, JEE Advanced, EAMCET, Class 11 Physics, Class 12 Physics, and Physics Foundation. Each is tailored to the respective exam syllabus.'),
            ('courses',    'Is there a Physics Foundation course for beginners?',
             'Yes! Our Physics Foundation course is ideal for students who want to build strong conceptual clarity before moving to competitive exam preparation.'),
            ('pricing',    'What are the subscription plan options?',
             'We offer 1 Month, 3 Months, 6 Months, and 12 Months plans. Longer plans offer better value. Contact us or check the Sign Up page for current pricing.'),
            ('pricing',    'What payment methods are accepted?',
             'We accept all UPI apps (Google Pay, PhonePe, Paytm), debit/credit cards, and net banking — all processed securely through PhonePe. We do not store any card or banking details.'),
            ('pricing',    'Is there a refund policy?',
             'Yes — full refund within 7 days of enrollment if you have watched less than 20% of the course. Refunds are processed in 5–7 business days. See /refund.html for full details.'),
            ('enrollment', 'How do I enroll in a course?',
             'Click Sign Up, fill in your details, select your course and plan, then complete payment. Your course is instantly activated and you can start watching immediately.'),
            ('enrollment', 'Can I access the course from mobile?',
             'Yes! You can install Laxmi Academy as an app on your phone (PWA). On Android tap "Add to Home Screen" in Chrome; on iPhone use Safari Share → Add to Home Screen.'),
            ('demo',       'Is there a free demo class?',
             'Yes! You can book a free 45-minute demo class with no payment required. Click "Book Free Demo Class" on the homepage or contact us via WhatsApp at +91 72078 98999.'),
            ('support',    'How quickly are doubts answered?',
             'Our team typically responds to student doubts within 30 minutes during working hours. You can submit doubts directly from your student dashboard after enrolling.'),
            ('support',    'How do I contact Laxmi Academy?',
             'You can call or WhatsApp us at +91 72078 98999, use the enquiry form on the website, or email us. We are based in Hyderabad, Telangana.'),
        ]
        conn.executemany(
            "INSERT INTO chatbot_knowledge (category, question, answer) VALUES (?, ?, ?)",
            faqs
        )
