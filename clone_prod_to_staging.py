"""
clone_prod_to_staging.py

Copies non-sensitive seed data from prod DB → staging DB.
Copies:   admins, instructors, lessons, course_pricing,
          chatbot_knowledge, discount_codes
Skips:    students, payments, sessions, enquiries,
          doubts, sales_* (fresh in staging)

Usage:
    PROD_DATABASE_URL="postgres://..." STAGING_DATABASE_URL="postgres://..." python clone_prod_to_staging.py
"""

import os, sys
from urllib.parse import urlparse, unquote
import psycopg
from psycopg.rows import dict_row

PROD_URL    = os.environ.get('PROD_DATABASE_URL', '')
STAGING_URL = os.environ.get('STAGING_DATABASE_URL', '')

if not PROD_URL or not STAGING_URL:
    print("ERROR: Set PROD_DATABASE_URL and STAGING_DATABASE_URL env vars.")
    sys.exit(1)

if PROD_URL == STAGING_URL:
    print("ERROR: PROD and STAGING URLs are the same — aborting to protect prod data.")
    sys.exit(1)


def _connect(url):
    p = urlparse(url)
    return psycopg.connect(
        host=p.hostname, port=p.port or 5432,
        user=unquote(p.username or ''), password=unquote(p.password or ''),
        dbname=(p.path or '/postgres').lstrip('/') or 'postgres',
        sslmode='require', row_factory=dict_row,
    )


def clone_table(prod, staging, table, columns, truncate=True):
    rows = prod.execute(f"SELECT {columns} FROM {table}").fetchall()
    if not rows:
        print(f"  [SKIP] {table}: no rows in prod")
        return
    if truncate:
        staging.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
    cols = list(rows[0].keys())
    col_str = ', '.join(cols)
    placeholders = ', '.join(['%s'] * len(cols))
    count = 0
    for row in rows:
        vals = tuple(row[c] for c in cols)
        staging.execute(
            f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
            vals
        )
        count += 1
    print(f"  [OK] {table}: {count} rows copied")


print("Connecting to prod...")
prod_conn    = _connect(PROD_URL)
print("Connecting to staging...")
staging_conn = _connect(STAGING_URL)

try:
    print("\nCloning seed tables prod → staging...\n")

    clone_table(prod_conn, staging_conn, 'admins',
                'name, email, password, created_at')

    clone_table(prod_conn, staging_conn, 'instructors',
                'name, email, phone, password, subject, bio, is_active, created_at')

    clone_table(prod_conn, staging_conn, 'lessons',
                'instructor_id, topic, title, description, video_type, video_url, duration, order_num, is_published, course, created_at')

    clone_table(prod_conn, staging_conn, 'course_pricing',
                'course, plan, amount, created_at')

    clone_table(prod_conn, staging_conn, 'chatbot_knowledge',
                'category, question, answer, is_active, created_at')

    clone_table(prod_conn, staging_conn, 'discount_codes',
                'code, discount_percent, max_uses, times_used, is_active, expires_at, created_at')

    staging_conn.commit()
    print("\nDone. Staging DB seeded from prod.")
    print("Tables NOT copied (intentionally fresh in staging):")
    print("  students, payments, sessions, enquiries, doubts, sales_leads, sales_orders, sales_outreach")

except Exception as e:
    staging_conn.rollback()
    print(f"\nERROR: {e}")
    sys.exit(1)
finally:
    prod_conn.close()
    staging_conn.close()
