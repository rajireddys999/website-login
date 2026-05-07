-- NR AI Orbit — Staging Database Schema
-- Run this in your staging Supabase project: SQL Editor → New query → paste → Run
-- Safe to run on a fresh project (all CREATE IF NOT EXISTS)

-- ── Students ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.students (
  id             SERIAL PRIMARY KEY,
  full_name      TEXT    NOT NULL,
  email          TEXT    NOT NULL UNIQUE,
  phone          TEXT    NOT NULL UNIQUE,
  password       TEXT    NOT NULL,
  course         TEXT    NOT NULL DEFAULT 'Physics Foundation',
  plan           TEXT    NOT NULL DEFAULT '6 Months',
  is_active      INTEGER NOT NULL DEFAULT 1,
  created_at     TEXT    NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS'),
  payment_status TEXT    NOT NULL DEFAULT 'paid',
  email_verified INTEGER NOT NULL DEFAULT 0
);

-- ── Admins ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.admins (
  id         SERIAL PRIMARY KEY,
  name       TEXT NOT NULL,
  email      TEXT NOT NULL UNIQUE,
  password   TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS')
);

-- ── Instructors ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.instructors (
  id         SERIAL PRIMARY KEY,
  name       TEXT    NOT NULL,
  email      TEXT    NOT NULL UNIQUE,
  phone      TEXT,
  password   TEXT    NOT NULL,
  subject    TEXT    NOT NULL DEFAULT 'Physics',
  bio        TEXT,
  is_active  INTEGER NOT NULL DEFAULT 1,
  created_at TEXT    NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS')
);

-- ── Sessions ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.sessions (
  id         SERIAL PRIMARY KEY,
  token      TEXT NOT NULL UNIQUE,
  user_id    INTEGER NOT NULL,
  role       TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS'),
  expires_at TEXT NOT NULL
);

-- ── Enquiries ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.enquiries (
  id         SERIAL PRIMARY KEY,
  full_name  TEXT NOT NULL,
  email      TEXT,
  phone      TEXT,
  course     TEXT,
  message    TEXT,
  status     TEXT NOT NULL DEFAULT 'new',
  created_at TEXT NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS')
);

-- ── Lessons (depends on instructors) ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.lessons (
  id            SERIAL PRIMARY KEY,
  instructor_id INTEGER NOT NULL REFERENCES public.instructors(id) ON DELETE CASCADE,
  topic         TEXT    NOT NULL,
  title         TEXT    NOT NULL,
  description   TEXT,
  video_type    TEXT    NOT NULL DEFAULT 'youtube',
  video_url     TEXT    NOT NULL,
  duration      TEXT,
  order_num     INTEGER NOT NULL DEFAULT 0,
  is_published  INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT    NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS'),
  course        TEXT    NOT NULL DEFAULT 'all'
);

-- ── Course pricing ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.course_pricing (
  id         SERIAL PRIMARY KEY,
  course     TEXT    NOT NULL,
  plan       TEXT    NOT NULL,
  amount     INTEGER NOT NULL DEFAULT 0,
  created_at TEXT    NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS'),
  UNIQUE(course, plan)
);

-- ── Course enrollments (depends on students) ──────────────────────────────
CREATE TABLE IF NOT EXISTS public.course_enrollments (
  id          SERIAL PRIMARY KEY,
  student_id  INTEGER NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
  course      TEXT    NOT NULL,
  plan        TEXT    NOT NULL DEFAULT '6 Months',
  amount      INTEGER NOT NULL DEFAULT 0,
  status      TEXT    NOT NULL DEFAULT 'active',
  enrolled_at TEXT    NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS')
);

-- ── Payments (depends on students) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.payments (
  id                      SERIAL PRIMARY KEY,
  student_id              INTEGER NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
  merchant_transaction_id TEXT    NOT NULL UNIQUE,
  amount                  INTEGER NOT NULL,
  status                  TEXT    NOT NULL DEFAULT 'pending',
  phonepe_response        TEXT,
  created_at              TEXT    NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at              TEXT    NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS'),
  invoice_number          TEXT
);

-- ── Lesson progress (depends on students + lessons) ───────────────────────
CREATE TABLE IF NOT EXISTS public.lesson_progress (
  id              SERIAL PRIMARY KEY,
  student_id      INTEGER NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
  lesson_id       INTEGER NOT NULL REFERENCES public.lessons(id) ON DELETE CASCADE,
  watched         INTEGER NOT NULL DEFAULT 0,
  completed       INTEGER NOT NULL DEFAULT 0,
  watched_seconds INTEGER NOT NULL DEFAULT 0,
  updated_at      TEXT    NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS'),
  UNIQUE(student_id, lesson_id)
);

-- ── Email verifications (depends on students) ─────────────────────────────
CREATE TABLE IF NOT EXISTS public.email_verifications (
  id         SERIAL PRIMARY KEY,
  student_id INTEGER NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
  token      TEXT    NOT NULL UNIQUE,
  expires_at TEXT    NOT NULL,
  used       INTEGER NOT NULL DEFAULT 0,
  created_at TEXT    NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS')
);

-- ── Password resets (depends on students) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS public.password_resets (
  id         SERIAL PRIMARY KEY,
  student_id INTEGER NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
  token      TEXT    NOT NULL UNIQUE,
  expires_at TEXT    NOT NULL,
  used       INTEGER NOT NULL DEFAULT 0,
  created_at TEXT    NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS')
);

-- ── Doubts (depends on students + lessons) ────────────────────────────────
CREATE TABLE IF NOT EXISTS public.doubts (
  id          SERIAL PRIMARY KEY,
  student_id  INTEGER NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
  lesson_id   INTEGER          REFERENCES public.lessons(id)  ON DELETE SET NULL,
  question    TEXT    NOT NULL,
  answer      TEXT,
  status      TEXT    NOT NULL DEFAULT 'open',
  answered_by INTEGER,
  created_at  TEXT    NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS'),
  answered_at TEXT
);

-- ── Discount codes ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.discount_codes (
  id               SERIAL PRIMARY KEY,
  code             TEXT    NOT NULL UNIQUE,
  discount_percent INTEGER NOT NULL DEFAULT 10,
  max_uses         INTEGER NOT NULL DEFAULT 100,
  times_used       INTEGER NOT NULL DEFAULT 0,
  is_active        INTEGER NOT NULL DEFAULT 1,
  expires_at       TEXT,
  created_at       TEXT    NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS')
);

-- ── Chatbot knowledge ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.chatbot_knowledge (
  id         SERIAL PRIMARY KEY,
  category   TEXT    NOT NULL DEFAULT 'general',
  question   TEXT    NOT NULL,
  answer     TEXT    NOT NULL,
  is_active  INTEGER NOT NULL DEFAULT 1,
  created_at TEXT    NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS')
);

-- ── Sales leads ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.sales_leads (
  id              SERIAL PRIMARY KEY,
  name            TEXT NOT NULL,
  type            TEXT NOT NULL DEFAULT 'Student',
  phone           TEXT NOT NULL DEFAULT '',
  email           TEXT NOT NULL DEFAULT '',
  location        TEXT NOT NULL DEFAULT '',
  course_interest TEXT NOT NULL DEFAULT '',
  status          TEXT NOT NULL DEFAULT 'New',
  notes           TEXT NOT NULL DEFAULT '',
  created_at      TEXT NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at      TEXT NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS')
);

-- ── Sales orders (depends on sales_leads) ────────────────────────────────
CREATE TABLE IF NOT EXISTS public.sales_orders (
  id          SERIAL PRIMARY KEY,
  lead_id     INTEGER REFERENCES public.sales_leads(id) ON DELETE SET NULL,
  lead_name   TEXT NOT NULL,
  course_name TEXT NOT NULL,
  amount      REAL NOT NULL DEFAULT 0,
  order_date  TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'Pending',
  notes       TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS')
);

-- ── Sales outreach (depends on sales_leads) ───────────────────────────────
CREATE TABLE IF NOT EXISTS public.sales_outreach (
  id              SERIAL PRIMARY KEY,
  lead_id         INTEGER REFERENCES public.sales_leads(id) ON DELETE CASCADE,
  channel         TEXT NOT NULL DEFAULT 'WhatsApp',
  message         TEXT NOT NULL DEFAULT '',
  delivery_status TEXT NOT NULL DEFAULT 'Sent',
  created_at      TEXT NOT NULL DEFAULT to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS')
);

-- ── Indexes ───────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_students_email      ON public.students(email);
CREATE INDEX IF NOT EXISTS idx_students_phone      ON public.students(phone);
CREATE INDEX IF NOT EXISTS idx_instructors_email   ON public.instructors(email);
CREATE INDEX IF NOT EXISTS idx_sessions_token      ON public.sessions(token);
CREATE INDEX IF NOT EXISTS idx_lessons_topic       ON public.lessons(topic);
CREATE INDEX IF NOT EXISTS idx_lessons_instructor  ON public.lessons(instructor_id);
CREATE INDEX IF NOT EXISTS idx_payments_txn        ON public.payments(merchant_transaction_id);
CREATE INDEX IF NOT EXISTS idx_payments_student    ON public.payments(student_id);
CREATE INDEX IF NOT EXISTS idx_ce_student          ON public.course_enrollments(student_id);
CREATE INDEX IF NOT EXISTS idx_ce_course           ON public.course_enrollments(course);
CREATE INDEX IF NOT EXISTS idx_lp_student          ON public.lesson_progress(student_id);
CREATE INDEX IF NOT EXISTS idx_lp_lesson           ON public.lesson_progress(lesson_id);
CREATE INDEX IF NOT EXISTS idx_ev_token            ON public.email_verifications(token);
CREATE INDEX IF NOT EXISTS idx_ev_student          ON public.email_verifications(student_id);
CREATE INDEX IF NOT EXISTS idx_pr_token            ON public.password_resets(token);
CREATE INDEX IF NOT EXISTS idx_pr_student          ON public.password_resets(student_id);
CREATE INDEX IF NOT EXISTS idx_doubts_student      ON public.doubts(student_id);
CREATE INDEX IF NOT EXISTS idx_doubts_status       ON public.doubts(status);
CREATE INDEX IF NOT EXISTS idx_dc_code             ON public.discount_codes(code);
CREATE INDEX IF NOT EXISTS idx_ck_category         ON public.chatbot_knowledge(category);

-- ── Seed default admin ────────────────────────────────────────────────────
-- Password: Admin@123  (bcrypt hash — change after first login)
INSERT INTO public.admins (name, email, password)
VALUES ('Admin', 'admin@nraiorbit.com', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMaFMDQfgHl7h5NiO9vA7mBfKu')
ON CONFLICT (email) DO NOTHING;

-- ── Seed course pricing ───────────────────────────────────────────────────
INSERT INTO public.course_pricing (course, plan, amount) VALUES
  ('Physics Foundation', '6 Months',  999),
  ('Physics Foundation', '9 Months',  1499),
  ('Physics Foundation', '12 Months', 1998),
  ('JEE Mains',          '6 Months',  999),
  ('JEE Mains',          '9 Months',  1499),
  ('JEE Mains',          '12 Months', 1998),
  ('JEE Advanced',       '6 Months',  999),
  ('JEE Advanced',       '9 Months',  1499),
  ('JEE Advanced',       '12 Months', 1998),
  ('NEET',               '6 Months',  999),
  ('NEET',               '9 Months',  1499),
  ('NEET',               '12 Months', 1998),
  ('EAMCET',             '6 Months',  999),
  ('EAMCET',             '9 Months',  1499),
  ('EAMCET',             '12 Months', 1998),
  ('Class 11 Physics',   '6 Months',  999),
  ('Class 11 Physics',   '9 Months',  1499),
  ('Class 11 Physics',   '12 Months', 1998),
  ('Class 12 Physics',   '6 Months',  999),
  ('Class 12 Physics',   '9 Months',  1499),
  ('Class 12 Physics',   '12 Months', 1998)
ON CONFLICT (course, plan) DO NOTHING;
