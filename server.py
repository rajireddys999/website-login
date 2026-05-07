import uuid, os, re, json, base64, hashlib, secrets, smtplib, math
from email.mime.text import MIMEText
import bcrypt
import requests as http_requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from db import get_conn, init_db
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

limiter = Limiter(key_func=get_remote_address, app=app, default_limits=[])

# Always init DB — runs under both `python server.py` and gunicorn
try:
    import sys
    init_db()
    print("[OK] Database ready (Supabase)", file=sys.stderr)
except Exception as _init_err:
    import sys, traceback
    print(f"[FATAL] init_db() failed: {_init_err}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)

# ── Email config ─────────────────────────────────────────────────
SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ.get('SMTP_USER', '') or os.environ.get('SMTP_EMAIL', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')
FROM_EMAIL = os.environ.get('FROM_EMAIL', SMTP_USER)

def send_email(to_addr, subject, body_html):
    if not SMTP_USER or not SMTP_PASS:
        raise RuntimeError("SMTP not configured")
    msg = MIMEText(body_html, 'html')
    msg['Subject'] = subject
    msg['From']    = f"NR AI Orbit Learning Portal <{FROM_EMAIL}>"
    msg['To']      = to_addr
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(FROM_EMAIL, [to_addr], msg.as_string())

def send_verification_email(email, full_name, token):
    verify_url = f"{APP_BASE_URL}/verify-email.html?token={token}"
    body = f"""
    <p>Hi {full_name},</p>
    <p>Please verify your email address to activate your NR AI Orbit Learning Portal account:</p>
    <p><a href="{verify_url}" style="background:#6366f1;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none">Verify Email</a></p>
    <p>This link expires in 24 hours. If you did not sign up, ignore this email.</p>
    """
    send_email(email, "Verify your NR AI Orbit Learning Portal account", body)

# ── PhonePe config (UAT sandbox by default) ───────────────────────
PHONEPE_MERCHANT_ID = os.environ.get('PHONEPE_MERCHANT_ID', 'PGTESTPAYUAT86')
PHONEPE_SALT_KEY    = os.environ.get('PHONEPE_SALT_KEY',    '96434309-7796-489d-8924-ab56988a6076')
PHONEPE_SALT_INDEX  = os.environ.get('PHONEPE_SALT_INDEX',  '1')
PHONEPE_BASE_URL    = os.environ.get('PHONEPE_BASE_URL',    'https://api-preprod.phonepe.com/apis/pg-sandbox')
APP_BASE_URL        = os.environ.get('APP_BASE_URL',        'https://website-login-wyxt.onrender.com')

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads', 'videos')
ALLOWED_EXTENSIONS = {'mp4', 'webm', 'mkv', 'mov', 'avi'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_youtube_id(url):
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([A-Za-z0-9_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None

# ── Helpers ──────────────────────────────────────────────────────

def create_session(user_id, role):
    token      = str(uuid.uuid4())
    expires_at = (datetime.utcnow() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    conn = get_conn()
    conn.execute(
        "INSERT INTO sessions (token, user_id, role, expires_at) VALUES (?, ?, ?, ?)",
        (token, user_id, role, expires_at)
    )
    conn.commit(); conn.close()
    return token

def get_session(token):
    if not token:
        return None
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM sessions WHERE token = ? AND expires_at > datetime('now')", (token,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def require_auth():
    auth  = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '').strip()
    session = get_session(token)
    if not session:
        return None, jsonify({'error': 'Unauthorised. Please log in.'}), 401
    return session, None, None

def require_role(*roles):
    session, err_resp, err_code = require_auth()
    if err_resp:
        return None, err_resp, err_code
    if session['role'] not in roles:
        return None, jsonify({'error': f"Access denied. Required role: {', '.join(roles)}."}), 403
    return session, None, None

def row_to_dict(row):
    return dict(row) if row else None

# ── Public health check (no auth — used by Render & uptime monitors) ──
@app.route('/health')
def health():
    try:
        conn = get_conn()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return jsonify({'status': 'ok', 'db': 'ok', 'timestamp': datetime.utcnow().isoformat()})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 503

# ── Static files ──────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/uploads/videos/<path:filename>')
def serve_video(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)

# ── POST /api/login ──────────────────────────────────────────────

@app.route('/api/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    data       = request.get_json() or {}
    identifier = data.get('identifier', '').strip()
    password   = data.get('password', '')
    role       = data.get('role', 'student')

    if not identifier or not password:
        return jsonify({'error': 'Email/phone and password are required.'}), 400

    conn = get_conn()
    if role == 'student':
        user = conn.execute(
            "SELECT * FROM students WHERE (email = ? OR phone = ?)",
            (identifier, identifier)
        ).fetchone()
    elif role == 'admin':
        user = conn.execute(
            "SELECT * FROM admins WHERE email = ?", (identifier,)
        ).fetchone()
    elif role == 'instructor':
        user = conn.execute(
            "SELECT * FROM instructors WHERE email = ? AND is_active = 1", (identifier,)
        ).fetchone()
    else:
        conn.close()
        return jsonify({'error': 'Invalid role.'}), 400
    conn.close()

    if not user or not bcrypt.checkpw(password.encode(), user['password'].encode()):
        return jsonify({'error': 'Invalid credentials. Please check and try again.'}), 401

    if role == 'student' and not dict(user).get('email_verified', 1):
        return jsonify({'error': 'Please verify your email before logging in. Check your inbox for the verification link.', 'email_unverified': True}), 403

    token = create_session(user['id'], role)
    safe  = {k: v for k, v in dict(user).items() if k != 'password'}
    payment_pending = role == 'student' and user['payment_status'] != 'paid'
    return jsonify({'token': token, 'role': role, 'user': safe, 'payment_pending': payment_pending})

# ── POST /api/register ───────────────────────────────────────────

@app.route('/api/register', methods=['POST'])
def register():
    VALID_COURSES = [
        'NEET',
        'JEE Mains',
        'JEE Advanced',
        'EAMCET',
        'Class 11 Physics',
        'Class 12 Physics',
        'Physics Foundation',
    ]
    data      = request.get_json() or {}
    full_name = data.get('full_name', '').strip()
    email     = data.get('email', '').strip()
    phone     = data.get('phone', '').strip()
    password  = data.get('password', '')
    course    = data.get('course', '').strip()
    plan      = data.get('plan', '6 Months')

    if course not in VALID_COURSES:
        course = 'JEE Mains'

    if not full_name or not email or not phone or not password:
        return jsonify({'error': 'full_name, email, phone and password are required.'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters.'}), 400

    conn = get_conn()
    existing = conn.execute(
        "SELECT id FROM students WHERE email = ? OR phone = ?", (email, phone)
    ).fetchone()
    if existing:
        conn.close()
        return jsonify({'error': 'An account with this email or phone already exists.'}), 409

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    cursor = conn.execute(
        "INSERT INTO students (full_name, email, phone, password, course, plan, is_active, payment_status, email_verified) VALUES (?, ?, ?, ?, ?, ?, 1, 'pending', 1)",
        (full_name, email, phone, hashed, course, plan)
    )
    conn.commit()
    student_id = cursor.lastrowid

    # Immediately create course_enrollment so admin can see it without waiting for migration
    if course:
        pricing = conn.execute(
            "SELECT amount FROM course_pricing WHERE course=? AND plan=?", (course, plan)
        ).fetchone()
        enr_amount = pricing['amount'] if pricing else 99
        conn.execute(
            "INSERT INTO course_enrollments (student_id, course, plan, amount, status) VALUES (?,?,?,?,'active')",
            (student_id, course, plan, enr_amount)
        )
        conn.commit()

    conn.close()

    session_token = create_session(student_id, 'student')
    return jsonify({
        'token': session_token, 'role': 'student', 'student_id': student_id,
        'message': 'Account created successfully. Welcome to NR AI Orbit Learning Portal!',
    }), 201

# ── GET /api/verify-email?token= ────────────────────────────────

@app.route('/api/verify-email', methods=['GET'])
def verify_email():
    token = request.args.get('token', '').strip()
    if not token:
        return jsonify({'error': 'Verification token is required.'}), 400

    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM email_verifications WHERE token = ? AND used = 0 AND expires_at > datetime('now')",
        (token,)
    ).fetchone()

    if not row:
        conn.close()
        return jsonify({'error': 'Invalid or expired verification link. Please request a new one.'}), 400

    conn.execute("UPDATE students SET email_verified = 1 WHERE id = ?", (row['student_id'],))
    conn.execute("UPDATE email_verifications SET used = 1 WHERE id = ?", (row['id'],))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Email verified successfully. You can now log in.'})

# ── POST /api/resend-verification ────────────────────────────────

@app.route('/api/resend-verification', methods=['POST'])
@limiter.limit("3 per hour")
def resend_verification():
    data  = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    if not email:
        return jsonify({'error': 'email is required.'}), 400

    conn    = get_conn()
    student = conn.execute(
        "SELECT id, full_name, email_verified FROM students WHERE email = ?", (email,)
    ).fetchone()

    if not student:
        conn.close()
        # Don't reveal whether email exists
        return jsonify({'message': 'If that email is registered, a new verification link has been sent.'})

    if student['email_verified']:
        conn.close()
        return jsonify({'error': 'This email is already verified.'}), 409

    # Invalidate previous tokens
    conn.execute("UPDATE email_verifications SET used = 1 WHERE student_id = ?", (student['id'],))

    verify_token = secrets.token_urlsafe(32)
    expires_at   = (datetime.utcnow() + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    conn.execute(
        "INSERT INTO email_verifications (student_id, token, expires_at) VALUES (?, ?, ?)",
        (student['id'], verify_token, expires_at)
    )
    conn.commit()
    conn.close()

    try:
        send_verification_email(email, student['full_name'] if student else '', verify_token)
    except Exception as exc:
        app.logger.error("Verification email failed for %s: %s", email, exc)
    return jsonify({'message': 'If that email is registered, a new verification link has been sent.'})

# ── POST /api/forgot-password ────────────────────────────────────

@app.route('/api/forgot-password', methods=['POST'])
@limiter.limit("5 per hour")
def forgot_password():
    data  = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    if not email:
        return jsonify({'error': 'email is required.'}), 400

    conn    = get_conn()
    student = conn.execute(
        "SELECT id, full_name FROM students WHERE email = ?", (email,)
    ).fetchone()

    # Always return the same message so we don't reveal whether an account exists
    generic_msg = 'If that email is registered, a password reset link has been sent.'

    if not student:
        conn.close()
        return jsonify({'message': generic_msg})

    # Invalidate previous unused tokens for this student
    conn.execute(
        "UPDATE password_resets SET used = 1 WHERE student_id = ? AND used = 0",
        (student['id'],)
    )

    reset_token = secrets.token_urlsafe(32)
    expires_at  = (datetime.utcnow() + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
    conn.execute(
        "INSERT INTO password_resets (student_id, token, expires_at) VALUES (?, ?, ?)",
        (student['id'], reset_token, expires_at)
    )
    conn.commit()
    conn.close()

    reset_url = f"{APP_BASE_URL}/reset-password.html?token={reset_token}"
    body = f"""
    <p>Hi {student['full_name']},</p>
    <p>We received a request to reset your NR AI Orbit Learning Portal password. Click the button below to choose a new password:</p>
    <p><a href="{reset_url}" style="background:#6366f1;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none">Reset Password</a></p>
    <p>This link expires in <strong>1 hour</strong>. If you did not request a password reset, you can safely ignore this email.</p>
    """
    try:
        send_email(email, "Reset your NR AI Orbit Learning Portal password", body)
    except Exception as exc:
        app.logger.error("Password reset email failed for %s: %s", email, exc)
    return jsonify({'message': generic_msg})

# ── POST /api/reset-password ──────────────────────────────────────

@app.route('/api/reset-password', methods=['POST'])
def reset_password():
    data         = request.get_json() or {}
    token        = data.get('token', '').strip()
    new_password = data.get('new_password', '')

    if not token or not new_password:
        return jsonify({'error': 'token and new_password are required.'}), 400
    if len(new_password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters.'}), 400

    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM password_resets WHERE token = ? AND used = 0 AND expires_at > datetime('now')",
        (token,)
    ).fetchone()

    if not row:
        conn.close()
        return jsonify({'error': 'Invalid or expired reset link. Please request a new one.'}), 400

    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    conn.execute("UPDATE students SET password = ? WHERE id = ?", (hashed, row['student_id']))
    conn.execute("UPDATE password_resets SET used = 1 WHERE id = ?", (row['id'],))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Password reset successfully. You can now log in with your new password.'})

# ── POST /api/logout ─────────────────────────────────────────────

@app.route('/api/logout', methods=['POST'])
def logout():
    auth  = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '').strip()
    if token:
        conn = get_conn()
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit(); conn.close()
    return jsonify({'message': 'Logged out.'})

# ── GET /api/me ──────────────────────────────────────────────────

@app.route('/api/me', methods=['GET'])
def me():
    session, err_resp, err_code = require_auth()
    if err_resp:
        return err_resp, err_code

    conn = get_conn()
    if session['role'] == 'student':
        user = conn.execute(
            "SELECT id, full_name, email, phone, course, plan, created_at, payment_status, is_active FROM students WHERE id = ?",
            (session['user_id'],)
        ).fetchone()
    elif session['role'] == 'admin':
        user = conn.execute(
            "SELECT id, name, email, created_at FROM admins WHERE id = ?",
            (session['user_id'],)
        ).fetchone()
    elif session['role'] == 'instructor':
        user = conn.execute(
            "SELECT id, name, email, phone, subject, bio, created_at FROM instructors WHERE id = ?",
            (session['user_id'],)
        ).fetchone()
    conn.close()

    if not user:
        return jsonify({'error': 'User not found.'}), 404
    return jsonify({'role': session['role'], 'user': row_to_dict(user)})

# ── POST /api/enquiry ────────────────────────────────────────────

@app.route('/api/enquiry', methods=['POST'])
def enquiry():
    data      = request.get_json() or {}
    full_name = data.get('full_name', '').strip()
    phone     = data.get('phone', '').strip()
    if not full_name or not phone:
        return jsonify({'error': 'full_name and phone are required.'}), 400

    conn = get_conn()
    conn.execute(
        "INSERT INTO enquiries (full_name, email, phone, course, message) VALUES (?, ?, ?, ?, ?)",
        (full_name, data.get('email',''), phone, data.get('course',''), data.get('message',''))
    )
    conn.commit(); conn.close()
    return jsonify({'message': 'Enquiry received. We will contact you shortly.'}), 201

# ── GET /api/lessons — for students ─────────────────────────────

@app.route('/api/lessons', methods=['GET'])
def get_lessons():
    session, err_resp, err_code = require_auth()
    if err_resp:
        return err_resp, err_code

    conn = get_conn()

    if session['role'] == 'student':
        student = conn.execute(
            "SELECT course, payment_status FROM students WHERE id = ?", (session['user_id'],)
        ).fetchone()
        if not student or student['payment_status'] != 'paid':
            conn.close()
            return jsonify([])
        student_course = student['course'] if student else None

        if student_course:
            rows = conn.execute("""
                SELECT l.*, i.name as instructor_name
                FROM lessons l JOIN instructors i ON l.instructor_id = i.id
                WHERE l.is_published = 1 AND (l.course = ? OR l.course = 'all')
                ORDER BY l.order_num ASC, l.created_at ASC
            """, (student_course,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT l.*, i.name as instructor_name
                FROM lessons l JOIN instructors i ON l.instructor_id = i.id
                WHERE l.is_published = 1
                ORDER BY l.order_num ASC, l.created_at ASC
            """).fetchall()
    else:
        topic = request.args.get('topic', '')
        if topic:
            rows = conn.execute("""
                SELECT l.*, i.name as instructor_name
                FROM lessons l JOIN instructors i ON l.instructor_id = i.id
                WHERE l.topic = ? AND l.is_published = 1
                ORDER BY l.order_num ASC, l.created_at ASC
            """, (topic,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT l.*, i.name as instructor_name
                FROM lessons l JOIN instructors i ON l.instructor_id = i.id
                WHERE l.is_published = 1
                ORDER BY l.topic, l.order_num ASC
            """).fetchall()

    conn.close()
    return jsonify([dict(r) for r in rows])

# ── INSTRUCTOR: GET own lessons ──────────────────────────────────

@app.route('/api/instructor/lessons', methods=['GET'])
def instructor_get_lessons():
    session, err_resp, err_code = require_role('instructor')
    if err_resp:
        return err_resp, err_code

    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM lessons WHERE instructor_id = ?
        ORDER BY topic, order_num ASC, created_at DESC
    """, (session['user_id'],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ── INSTRUCTOR: POST lesson (YouTube URL) ────────────────────────

@app.route('/api/instructor/lessons', methods=['POST'])
def instructor_add_lesson():
    session, err_resp, err_code = require_role('instructor')
    if err_resp:
        return err_resp, err_code

    VALID_COURSES = [
        'NEET - BI-PC', 'JEE MAINS - Physics', 'EAMCET - Physics',
        'Intermediate - 1-Year Physics', 'Intermediate - 2-Year Physics', 'all'
    ]
    data        = request.get_json() or {}
    topic       = data.get('topic', '').strip()
    course      = data.get('course', '').strip()
    title       = data.get('title', '').strip()
    video_url   = data.get('video_url', '').strip()
    description = data.get('description', '').strip()
    duration    = data.get('duration', '').strip()
    order_num   = int(data.get('order_num', 0))

    if not title or not video_url:
        return jsonify({'error': 'title and video_url are required.'}), 400
    if not course or course not in VALID_COURSES:
        return jsonify({'error': f'course must be one of: {", ".join(VALID_COURSES)}'}), 400

    video_type       = 'youtube'
    stored_video_url = video_url

    conn = get_conn()
    cursor = conn.execute("""
        INSERT INTO lessons (instructor_id, topic, course, title, description, video_type, video_url, duration, order_num)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (session['user_id'], topic, course, title, description, video_type, stored_video_url, duration, order_num))
    conn.commit()
    lesson_id = cursor.lastrowid
    lesson    = conn.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
    conn.close()
    return jsonify(dict(lesson)), 201

# ── INSTRUCTOR: POST /api/instructor/upload — video file ────────

@app.route('/api/instructor/upload', methods=['POST'])
def instructor_upload_video():
    session, err_resp, err_code = require_role('instructor')
    if err_resp:
        return err_resp, err_code

    if 'video' not in request.files:
        return jsonify({'error': 'No video file provided.'}), 400

    file = request.files['video']
    if file.filename == '':
        return jsonify({'error': 'Empty filename.'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': f'Allowed formats: {", ".join(ALLOWED_EXTENSIONS)}'}), 400

    VALID_COURSES = [
        'NEET - BI-PC', 'JEE MAINS - Physics', 'EAMCET - Physics',
        'Intermediate - 1-Year Physics', 'Intermediate - 2-Year Physics', 'all'
    ]
    topic       = request.form.get('topic', '').strip()
    course      = request.form.get('course', '').strip()
    title       = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    duration    = request.form.get('duration', '').strip()
    order_num   = int(request.form.get('order_num', 0))

    if not title:
        return jsonify({'error': 'title is required.'}), 400
    if not course or course not in VALID_COURSES:
        return jsonify({'error': f'course must be one of: {", ".join(VALID_COURSES)}'}), 400

    filename  = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
    filepath  = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    video_url = f'/uploads/videos/{filename}'

    conn = get_conn()
    cursor = conn.execute("""
        INSERT INTO lessons (instructor_id, topic, course, title, description, video_type, video_url, duration, order_num)
        VALUES (?, ?, ?, ?, ?, 'upload', ?, ?, ?)
    """, (session['user_id'], topic, course, title, description, video_url, duration, order_num))
    conn.commit()
    lesson_id = cursor.lastrowid
    lesson    = conn.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
    conn.close()
    return jsonify(dict(lesson)), 201

# ── INSTRUCTOR: PATCH lesson ─────────────────────────────────────

@app.route('/api/instructor/lessons/<int:lid>', methods=['PATCH'])
def instructor_update_lesson(lid):
    session, err_resp, err_code = require_role('instructor')
    if err_resp:
        return err_resp, err_code

    conn   = get_conn()
    lesson = conn.execute(
        "SELECT * FROM lessons WHERE id = ? AND instructor_id = ?",
        (lid, session['user_id'])
    ).fetchone()
    if not lesson:
        conn.close()
        return jsonify({'error': 'Lesson not found.'}), 404

    data = request.get_json() or {}
    fields = {}
    for f in ['title', 'description', 'duration', 'order_num', 'is_published']:
        if f in data:
            fields[f] = data[f]

    if fields:
        set_clause = ', '.join(f'{k} = ?' for k in fields)
        conn.execute(f"UPDATE lessons SET {set_clause} WHERE id = ?",
                     list(fields.values()) + [lid])
        conn.commit()

    updated = conn.execute("SELECT * FROM lessons WHERE id = ?", (lid,)).fetchone()
    conn.close()
    return jsonify(dict(updated))

# ── INSTRUCTOR: DELETE lesson ────────────────────────────────────

@app.route('/api/instructor/lessons/<int:lid>', methods=['DELETE'])
def instructor_delete_lesson(lid):
    session, err_resp, err_code = require_role('instructor')
    if err_resp:
        return err_resp, err_code

    conn   = get_conn()
    lesson = conn.execute(
        "SELECT * FROM lessons WHERE id = ? AND instructor_id = ?",
        (lid, session['user_id'])
    ).fetchone()
    if not lesson:
        conn.close()
        return jsonify({'error': 'Lesson not found.'}), 404

    # Delete uploaded file if applicable
    if lesson['video_type'] == 'upload' and lesson['video_url'].startswith('/uploads/'):
        filepath = os.path.join(os.path.dirname(__file__), lesson['video_url'].lstrip('/'))
        if os.path.exists(filepath):
            os.remove(filepath)

    conn.execute("DELETE FROM lessons WHERE id = ?", (lid,))
    conn.commit(); conn.close()
    return jsonify({'message': 'Lesson deleted.'})

# ── INSTRUCTOR: GET stats ────────────────────────────────────────

@app.route('/api/instructor/stats', methods=['GET'])
def instructor_stats():
    session, err_resp, err_code = require_role('instructor')
    if err_resp:
        return err_resp, err_code

    conn = get_conn()
    stats = {
        'total_lessons':     conn.execute("SELECT COUNT(*) FROM lessons WHERE instructor_id = ?", (session['user_id'],)).fetchone()[0],
        'published_lessons': conn.execute("SELECT COUNT(*) FROM lessons WHERE instructor_id = ? AND is_published = 1", (session['user_id'],)).fetchone()[0],
        'topics_covered':    conn.execute("SELECT COUNT(DISTINCT topic) FROM lessons WHERE instructor_id = ?", (session['user_id'],)).fetchone()[0],
        'youtube_lessons':   conn.execute("SELECT COUNT(*) FROM lessons WHERE instructor_id = ? AND video_type = 'youtube'", (session['user_id'],)).fetchone()[0],
        'upload_lessons':    conn.execute("SELECT COUNT(*) FROM lessons WHERE instructor_id = ? AND video_type = 'upload'", (session['user_id'],)).fetchone()[0],
        'by_topic': [dict(r) for r in conn.execute(
            "SELECT topic, COUNT(*) as count FROM lessons WHERE instructor_id = ? GROUP BY topic ORDER BY count DESC",
            (session['user_id'],)
        ).fetchall()],
        'recent_lessons': [dict(r) for r in conn.execute(
            "SELECT * FROM lessons WHERE instructor_id = ? ORDER BY created_at DESC LIMIT 5",
            (session['user_id'],)
        ).fetchall()],
    }
    conn.close()
    return jsonify(stats)

# ── ADMIN: students ──────────────────────────────────────────────

@app.route('/api/admin/students', methods=['GET'])
def admin_students():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    page_param = request.args.get('page')
    conn = get_conn()

    if page_param is None:
        rows = conn.execute("""
            SELECT s.id, s.full_name, s.email, s.phone, s.course, s.plan,
                   s.is_active, s.payment_status, s.created_at,
                   STRING_AGG(DISTINCT ce.course, ' | ') as enrolled_courses,
                   COALESCE((SELECT SUM(amount) FROM payments
                             WHERE student_id=s.id AND status='paid'), 0)    as paid_amount,
                   COALESCE((SELECT SUM(amount) FROM payments
                             WHERE student_id=s.id AND status='pending'), 0) as due_amount
            FROM students s
            LEFT JOIN course_enrollments ce ON ce.student_id = s.id AND ce.status = 'active'
            GROUP BY s.id
            ORDER BY s.created_at DESC
        """).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    page  = max(1, int(page_param))
    limit = max(1, min(200, int(request.args.get('limit', 50))))
    total = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    rows  = conn.execute(
        "SELECT id, full_name, email, phone, course, plan, is_active, payment_status, created_at FROM students ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, (page - 1) * limit)
    ).fetchall()
    conn.close()
    return jsonify({'data': [dict(r) for r in rows], 'total': total, 'page': page, 'pages': math.ceil(total / limit) if total else 1})

# ── ADMIN: enquiries ─────────────────────────────────────────────

@app.route('/api/admin/enquiries', methods=['GET'])
def admin_enquiries():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    page_param = request.args.get('page')
    conn = get_conn()

    if page_param is None:
        rows = conn.execute("SELECT * FROM enquiries ORDER BY created_at DESC").fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    page  = max(1, int(page_param))
    limit = max(1, min(200, int(request.args.get('limit', 50))))
    total = conn.execute("SELECT COUNT(*) FROM enquiries").fetchone()[0]
    rows  = conn.execute(
        "SELECT * FROM enquiries ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, (page - 1) * limit)
    ).fetchall()
    conn.close()
    return jsonify({'data': [dict(r) for r in rows], 'total': total, 'page': page, 'pages': math.ceil(total / limit) if total else 1})

# ── ADMIN: stats ─────────────────────────────────────────────────

@app.route('/api/admin/stats', methods=['GET'])
def admin_stats():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    conn = get_conn()
    stats = {
        'total_students':    conn.execute("SELECT COUNT(*) FROM students").fetchone()[0],
        'active_students':   conn.execute("SELECT COUNT(*) FROM students WHERE is_active=1").fetchone()[0],
        'revoked_students':  conn.execute("SELECT COUNT(*) FROM students WHERE is_active=0").fetchone()[0],
        'total_enquiries':   conn.execute("SELECT COUNT(*) FROM enquiries").fetchone()[0],
        'new_enquiries':     conn.execute("SELECT COUNT(*) FROM enquiries WHERE status='new'").fetchone()[0],
        'active_sessions':   conn.execute("SELECT COUNT(*) FROM sessions WHERE expires_at > datetime('now')").fetchone()[0],
        'total_lessons':     conn.execute("SELECT COUNT(*) FROM lessons WHERE is_published=1").fetchone()[0],
        'total_instructors': conn.execute("SELECT COUNT(*) FROM instructors WHERE is_active=1").fetchone()[0],
        'courses': [dict(r) for r in conn.execute(
            "SELECT course, COUNT(*) as count FROM students GROUP BY course ORDER BY count DESC"
        ).fetchall()],
        'pending_students': conn.execute("SELECT COUNT(*) FROM students WHERE payment_status='pending'").fetchone()[0],
        'total_revenue':    conn.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='paid'").fetchone()[0],
        'recent_students': [dict(r) for r in conn.execute(
            "SELECT id, full_name, email, course, created_at FROM students ORDER BY created_at DESC LIMIT 5"
        ).fetchall()],
        'recent_enquiries': [dict(r) for r in conn.execute(
            "SELECT id, full_name, phone, course, status, created_at FROM enquiries ORDER BY created_at DESC LIMIT 5"
        ).fetchall()],
    }
    conn.close()
    return jsonify(stats)

# ── ADMIN: toggle student ────────────────────────────────────────

@app.route('/api/admin/students/<int:sid>/toggle', methods=['PATCH'])
def toggle_student(sid):
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    conn    = get_conn()
    student = conn.execute("SELECT id, full_name, is_active FROM students WHERE id=?", (sid,)).fetchone()
    if not student:
        conn.close()
        return jsonify({'error': 'Student not found.'}), 404

    new_status = 0 if student['is_active'] else 1
    conn.execute("UPDATE students SET is_active=? WHERE id=?", (new_status, sid))
    if new_status == 0:
        conn.execute("DELETE FROM sessions WHERE user_id=? AND role='student'", (sid,))
    conn.commit(); conn.close()
    return jsonify({'id': sid, 'is_active': new_status,
                    'message': f"Access {'restored' if new_status else 'revoked'} for {student['full_name']}."})

# ── ADMIN: delete student ────────────────────────────────────────

@app.route('/api/admin/students/<int:sid>', methods=['DELETE'])
def delete_student(sid):
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    conn    = get_conn()
    student = conn.execute("SELECT full_name FROM students WHERE id=?", (sid,)).fetchone()
    if not student:
        conn.close()
        return jsonify({'error': 'Student not found.'}), 404

    conn.execute("DELETE FROM sessions WHERE user_id=? AND role='student'", (sid,))
    conn.execute("DELETE FROM students WHERE id=?", (sid,))
    conn.commit(); conn.close()
    return jsonify({'message': f"{student['full_name']} deleted successfully."})

# ── ADMIN: enquiry status ────────────────────────────────────────

@app.route('/api/admin/enquiries/<int:eid>/status', methods=['PATCH'])
def update_enquiry_status(eid):
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    data   = request.get_json() or {}
    status = data.get('status', '')
    if status not in ('new', 'contacted', 'enrolled'):
        return jsonify({'error': 'status must be new, contacted, or enrolled.'}), 400

    conn = get_conn()
    conn.execute("UPDATE enquiries SET status=? WHERE id=?", (status, eid))
    conn.commit(); conn.close()
    return jsonify({'id': eid, 'status': status})

# ── ADMIN: sessions ──────────────────────────────────────────────

@app.route('/api/admin/sessions', methods=['GET'])
def admin_sessions():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    conn = get_conn()
    rows = conn.execute("""
        SELECT s.id, s.token, s.role, s.created_at, s.expires_at,
               CASE s.role
                 WHEN 'student'    THEN (SELECT full_name FROM students    WHERE id = s.user_id)
                 WHEN 'admin'      THEN (SELECT name       FROM admins      WHERE id = s.user_id)
                 WHEN 'instructor' THEN (SELECT name       FROM instructors WHERE id = s.user_id)
               END as user_name
        FROM sessions s
        WHERE s.expires_at > datetime('now')
        ORDER BY s.created_at DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ── ADMIN: DELETE /api/admin/sessions/cleanup ────────────────────

@app.route('/api/admin/sessions/cleanup', methods=['DELETE'])
def admin_sessions_cleanup():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    conn    = get_conn()
    cursor  = conn.execute("DELETE FROM sessions WHERE expires_at < datetime('now')")
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return jsonify({'deleted': deleted})

# ── ADMIN: instructors ───────────────────────────────────────────

@app.route('/api/admin/instructors', methods=['GET'])
def admin_instructors():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name, email, phone, subject, bio, is_active, created_at FROM instructors ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ── ADMIN: all lessons ───────────────────────────────────────────

@app.route('/api/admin/lessons', methods=['GET'])
def admin_lessons():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    page_param = request.args.get('page')
    conn = get_conn()

    if page_param is None:
        rows = conn.execute("""
            SELECT l.*, i.name as instructor_name
            FROM lessons l JOIN instructors i ON l.instructor_id = i.id
            ORDER BY l.created_at DESC
        """).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    page  = max(1, int(page_param))
    limit = max(1, min(200, int(request.args.get('limit', 50))))
    total = conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
    rows  = conn.execute("""
        SELECT l.*, i.name as instructor_name
        FROM lessons l JOIN instructors i ON l.instructor_id = i.id
        ORDER BY l.created_at DESC LIMIT ? OFFSET ?
    """, (limit, (page - 1) * limit)).fetchall()
    conn.close()
    return jsonify({'data': [dict(r) for r in rows], 'total': total, 'page': page, 'pages': math.ceil(total / limit) if total else 1})

# ── ADMIN: toggle instructor ─────────────────────────────────────

@app.route('/api/admin/instructors/<int:iid>/toggle', methods=['PATCH'])
def toggle_instructor(iid):
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    conn = get_conn()
    inst = conn.execute("SELECT id, name, is_active FROM instructors WHERE id=?", (iid,)).fetchone()
    if not inst:
        conn.close()
        return jsonify({'error': 'Instructor not found.'}), 404

    new_status = 0 if inst['is_active'] else 1
    conn.execute("UPDATE instructors SET is_active=? WHERE id=?", (new_status, iid))
    if new_status == 0:
        conn.execute("DELETE FROM sessions WHERE user_id=? AND role='instructor'", (iid,))
    conn.commit(); conn.close()
    return jsonify({'id': iid, 'is_active': new_status,
                    'message': f"{'Restored' if new_status else 'Revoked'} access for {inst['name']}."})

# ── GET /api/status ──────────────────────────────────────────────

@app.route('/api/status', methods=['GET'])
def status():
    conn = get_conn()
    counts = {
        'students':    conn.execute("SELECT COUNT(*) FROM students").fetchone()[0],
        'admins':      conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0],
        'instructors': conn.execute("SELECT COUNT(*) FROM instructors").fetchone()[0],
        'lessons':     conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0],
        'sessions':    conn.execute("SELECT COUNT(*) FROM sessions WHERE expires_at > datetime('now')").fetchone()[0],
        'enquiries':   conn.execute("SELECT COUNT(*) FROM enquiries").fetchone()[0],
    }
    conn.close()
    return jsonify({'status': 'ok', 'database': 'laxmi_academy.db', 'counts': counts})

# ── PhonePe helpers ──────────────────────────────────────────────

def _phonepe_checksum(payload_b64):
    raw = payload_b64 + '/pg/v1/pay' + PHONEPE_SALT_KEY
    return hashlib.sha256(raw.encode()).hexdigest() + '###' + PHONEPE_SALT_INDEX

def _phonepe_status_checksum(txn_id):
    path = f'/pg/v1/status/{PHONEPE_MERCHANT_ID}/{txn_id}'
    raw  = path + PHONEPE_SALT_KEY
    return hashlib.sha256(raw.encode()).hexdigest() + '###' + PHONEPE_SALT_INDEX, path

# ── POST /api/payment/initiate ────────────────────────────────────

@app.route('/api/payment/initiate', methods=['POST'])
def initiate_payment():
    session, err_resp, err_code = require_auth()
    if err_resp:
        return err_resp, err_code

    data   = request.get_json() or {}
    amount = int(data.get('amount', 0))
    if amount <= 0:
        return jsonify({'error': 'Invalid amount.'}), 400

    txn_id = f"LA{session['user_id']}_{uuid.uuid4().hex[:10].upper()}"

    payload = {
        'merchantId':            PHONEPE_MERCHANT_ID,
        'merchantTransactionId': txn_id,
        'merchantUserId':        f"USER{session['user_id']}",
        'amount':                amount * 100,
        'redirectUrl':           f"{APP_BASE_URL}/api/payment/callback/{txn_id}",
        'redirectMode':          'REDIRECT',
        'callbackUrl':           f"{APP_BASE_URL}/api/payment/webhook",
        'paymentInstrument':     {'type': 'PAY_PAGE'}
    }

    payload_b64 = base64.b64encode(json.dumps(payload).encode()).decode()
    checksum    = _phonepe_checksum(payload_b64)

    conn = get_conn()
    conn.execute(
        "INSERT INTO payments (student_id, merchant_transaction_id, amount) VALUES (?, ?, ?)",
        (session['user_id'], txn_id, amount)
    )
    conn.commit()
    conn.close()

    try:
        resp = http_requests.post(
            f"{PHONEPE_BASE_URL}/pg/v1/pay",
            headers={'Content-Type': 'application/json', 'X-VERIFY': checksum, 'accept': 'application/json'},
            json={'request': payload_b64},
            timeout=15
        )
        resp_data = resp.json()
        if resp_data.get('success'):
            redirect_url = resp_data['data']['instrumentResponse']['redirectInfo']['url']
            return jsonify({'redirect_url': redirect_url, 'txn_id': txn_id})
        return jsonify({'error': resp_data.get('message', 'PhonePe initiation failed.')}), 502
    except Exception as ex:
        return jsonify({'error': f'Payment gateway unreachable: {ex}'}), 503

# ── GET /api/payment/callback/<txn_id> ───────────────────────────

@app.route('/api/payment/callback/<txn_id>', methods=['GET'])
def payment_callback(txn_id):
    checksum, url_path = _phonepe_status_checksum(txn_id)
    success = False
    resp_json = {}
    try:
        resp = http_requests.get(
            f"{PHONEPE_BASE_URL}{url_path}",
            headers={'X-VERIFY': checksum, 'X-MERCHANT-ID': PHONEPE_MERCHANT_ID, 'accept': 'application/json'},
            timeout=15
        )
        resp_json = resp.json()
        success = resp_json.get('success') and resp_json.get('code') == 'PAYMENT_SUCCESS'
    except Exception:
        pass

    conn = get_conn()
    payment = conn.execute(
        "SELECT * FROM payments WHERE merchant_transaction_id = ?", (txn_id,)
    ).fetchone()

    if payment:
        new_status = 'paid' if success else 'failed'
        conn.execute(
            "UPDATE payments SET status = ?, phonepe_response = ?, updated_at = datetime('now') WHERE merchant_transaction_id = ?",
            (new_status, json.dumps(resp_json), txn_id)
        )
        if success:
            conn.execute(
                "UPDATE students SET is_active = 1, payment_status = 'paid' WHERE id = ?",
                (payment['student_id'],)
            )
        conn.commit()

    conn.close()

    if success:
        return redirect('/login.html?payment=success')
    return redirect('/login.html?payment=failed')

# ── POST /api/payment/webhook ─────────────────────────────────────

@app.route('/api/payment/webhook', methods=['POST'])
def payment_webhook():
    body    = request.get_json(silent=True) or {}
    encoded = body.get('response', '')

    # Verify PhonePe X-VERIFY signature
    x_verify = request.headers.get('X-VERIFY', '')
    if x_verify:
        expected = hashlib.sha256((encoded + PHONEPE_SALT_KEY).encode()).hexdigest() + '###' + PHONEPE_SALT_INDEX
        if not secrets.compare_digest(x_verify, expected):
            app.logger.warning("PhonePe webhook signature mismatch — possible spoofing attempt")
            return jsonify({'error': 'Invalid signature.'}), 400

    try:
        decoded   = json.loads(base64.b64decode(encoded).decode())
        txn_id    = decoded.get('data', {}).get('merchantTransactionId', '')
        pg_success = decoded.get('success') and decoded.get('code') == 'PAYMENT_SUCCESS'
    except Exception:
        return jsonify({'status': 'ignored'}), 200

    if txn_id:
        conn    = get_conn()
        payment = conn.execute(
            "SELECT * FROM payments WHERE merchant_transaction_id = ?", (txn_id,)
        ).fetchone()
        if payment and payment['status'] == 'pending':
            new_status = 'paid' if pg_success else 'failed'
            conn.execute(
                "UPDATE payments SET status = ?, phonepe_response = ?, updated_at = datetime('now') WHERE merchant_transaction_id = ?",
                (new_status, json.dumps(decoded), txn_id)
            )
            if pg_success:
                conn.execute(
                    "UPDATE students SET is_active = 1, payment_status = 'paid' WHERE id = ?",
                    (payment['student_id'],)
                )
            conn.commit()
        conn.close()

    return jsonify({'status': 'ok'}), 200

# ── GET /api/payment/status/<txn_id> ─────────────────────────────

@app.route('/api/payment/status/<txn_id>', methods=['GET'])
def payment_status(txn_id):
    session, err_resp, err_code = require_auth()
    if err_resp:
        return err_resp, err_code

    conn = get_conn()
    payment = conn.execute(
        "SELECT status, amount, created_at FROM payments WHERE merchant_transaction_id = ? AND student_id = ?",
        (txn_id, session['user_id'])
    ).fetchone()
    conn.close()

    if not payment:
        return jsonify({'error': 'Transaction not found.'}), 404
    return jsonify(dict(payment))

# ── ADMIN: payments ───────────────────────────────────────────────

@app.route('/api/admin/payments', methods=['GET'])
def admin_payments():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    page_param = request.args.get('page')
    conn = get_conn()

    if page_param is None:
        rows = conn.execute("""
            SELECT p.*, s.full_name, s.email
            FROM payments p JOIN students s ON p.student_id = s.id
            ORDER BY p.created_at DESC
        """).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    page  = max(1, int(page_param))
    limit = max(1, min(200, int(request.args.get('limit', 50))))
    total = conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
    rows  = conn.execute("""
        SELECT p.*, s.full_name, s.email
        FROM payments p JOIN students s ON p.student_id = s.id
        ORDER BY p.created_at DESC LIMIT ? OFFSET ?
    """, (limit, (page - 1) * limit)).fetchall()
    conn.close()
    return jsonify({'data': [dict(r) for r in rows], 'total': total, 'page': page, 'pages': math.ceil(total / limit) if total else 1})

# ── ADMIN: PATCH /api/admin/payments/<id>/status ─────────────────

@app.route('/api/admin/payments/<int:pid>/status', methods=['PATCH'])
def admin_payment_status(pid):
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    data       = request.get_json() or {}
    new_status = data.get('status', '')
    if new_status not in ('paid', 'pending', 'failed'):
        return jsonify({'error': 'status must be paid, pending, or failed.'}), 400

    conn    = get_conn()
    payment = conn.execute("SELECT * FROM payments WHERE id = ?", (pid,)).fetchone()
    if not payment:
        conn.close()
        return jsonify({'error': 'Payment not found.'}), 404

    conn.execute(
        "UPDATE payments SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (new_status, pid)
    )

    if new_status == 'paid':
        conn.execute(
            "UPDATE students SET is_active = 1, payment_status = 'paid' WHERE id = ?",
            (payment['student_id'],)
        )

    conn.commit()
    updated = conn.execute("SELECT * FROM payments WHERE id = ?", (pid,)).fetchone()
    conn.close()
    return jsonify({'success': True, 'payment': dict(updated)})

# ── Invoice PDF ──────────────────────────────────────────────────

@app.route('/api/invoice/<int:payment_id>', methods=['GET'])
def download_invoice(payment_id):
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
    # Accept token from query param so plain <a href> links work in browser tabs
    qtoken = request.args.get('token', '').strip()
    if qtoken:
        request.environ['HTTP_AUTHORIZATION'] = f'Bearer {qtoken}'
    session_data, err_resp, err_code = require_auth()
    if err_resp:
        return err_resp, err_code

    conn = get_conn()
    row = conn.execute("""
        SELECT p.*, s.full_name, s.email, s.phone, s.course, s.plan
        FROM payments p JOIN students s ON p.student_id = s.id
        WHERE p.id = ?
    """, (payment_id,)).fetchone()
    conn.close()

    if not row:
        return jsonify({'error': 'Payment not found.'}), 404

    if session_data['role'] == 'student' and row['student_id'] != session_data['user_id']:
        return jsonify({'error': 'Access denied.'}), 403

    p = dict(row)

    def safe(val, fallback='-'):
        """Strip non-Latin-1 chars so fpdf built-in fonts never crash."""
        s = str(val or fallback)
        return s.encode('latin-1', errors='replace').decode('latin-1')

    inv_num = p.get('invoice_number') or f"INV-{(p.get('created_at') or '2026-01')[:7].replace('-','')}-{payment_id:04d}"
    status  = (p.get('status') or 'pending').upper()
    amount  = p.get('amount', 0) or 0
    txn_id  = safe(p.get('merchant_transaction_id'), '-')
    issued  = safe((p.get('created_at') or '')[:10], '-')

    NL = dict(new_x=XPos.LMARGIN, new_y=YPos.NEXT)  # fpdf2 2.7+ line-break

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Header bar
    pdf.set_fill_color(30, 20, 60)
    pdf.rect(0, 0, 210, 28, 'F')
    pdf.set_text_color(255, 255, 255)
    pdf.set_font('Helvetica', 'B', 18)
    pdf.set_xy(10, 7)
    pdf.cell(0, 12, 'NR AI Orbit Learning Portal', **NL)
    pdf.set_font('Helvetica', '', 9)
    pdf.set_xy(10, 19)
    pdf.cell(0, 6, 'Physics Excellence - Payment Invoice')

    # Status badge top-right
    badge_color = (34, 197, 94) if status == 'PAID' else (234, 179, 8) if status == 'PENDING' else (239, 68, 68)
    pdf.set_fill_color(*badge_color)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_xy(155, 9)
    pdf.cell(45, 10, status, align='C', fill=True)

    pdf.set_text_color(30, 20, 60)
    pdf.set_xy(10, 35)

    # Invoice meta
    pdf.set_font('Helvetica', 'B', 13)
    pdf.cell(0, 8, f'Invoice  {safe(inv_num)}', **NL)
    pdf.set_font('Helvetica', '', 9)
    pdf.set_text_color(100, 100, 120)
    pdf.cell(0, 6, f'Issued: {issued}    Transaction: {txn_id}', **NL)

    pdf.ln(6)
    pdf.set_draw_color(200, 200, 220)
    pdf.set_line_width(0.3)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)

    # Bill To
    pdf.set_text_color(30, 20, 60)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 6, 'Bill To', **NL)
    pdf.set_font('Helvetica', '', 10)
    pdf.cell(0, 6, safe(p.get('full_name')), **NL)
    pdf.cell(0, 6, safe(p.get('email')), **NL)
    if p.get('phone'):
        pdf.cell(0, 6, safe(p['phone']), **NL)

    pdf.ln(6)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)

    # Line items table
    pdf.set_fill_color(240, 238, 255)
    pdf.set_font('Helvetica', 'B', 9)
    pdf.cell(100, 8, 'Description', fill=True, border=1)
    pdf.cell(45,  8, 'Plan',        fill=True, border=1)
    pdf.cell(45,  8, 'Amount',      fill=True, border=1, align='R', **NL)

    pdf.set_font('Helvetica', '', 9)
    pdf.cell(100, 8, safe(p.get('course') or p.get('plan') or 'Course Enrollment'), border=1)
    pdf.cell(45,  8, safe(p.get('plan') or '-'), border=1)
    pdf.cell(45,  8, f'Rs. {amount:,}', border=1, align='R', **NL)

    pdf.ln(4)
    pdf.set_font('Helvetica', 'B', 11)
    pdf.cell(145, 9, 'Total Amount', align='R')
    pdf.cell(45,  9, f'Rs. {amount:,}', align='R', **NL)

    pdf.ln(10)
    pdf.set_font('Helvetica', 'I', 8)
    pdf.set_text_color(130, 130, 150)
    pdf.cell(0, 6, 'Thank you for choosing NR AI Orbit Learning Portal. This is a computer-generated invoice.', align='C', **NL)

    pdf_bytes = pdf.output()
    response = app.response_class(bytes(pdf_bytes), mimetype='application/pdf')
    response.headers['Content-Disposition'] = f'attachment; filename="invoice-{safe(inv_num)}.pdf"'
    return response

# ── Linear proxy ─────────────────────────────────────────────────

LINEAR_API_KEY  = os.environ.get('LINEAR_API_KEY', '')
LINEAR_TEAM_ID  = os.environ.get('LINEAR_TEAM_ID', '4c267af7-bd36-43cf-8e6c-1d1d29522c21')

@app.route('/api/admin/linear', methods=['GET'])
def admin_linear():
    session, err, code = require_role('admin')
    if err: return err, code
    try:
        resp = http_requests.post(
            'https://api.linear.app/graphql',
            headers={'Authorization': LINEAR_API_KEY, 'Content-Type': 'application/json'},
            json={'query': f'''{{
              team(id: "{LINEAR_TEAM_ID}") {{
                states {{ nodes {{ id name type position }} }}
                issues {{
                  nodes {{
                    id identifier title priority createdAt
                    state {{ name type }}
                    assignee {{ name }}
                  }}
                }}
              }}
            }}'''},
            timeout=10
        )
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 503

# ── AI assist ─────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

@app.route('/api/admin/ai-assist', methods=['POST'])
def ai_assist():
    session, err, code = require_role('admin')
    if err: return err, code

    data    = request.get_json() or {}
    prompt  = data.get('prompt', '').strip()
    context = data.get('context', {})
    history = data.get('history', [])

    if not prompt:
        return jsonify({'error': 'prompt is required.'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'ANTHROPIC_API_KEY not set. Add it to your Render environment variables.'}), 503

    system = f"""You are an AI operations assistant embedded in the Mission Control dashboard for NR AI Orbit Learning Portal — a physics coaching centre in Hyderabad, India.

Live academy stats right now:
{json.dumps(context, indent=2)}

Your job: help the admin understand their data, answer operational questions, spot trends, and suggest actions.
Be concise (2–4 sentences unless detail is needed). Use numbers from the stats above when relevant."""

    messages = [{'role': m['role'], 'content': m['content']} for m in history[-6:]]
    messages.append({'role': 'user', 'content': prompt})

    try:
        resp = http_requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json'
            },
            json={'model': 'claude-haiku-4-5-20251001', 'max_tokens': 512,
                  'system': system, 'messages': messages},
            timeout=30
        )
        d = resp.json()
        if resp.ok:
            return jsonify({'response': d['content'][0]['text'], 'model': d.get('model', '')})
        return jsonify({'error': d.get('error', {}).get('message', 'AI request failed')}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 503

# ── Website health ────────────────────────────────────────────────

@app.route('/api/admin/health', methods=['GET'])
def admin_health():
    session, err, code = require_role('admin')
    if err: return err, code
    conn = get_conn()
    try:
        student_count = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        db_ok = True
    except Exception:
        student_count = 0
        db_ok = False
    finally:
        conn.close()
    return jsonify({
        'status': 'ok',
        'db': db_ok,
        'student_count': student_count,
        'ts': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    })

# ── STUDENT: POST /api/student/progress ──────────────────────────

@app.route('/api/student/progress', methods=['POST'])
def student_post_progress():
    session, err_resp, err_code = require_role('student')
    if err_resp:
        return err_resp, err_code

    data            = request.get_json() or {}
    lesson_id       = data.get('lesson_id')
    watched_seconds = int(data.get('watched_seconds', 0))
    completed       = 1 if data.get('completed') else 0

    if lesson_id is None:
        return jsonify({'error': 'lesson_id is required.'}), 400

    watched = 1 if watched_seconds > 0 or completed else 0

    conn = get_conn()
    conn.execute("""
        INSERT INTO lesson_progress (student_id, lesson_id, watched, completed, watched_seconds, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(student_id, lesson_id) DO UPDATE SET
            watched         = GREATEST(watched, excluded.watched),
            completed       = GREATEST(completed, excluded.completed),
            watched_seconds = GREATEST(watched_seconds, excluded.watched_seconds),
            updated_at      = datetime('now')
    """, (session['user_id'], lesson_id, watched, completed, watched_seconds))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ── STUDENT: GET /api/student/progress ───────────────────────────

@app.route('/api/student/progress', methods=['GET'])
def student_get_progress():
    session, err_resp, err_code = require_role('student')
    if err_resp:
        return err_resp, err_code

    conn = get_conn()
    rows = conn.execute(
        "SELECT lesson_id, watched, completed, watched_seconds FROM lesson_progress WHERE student_id = ?",
        (session['user_id'],)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ── STUDENT: get pricing for own course+plan ─────────────────────

@app.route('/api/student/pricing', methods=['GET'])
def student_pricing():
    session, err_resp, err_code = require_role('student')
    if err_resp:
        return err_resp, err_code
    conn = get_conn()
    student = conn.execute("SELECT course, plan FROM students WHERE id=?", (session['user_id'],)).fetchone()
    if not student:
        conn.close()
        return jsonify({'amount': 99})
    row = conn.execute(
        "SELECT amount FROM course_pricing WHERE course=? AND plan=?",
        (student['course'], student['plan'])
    ).fetchone()
    conn.close()
    return jsonify({'amount': row['amount'] if row else 99, 'course': student['course'], 'plan': student['plan']})

# ── ADMIN: course pricing ─────────────────────────────────────────

@app.route('/api/admin/course-pricing', methods=['GET'])
def get_course_pricing():
    session, err, code = require_role('admin')
    if err: return err, code
    conn = get_conn()
    rows = conn.execute("SELECT * FROM course_pricing ORDER BY course, plan").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/course-pricing', methods=['POST'])
def upsert_course_pricing():
    session, err, code = require_role('admin')
    if err: return err, code
    data   = request.get_json() or {}
    course = (data.get('course') or '').strip()
    plan   = (data.get('plan') or '').strip()
    amount = int(data.get('amount', 0))
    if not course or not plan or amount < 0:
        return jsonify({'error': 'course, plan, and amount required.'}), 400
    conn = get_conn()
    conn.execute("""
        INSERT INTO course_pricing (course, plan, amount)
        VALUES (?,?,?)
        ON CONFLICT(course, plan) DO UPDATE SET amount=excluded.amount
    """, (course, plan, amount))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/course-pricing/<int:pid>', methods=['DELETE'])
def delete_course_pricing(pid):
    session, err, code = require_role('admin')
    if err: return err, code
    conn = get_conn()
    conn.execute("DELETE FROM course_pricing WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ── ADMIN: student enrollments ────────────────────────────────────

@app.route('/api/admin/students/<int:sid>/enrollments', methods=['GET'])
def get_student_enrollments(sid):
    session, err, code = require_role('admin')
    if err: return err, code
    conn = None
    try:
        conn = get_conn()
        rows = conn.execute("""
            SELECT ce.id, ce.student_id, ce.course, ce.plan, ce.amount,
                   ce.status, ce.enrolled_at,
                   MAX(p.status) AS pay_status,
                   MAX(p.amount) AS pay_amount,
                   MAX(p.id)     AS payment_id
            FROM course_enrollments ce
            LEFT JOIN payments p ON p.student_id = ce.student_id
                                 AND p.merchant_transaction_id LIKE 'ADM-' || ce.student_id::text || '-%'
                                 AND p.amount = ce.amount
            WHERE ce.student_id = ?
            GROUP BY ce.id, ce.student_id, ce.course, ce.plan, ce.amount, ce.status, ce.enrolled_at
            ORDER BY ce.enrolled_at DESC
        """, (sid,)).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as exc:
        app.logger.error("get_student_enrollments error: %s", exc, exc_info=True)
        return jsonify({'error': str(exc)}), 500
    finally:
        if conn:
            try: conn.close()
            except: pass

@app.route('/api/admin/students/<int:sid>/enrollments', methods=['POST'])
def add_student_enrollment(sid):
    session, err, code = require_role('admin')
    if err: return err, code
    data   = request.get_json() or {}
    course = (data.get('course') or '').strip()
    plan   = (data.get('plan') or '6 Months').strip()
    raw_amt = data.get('amount', None)
    if not course:
        return jsonify({'error': 'course is required.'}), 400

    conn = None
    try:
        conn = get_conn()
        student = conn.execute("SELECT id, course FROM students WHERE id=?", (sid,)).fetchone()
        if not student:
            return jsonify({'error': 'Student not found.'}), 404

        dup = conn.execute(
            "SELECT id FROM course_enrollments WHERE student_id=? AND course=? AND status='active'",
            (sid, course)
        ).fetchone()
        if dup:
            return jsonify({'error': f'Already enrolled in {course}. Deactivate existing first.'}), 409

        # Auto-fill amount from pricing table if not provided or zero
        try:
            parsed_amt = int(raw_amt) if raw_amt is not None else 0
        except (TypeError, ValueError):
            parsed_amt = 0

        if parsed_amt == 0:
            pricing = conn.execute(
                "SELECT amount FROM course_pricing WHERE course=? AND plan=?", (course, plan)
            ).fetchone()
            amount = pricing['amount'] if pricing else 99
        else:
            amount = parsed_amt

        cur = conn.execute(
            "INSERT INTO course_enrollments (student_id, course, plan, amount) VALUES (?,?,?,?)",
            (sid, course, plan, amount)
        )
        eid = cur.lastrowid

        # Only update students.course if this is their very first enrollment
        existing_count = conn.execute(
            "SELECT COUNT(*) FROM course_enrollments WHERE student_id=?", (sid,)
        ).fetchone()[0]
        if existing_count == 1:
            conn.execute("UPDATE students SET course=?, plan=? WHERE id=?", (course, plan, sid))

        # New admin-added course is pending until student actually pays
        txn_id = f"ADM-{sid}-{secrets.token_hex(8).upper()}"
        conn.execute(
            "INSERT INTO payments (student_id, merchant_transaction_id, amount, status) VALUES (?,?,?,?)",
            (sid, txn_id, amount, 'pending')
        )
        # Recalculate payment_status from actual payment records
        has_pending = conn.execute(
            "SELECT COUNT(*) FROM payments WHERE student_id=? AND status='pending'", (sid,)
        ).fetchone()[0]
        new_pay_status = 'pending' if has_pending else 'paid'
        conn.execute("UPDATE students SET payment_status=? WHERE id=?", (new_pay_status, sid))
        conn.commit()
        row = conn.execute("SELECT * FROM course_enrollments WHERE id=?", (eid,)).fetchone()
        return jsonify(dict(row)), 201
    except Exception as exc:
        app.logger.error("add_student_enrollment error: %s", exc, exc_info=True)
        if conn:
            try: conn.rollback()
            except Exception: pass
        return jsonify({'error': f'Server error: {str(exc)}'}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@app.route('/api/admin/enrollments/<int:eid>', methods=['PATCH'])
def update_enrollment(eid):
    session, err, code = require_role('admin')
    if err: return err, code
    data   = request.get_json() or {}
    plan   = data.get('plan')
    amount = data.get('amount')
    status = data.get('status')
    updates, params = [], []
    if plan:   updates.append("plan=?");   params.append(plan)
    if amount is not None: updates.append("amount=?"); params.append(int(amount))
    if status: updates.append("status=?"); params.append(status)
    if not updates:
        return jsonify({'error': 'Nothing to update.'}), 400
    conn = get_conn()
    conn.execute(f"UPDATE course_enrollments SET {','.join(updates)} WHERE id=?", params+[eid])
    conn.commit()
    row = conn.execute("SELECT * FROM course_enrollments WHERE id=?", (eid,)).fetchone()
    conn.close()
    return jsonify(dict(row) if row else {})

@app.route('/api/admin/enrollments/<int:eid>', methods=['DELETE'])
def delete_enrollment(eid):
    session, err, code = require_role('admin')
    if err: return err, code
    conn = get_conn()
    enr = conn.execute("SELECT student_id FROM course_enrollments WHERE id=?", (eid,)).fetchone()
    if not enr:
        conn.close(); return jsonify({'error': 'Enrollment not found.'}), 404
    sid = enr['student_id']
    conn.execute("DELETE FROM course_enrollments WHERE id=?", (eid,))
    # Update students.course to remaining first enrollment
    remaining = conn.execute(
        "SELECT course, plan FROM course_enrollments WHERE student_id=? ORDER BY enrolled_at LIMIT 1", (sid,)
    ).fetchone()
    if remaining:
        conn.execute("UPDATE students SET course=?, plan=? WHERE id=?",
                     (remaining['course'], remaining['plan'], sid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ── PUBLIC: website chatbot (RAJ-new) ────────────────────────────

@app.route('/api/chat', methods=['POST'])
@limiter.limit("30 per hour")
def public_chat():
    data    = request.get_json() or {}
    message = (data.get('message') or '').strip()
    history = data.get('history', [])

    if not message:
        return jsonify({'error': 'Message is required.'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'reply': 'The AI assistant is not configured yet. Please contact us directly via WhatsApp or the enquiry form.'}), 200

    conn = get_conn()
    try:
        # Safe public context — no PII, no credentials
        courses_rows = conn.execute("""
            SELECT course, COUNT(*) as lesson_count
            FROM lessons WHERE is_published = 1
            GROUP BY course ORDER BY lesson_count DESC
        """).fetchall()

        topics_rows = conn.execute("""
            SELECT topic, COUNT(*) as lesson_count
            FROM lessons WHERE is_published = 1
            GROUP BY topic ORDER BY lesson_count DESC LIMIT 10
        """).fetchall()

        # Pricing: group by course, list plans + amounts
        pricing_rows = conn.execute("""
            SELECT course, plan, amount FROM course_pricing ORDER BY course, amount
        """).fetchall()

        # Instructors: name + bio + subject only — never email/phone/password
        instructor_rows = conn.execute("""
            SELECT name, subject, bio FROM instructors WHERE is_active = 1
        """).fetchall()

        # Custom FAQs from chatbot_knowledge table
        faq_rows = conn.execute("""
            SELECT question, answer FROM chatbot_knowledge WHERE is_active = 1 ORDER BY category
        """).fetchall()

        total_lessons = conn.execute("SELECT COUNT(*) FROM lessons WHERE is_published=1").fetchone()[0]

        # Build context strings
        courses_info = '\n'.join([f"  - {r['course']}: {r['lesson_count']} lesson(s)" for r in courses_rows]) \
                       or '  - Physics Foundation, JEE Mains, JEE Advanced, NEET, EAMCET'
        topics_info  = '\n'.join([f"  - {r['topic']}: {r['lesson_count']} lesson(s)" for r in topics_rows]) \
                       or '  - Mechanics, Thermodynamics, Electromagnetism, Optics, Modern Physics'

        # Group pricing by course
        pricing_map = {}
        for r in pricing_rows:
            pricing_map.setdefault(r['course'], []).append(f"{r['plan']}: ₹{r['amount']}")
        pricing_info = '\n'.join([f"  {c}: {', '.join(plans)}" for c, plans in pricing_map.items()]) \
                       or '  Contact us for current pricing'

        instructors_info = '\n'.join([
            f"  - {r['name']} ({r['subject']})" + (f": {r['bio']}" if r['bio'] else '')
            for r in instructor_rows
        ]) or '  - Experienced Physics faculty'

        faq_info = '\n'.join([f"  Q: {r['question']}\n  A: {r['answer']}" for r in faq_rows]) or ''

    except Exception:
        courses_info  = '  - Physics Foundation, JEE Mains, JEE Advanced, NEET, EAMCET'
        topics_info   = '  - Mechanics, Thermodynamics, Electromagnetism, Optics, Modern Physics'
        pricing_info  = '  Contact us for current pricing'
        instructors_info = '  - Experienced Physics faculty'
        faq_info      = ''
        total_lessons = 'multiple'
    finally:
        conn.close()

    system = f"""You are Priya, a warm and knowledgeable Admissions Advisor at NR AI Orbit Learning Portal — a Physics coaching centre in Hyderabad, India. You help students choose the right course, understand fees, and guide them toward enrolling or booking a free demo.

ACADEMY:
- Location: Hyderabad, India | Specialisation: Physics for JEE Mains, JEE Advanced, NEET, EAMCET, Class 11 & 12
- Total published lessons: {total_lessons}
- Free demo: 45-minute free class — no payment required

COURSES & LESSON COUNT:
{courses_info}

TOPICS COVERED:
{topics_info}

COURSE FEES (₹):
{pricing_info}

INSTRUCTORS:
{instructors_info}

PAYMENT: UPI (GPay, PhonePe, Paytm), debit/credit card, net banking — via PhonePe gateway. Instant course activation on payment.
REFUND: Full refund within 7 days if less than 20% of course content watched. Processed in 5–7 business days.
ENROLLMENT STEPS: Sign Up → choose course & plan → complete payment → instant access.
CONTACT: WhatsApp/call +91 72078 98999 | enquiry form on website.

FREQUENTLY ASKED QUESTIONS:
{faq_info}

NEVER share: any student's personal data, transaction IDs, admin/instructor credentials, API keys, or internal server details.

HOW TO BEHAVE AS PRIYA:
- Warm, encouraging, and professional — like a knowledgeable academic counsellor
- Use **bold** for course names, prices, and key terms
- Use bullet points (lines starting with -) when listing 3+ items, steps, or options
- Ask one focused follow-up question when it helps personalise advice (e.g. "Which exam are you preparing for — JEE, NEET, or EAMCET?" before recommending a course)
- Keep replies concise: 2–4 sentences or a short bullet list. Avoid long paragraphs.
- Proactively mention the free demo or enrollment steps when relevant
- For anything not covered above: "I don't have those details — please WhatsApp us at +91 72078 98999 or use the enquiry form below\""""

    messages = [{'role': m['role'], 'content': m['content']} for m in history[-8:] if m.get('role') in ('user','assistant')]
    messages.append({'role': 'user', 'content': message})

    for model in ['claude-haiku-4-5-20251001', 'claude-3-haiku-20240307']:
        try:
            resp = http_requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={
                    'x-api-key': ANTHROPIC_API_KEY,
                    'anthropic-version': '2023-06-01',
                    'content-type': 'application/json'
                },
                json={'model': model, 'max_tokens': 400,
                      'system': system, 'messages': messages},
                timeout=25
            )
            d = resp.json()
            if resp.ok:
                return jsonify({'reply': d['content'][0]['text']})
            err = d.get('error', {}).get('message', str(resp.status_code))
            print(f'[chat] model={model} status={resp.status_code} error={err}')
            if resp.status_code in (401, 403, 400):
                break  # auth/billing failure — fall through to FAQ fallback
        except Exception as ex:
            print(f'[chat] model={model} exception={ex}')

    # ── Intent-based fallback — pulls live DB data, no API needed ────────────
    conn2 = None
    try:
        conn2 = get_conn()
        msg_l = message.lower()
        reply = None

        if any(k in msg_l for k in ['fee', 'fees', 'price', 'cost', 'how much', 'pricing', 'plan', 'plans', 'amount', 'rupee', 'pay', 'charge', 'money']):
            rows = conn2.execute("SELECT course, plan, amount FROM course_pricing ORDER BY course, amount").fetchall()
            if rows:
                pm = {}
                for r in rows:
                    pm.setdefault(r['course'], []).append(f"{r['plan']}: ₹{r['amount']}")
                lines = '\n'.join([f"- **{c}**: {', '.join(plans)}" for c, plans in list(pm.items())[:6]])
                reply = f"Here are our current course fees:\n\n{lines}\n\nLonger plans give the best value! Which course are you interested in?"

        elif any(k in msg_l for k in ['demo', 'free class', 'trial', 'try before', 'sample']):
            reply = "Yes! We offer a **free 45-minute demo class** — no payment required.\n\nHow to book:\n- Click **Book Free Demo** on the homepage\n- Or WhatsApp us at **+91 72078 98999**\n\nWould you like to know more about any specific course?"

        elif any(k in msg_l for k in ['enroll', 'enrollment', 'sign up', 'join', 'register', 'how to start', 'begin', 'get started', 'access']):
            reply = "Enrolling is quick and easy!\n\n- Click **Sign Up** on the homepage\n- Fill in your details and choose your course & plan\n- Complete payment via UPI, card, or net banking\n- **Instant access** — start watching right away!\n\nWant help choosing the right course?"

        elif any(k in msg_l for k in ['refund', 'cancel', 'money back', 'return']):
            reply = "We offer a **full refund within 7 days** of enrollment, as long as you've watched less than 20% of the course content.\n\nRefunds are processed in 5–7 business days. Full details at **/refund.html**."

        elif any(k in msg_l for k in ['payment', 'upi', 'gpay', 'phonepe', 'paytm', 'card', 'net banking', 'how to pay', 'online payment']):
            reply = "We accept all major payment methods:\n\n- **UPI**: Google Pay, PhonePe, Paytm\n- **Debit / Credit card**\n- **Net banking**\n\nAll payments go through the PhonePe gateway — secure and instant. Course access activates immediately after payment!"

        elif any(k in msg_l for k in ['contact', 'phone', 'whatsapp', 'call', 'reach', 'address', 'location', 'hyderabad', 'where']):
            reply = "You can reach us at:\n\n- **WhatsApp / Call**: +91 72078 98999\n- **Location**: Hyderabad, Telangana\n- **Enquiry form**: available on the homepage\n\nWe typically respond within 30 minutes during working hours!"

        elif any(k in msg_l for k in ['instructor', 'teacher', 'faculty', 'professor', 'who teaches', 'who is']):
            rows = conn2.execute("SELECT name, subject, bio FROM instructors WHERE is_active=1").fetchall()
            if rows:
                lines = '\n'.join([f"- **{r['name']}** ({r['subject']})" + (f" — {r['bio'][:80]}…" if r.get('bio') and len(r['bio']) > 20 else '') for r in rows])
                reply = f"Our faculty:\n\n{lines}\n\nWant to meet them? Book a **free demo class** with no commitment!"
            else:
                reply = "We have experienced Physics faculty specialising in JEE, NEET, and EAMCET. Book a free demo to meet them!"

        elif any(k in msg_l for k in ['course', 'courses', 'offer', 'available', 'jee', 'neet', 'eamcet', 'intermediate', 'foundation', 'class 11', 'class 12', 'which', 'suit', 'recommend', 'best for', 'prepare', 'preparing']):
            rows = conn2.execute("SELECT course, COUNT(*) as cnt FROM lessons WHERE is_published=1 GROUP BY course ORDER BY cnt DESC").fetchall()
            if rows:
                lines = '\n'.join([f"- **{r['course']}** ({r['cnt']} lessons)" for r in rows])
                reply = f"We offer these Physics courses:\n\n{lines}\n\nWhich exam are you preparing for — **JEE, NEET, or EAMCET**? I'll help you pick the right one!"
            else:
                reply = "We offer Physics courses for **JEE Mains, JEE Advanced, NEET, EAMCET, Class 11 & 12**, and a **Physics Foundation** course for beginners.\n\nWhich exam are you preparing for?"

        elif any(k in msg_l for k in ['mobile', 'app', 'phone', 'android', 'iphone', 'install', 'pwa', 'download']):
            reply = "Yes! NR AI Orbit Learning Portal works as a **mobile app** (PWA):\n\n- **Android**: open Chrome → menu → *Add to Home Screen*\n- **iPhone**: open Safari → Share → *Add to Home Screen*\n\nOnce installed it works like a native app — even offline!"

        elif any(k in msg_l for k in ['doubt', 'doubts', 'question', 'help', 'support', 'stuck', 'clear']):
            reply = "Our instructors typically respond to student doubts within **30 minutes** during working hours.\n\nYou can submit doubts directly from your **Student Dashboard** after enrolling. You can also WhatsApp us at **+91 72078 98999** for urgent queries."

        if reply:
            return jsonify({'reply': reply}), 200

        # Last resort: FAQ keyword match (score ≥ 2 to avoid false positives)
        faqs = conn2.execute("SELECT question, answer FROM chatbot_knowledge WHERE is_active=1").fetchall()
        msg_words = set(msg_l.split())
        best_faq, best_score = None, 0
        for faq in faqs:
            q_words = set(faq['question'].lower().split())
            score = len(q_words & msg_words)
            if score > best_score:
                best_score, best_faq = score, faq
        if best_faq and best_score >= 2:
            return jsonify({'reply': best_faq['answer']}), 200

    except Exception as ex:
        print(f'[chat] fallback error={ex}')
    finally:
        if conn2:
            try: conn2.close()
            except: pass

    return jsonify({'reply': "Thanks for your question! For a quick answer, WhatsApp us at **+91 72078 98999** or use the enquiry form below — we respond within 30 minutes!"}), 200


@app.route('/api/chat/health', methods=['GET'])
def chat_health():
    if not ANTHROPIC_API_KEY:
        return jsonify({'ok': False, 'reason': 'ANTHROPIC_API_KEY not set'})
    try:
        resp = http_requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={'x-api-key': ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
            json={'model': 'claude-3-haiku-20240307', 'max_tokens': 5, 'messages': [{'role': 'user', 'content': 'hi'}]},
            timeout=10
        )
        d = resp.json()
        if resp.ok:
            return jsonify({'ok': True, 'model': 'claude-3-haiku-20240307'})
        return jsonify({'ok': False, 'status': resp.status_code, 'error': d.get('error', {}).get('message', '')})
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)})


# ── ADMIN: edit student (full edit) ──────────────────────────────

@app.route('/api/admin/students/<int:sid>', methods=['PATCH'])
def admin_edit_student(sid):
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    data           = request.get_json() or {}
    full_name      = data.get('full_name', '').strip()
    phone          = data.get('phone', '').strip()
    course         = data.get('course', '').strip()
    plan           = data.get('plan', '').strip()
    payment_status = data.get('payment_status', '')
    is_active      = data.get('is_active')

    updates, params = [], []
    if full_name:
        updates.append("full_name = ?"); params.append(full_name)
    if phone:
        conn_chk = get_conn()
        dup = conn_chk.execute("SELECT id FROM students WHERE phone=? AND id!=?", (phone, sid)).fetchone()
        conn_chk.close()
        if dup:
            return jsonify({'error': 'Phone number already used by another student.'}), 409
        updates.append("phone = ?"); params.append(phone)
    if course:
        updates.append("course = ?"); params.append(course)
    if plan:
        updates.append("plan = ?"); params.append(plan)
    if payment_status in ('paid', 'pending', 'failed'):
        updates.append("payment_status = ?"); params.append(payment_status)
    if is_active is not None:
        updates.append("is_active = ?"); params.append(1 if is_active else 0)

    if not updates:
        return jsonify({'error': 'Nothing to update.'}), 400

    conn = get_conn()
    conn.execute(f"UPDATE students SET {', '.join(updates)} WHERE id = ?", params + [sid])
    # When admin marks as paid, flip all pending payments to paid
    if payment_status == 'paid':
        conn.execute(
            "UPDATE payments SET status='paid', updated_at=datetime('now') WHERE student_id=? AND status='pending'",
            (sid,)
        )
    conn.commit()
    row = conn.execute("SELECT id,full_name,email,phone,course,plan,is_active,payment_status,created_at FROM students WHERE id=?", (sid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Student not found.'}), 404
    return jsonify(dict(row))

# ── STUDENT: profile update (RAJ-15) ─────────────────────────────

@app.route('/api/student/profile', methods=['PATCH'])
def student_update_profile():
    session, err_resp, err_code = require_role('student')
    if err_resp:
        return err_resp, err_code

    data         = request.get_json() or {}
    full_name    = data.get('full_name', '').strip()
    phone        = data.get('phone', '').strip()
    cur_pw       = data.get('current_password', '')
    new_pw       = data.get('new_password', '')

    conn = get_conn()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (session['user_id'],)).fetchone()
    if not student:
        conn.close(); return jsonify({'error': 'Student not found.'}), 404

    updates, params = [], []
    if full_name:
        updates.append("full_name = ?"); params.append(full_name)
    if phone:
        existing = conn.execute("SELECT id FROM students WHERE phone = ? AND id != ?", (phone, session['user_id'])).fetchone()
        if existing:
            conn.close(); return jsonify({'error': 'Phone number already in use.'}), 409
        updates.append("phone = ?"); params.append(phone)

    if new_pw:
        if not cur_pw or not bcrypt.checkpw(cur_pw.encode(), student['password'].encode()):
            conn.close(); return jsonify({'error': 'Current password is incorrect.'}), 400
        if len(new_pw) < 8:
            conn.close(); return jsonify({'error': 'New password must be at least 8 characters.'}), 400
        updates.append("password = ?"); params.append(bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode())

    if updates:
        params.append(session['user_id'])
        conn.execute(f"UPDATE students SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()

    updated = conn.execute("SELECT id, full_name, email, phone, course, plan FROM students WHERE id = ?", (session['user_id'],)).fetchone()
    conn.close()
    return jsonify({'message': 'Profile updated.', 'student': dict(updated)})

# ── STUDENT: payment history (RAJ-20) ────────────────────────────

@app.route('/api/student/payments', methods=['GET'])
def student_payments():
    session, err_resp, err_code = require_role('student')
    if err_resp:
        return err_resp, err_code

    conn = get_conn()
    rows = conn.execute(
        "SELECT id, merchant_transaction_id, amount, status, created_at, updated_at FROM payments WHERE student_id = ? ORDER BY created_at DESC",
        (session['user_id'],)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ── STUDENT / INSTRUCTOR: Doubts Q&A (RAJ-14 / RAJ-25) ───────────

@app.route('/api/student/doubts', methods=['POST'])
def student_post_doubt():
    session, err_resp, err_code = require_role('student')
    if err_resp:
        return err_resp, err_code

    data      = request.get_json() or {}
    lesson_id = data.get('lesson_id')
    question  = (data.get('question') or '').strip()
    if not question:
        return jsonify({'error': 'Question is required.'}), 400

    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO doubts (student_id, lesson_id, question) VALUES (?, ?, ?)",
        (session['user_id'], lesson_id or None, question)
    )
    conn.commit()
    doubt_id = cur.lastrowid
    conn.close()
    return jsonify({'success': True, 'id': doubt_id}), 201

@app.route('/api/student/doubts', methods=['GET'])
def student_get_doubts():
    session, err_resp, err_code = require_role('student')
    if err_resp:
        return err_resp, err_code

    conn = get_conn()
    rows = conn.execute("""
        SELECT d.id, d.lesson_id, l.title as lesson_title,
               d.question, d.answer, d.status, d.created_at, d.answered_at
        FROM doubts d
        LEFT JOIN lessons l ON l.id = d.lesson_id
        WHERE d.student_id = ?
        ORDER BY d.created_at DESC
    """, (session['user_id'],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/instructor/doubts', methods=['GET'])
def instructor_get_doubts():
    session, err_resp, err_code = require_role('instructor')
    if err_resp:
        return err_resp, err_code

    conn = get_conn()
    rows = conn.execute("""
        SELECT d.id, d.lesson_id, l.title as lesson_title,
               d.question, d.answer, d.status, d.created_at, d.answered_at,
               s.full_name as student_name
        FROM doubts d
        LEFT JOIN lessons l ON l.id = d.lesson_id
        LEFT JOIN students s ON s.id = d.student_id
        WHERE l.instructor_id = ? OR d.lesson_id IS NULL
        ORDER BY d.status ASC, d.created_at DESC
    """, (session['user_id'],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/instructor/doubts/<int:did>/answer', methods=['PATCH'])
def instructor_answer_doubt(did):
    session, err_resp, err_code = require_role('instructor')
    if err_resp:
        return err_resp, err_code

    data   = request.get_json() or {}
    answer = (data.get('answer') or '').strip()
    if not answer:
        return jsonify({'error': 'Answer is required.'}), 400

    conn = get_conn()
    conn.execute("""
        UPDATE doubts SET answer = ?, status = 'answered',
               answered_by = ?, answered_at = datetime('now')
        WHERE id = ?
    """, (answer, session['user_id'], did))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ── ADMIN: bulk student actions (RAJ-29) ─────────────────────────

@app.route('/api/admin/students/bulk-revoke', methods=['PATCH'])
def admin_bulk_revoke():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    ids = (request.get_json() or {}).get('ids', [])
    if not ids:
        return jsonify({'error': 'No ids provided.'}), 400

    conn = get_conn()
    conn.execute(f"UPDATE students SET is_active = 0 WHERE id IN ({','.join('?'*len(ids))})", ids)
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'updated': len(ids)})

@app.route('/api/admin/students/bulk', methods=['DELETE'])
def admin_bulk_delete():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    ids = (request.get_json() or {}).get('ids', [])
    if not ids:
        return jsonify({'error': 'No ids provided.'}), 400

    conn = get_conn()
    conn.execute(f"DELETE FROM students WHERE id IN ({','.join('?'*len(ids))})", ids)
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'deleted': len(ids)})

# ── ADMIN: create instructor (RAJ-33) ─────────────────────────────

@app.route('/api/admin/instructors', methods=['POST'])
def admin_create_instructor():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    data    = request.get_json() or {}
    name    = (data.get('name') or '').strip()
    email   = (data.get('email') or '').strip().lower()
    phone   = (data.get('phone') or '').strip()
    subject = (data.get('subject') or 'Physics').strip()
    password= (data.get('password') or '')
    bio     = (data.get('bio') or '').strip()

    if not all([name, email, password]):
        return jsonify({'error': 'name, email, and password are required.'}), 400
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters.'}), 400

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO instructors (name, email, phone, subject, password, bio) VALUES (?,?,?,?,?,?)",
            (name, email, phone or None, subject, hashed, bio or None)
        )
        conn.commit()
        iid = cur.lastrowid
        row = conn.execute("SELECT id,name,email,phone,subject,bio,is_active,created_at FROM instructors WHERE id=?", (iid,)).fetchone()
        conn.close()
        return jsonify(dict(row)), 201
    except Exception as e:
        conn.close()
        if 'UNIQUE' in str(e):
            return jsonify({'error': 'Email already in use.'}), 409
        return jsonify({'error': str(e)}), 500

# ── INSTRUCTOR: analytics (RAJ-24) ───────────────────────────────

@app.route('/api/instructor/analytics', methods=['GET'])
def instructor_analytics():
    session, err_resp, err_code = require_role('instructor')
    if err_resp:
        return err_resp, err_code

    conn = get_conn()
    lessons = conn.execute(
        "SELECT id, title, topic FROM lessons WHERE instructor_id = ? AND is_published = 1",
        (session['user_id'],)
    ).fetchall()
    lesson_ids = [l['id'] for l in lessons]

    progress_rows = []
    if lesson_ids:
        ph = ','.join('?' * len(lesson_ids))
        progress_rows = conn.execute(f"""
            SELECT lesson_id,
                   COUNT(DISTINCT student_id)       as view_count,
                   SUM(watched_seconds)             as total_watch_seconds,
                   SUM(CASE WHEN completed=1 THEN 1 ELSE 0 END) as completions
            FROM lesson_progress
            WHERE lesson_id IN ({ph})
            GROUP BY lesson_id
        """, lesson_ids).fetchall()

    progress_map = {r['lesson_id']: dict(r) for r in progress_rows}
    total_students = conn.execute("SELECT COUNT(*) FROM students WHERE is_active=1").fetchone()[0]
    conn.close()

    result = []
    for l in lessons:
        p = progress_map.get(l['id'], {'view_count':0,'total_watch_seconds':0,'completions':0})
        result.append({
            'lesson_id':   l['id'],
            'title':       l['title'],
            'topic':       l['topic'],
            'views':       p['view_count'],
            'watch_hours': round((p['total_watch_seconds'] or 0) / 3600, 1),
            'completions': p['completions'],
            'completion_rate': round(p['completions'] / max(p['view_count'],1) * 100)
        })
    return jsonify({'lessons': result, 'total_active_students': total_students})

# ── INSTRUCTOR: student roster (RAJ-28) ──────────────────────────

@app.route('/api/instructor/students', methods=['GET'])
def instructor_students():
    session, err_resp, err_code = require_role('instructor')
    if err_resp:
        return err_resp, err_code

    conn = get_conn()
    rows = conn.execute("""
        SELECT s.id, s.full_name, s.email, s.phone, s.course, s.plan,
               s.is_active, s.payment_status, s.created_at,
               COUNT(DISTINCT lp.lesson_id) as lessons_watched
        FROM students s
        LEFT JOIN lesson_progress lp ON lp.student_id = s.id
        WHERE s.is_active = 1
        GROUP BY s.id
        ORDER BY s.full_name
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ── ADMIN: enquiry notes (RAJ-34) ────────────────────────────────

@app.route('/api/admin/enquiries/<int:eid>/notes', methods=['PATCH'])
def admin_enquiry_note(eid):
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    data   = request.get_json() or {}
    notes  = data.get('notes', '')
    status = data.get('status')

    conn = get_conn()
    cols = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='enquiries'"
    ).fetchall()
    col_names = [c['column_name'] for c in cols]
    if 'notes' not in col_names:
        conn.execute("ALTER TABLE enquiries ADD COLUMN notes TEXT")
        conn.commit()

    updates, params = ["notes = ?"], [notes]
    if status:
        updates.append("status = ?"); params.append(status)
    params.append(eid)
    conn.execute(f"UPDATE enquiries SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ── ADMIN: lesson bulk actions (RAJ-27) ──────────────────────────

@app.route('/api/admin/lessons/bulk', methods=['PATCH'])
def admin_bulk_lessons():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    data   = request.get_json() or {}
    ids    = data.get('ids', [])
    action = data.get('action', '')
    if not ids or action not in ('publish', 'unpublish', 'delete'):
        return jsonify({'error': 'ids and action (publish/unpublish/delete) required.'}), 400

    ph = ','.join('?' * len(ids))
    conn = get_conn()
    if action == 'delete':
        conn.execute(f"DELETE FROM lessons WHERE id IN ({ph})", ids)
    else:
        val = 1 if action == 'publish' else 0
        conn.execute(f"UPDATE lessons SET is_published = ? WHERE id IN ({ph})", [val]+list(ids))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'affected': len(ids)})

# ── ADMIN: discount codes (RAJ-22) ───────────────────────────────

@app.route('/api/admin/discount-codes', methods=['GET'])
def admin_get_discount_codes():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    conn = get_conn()
    rows = conn.execute("SELECT * FROM discount_codes ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/discount-codes', methods=['POST'])
def admin_create_discount_code():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    data    = request.get_json() or {}
    code    = (data.get('code') or '').strip().upper()
    pct     = int(data.get('discount_percent', 0))
    max_use = int(data.get('max_uses', 100))
    expires = data.get('expires_at', '')
    if not code or not (1 <= pct <= 100):
        return jsonify({'error': 'code and discount_percent (1-100) required.'}), 400

    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO discount_codes (code, discount_percent, max_uses, expires_at) VALUES (?,?,?,?)",
            (code, pct, max_use, expires or None)
        )
        conn.commit()
    except Exception as e:
        conn.close()
        if 'UNIQUE' in str(e):
            return jsonify({'error': 'Code already exists.'}), 409
        return jsonify({'error': str(e)}), 500
    conn.close()
    return jsonify({'success': True})

@app.route('/api/apply-discount', methods=['POST'])
def apply_discount():
    session, err_resp, err_code = require_role('student')
    if err_resp:
        return err_resp, err_code

    code = (request.get_json() or {}).get('code', '').strip().upper()
    if not code:
        return jsonify({'error': 'Code required.'}), 400

    conn = get_conn()
    row = conn.execute("""
        SELECT * FROM discount_codes
        WHERE code = ? AND is_active = 1
          AND (expires_at IS NULL OR expires_at > datetime('now'))
          AND times_used < max_uses
    """, (code,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Invalid or expired discount code.'}), 404
    return jsonify({'discount_percent': row['discount_percent'], 'code': code})

# ── Sales Agent ──────────────────────────────────────────────────

@app.route('/api/admin/sales/leads', methods=['GET'])
def sales_leads_list():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    conn = get_conn()
    status   = request.args.get('status', '')
    type_    = request.args.get('type', '')
    location = request.args.get('location', '')
    search   = request.args.get('search', '')
    sql    = "SELECT * FROM sales_leads WHERE 1=1"
    params = []
    if status:   sql += " AND status = ?";   params.append(status)
    if type_:    sql += " AND type = ?";     params.append(type_)
    if location: sql += " AND location = ?"; params.append(location)
    if search:
        sql += " AND (name ILIKE ? OR phone ILIKE ? OR email ILIKE ?)"
        params += [f'%{search}%', f'%{search}%', f'%{search}%']
    sql += " ORDER BY created_at DESC"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return jsonify(rows)

@app.route('/api/admin/sales/leads', methods=['POST'])
def sales_leads_create():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    d = request.get_json() or {}
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO sales_leads (name, type, phone, email, location, course_interest, status, notes) VALUES (?,?,?,?,?,?,?,?)",
        (d.get('name',''), d.get('type','Student'), d.get('phone',''), d.get('email',''),
         d.get('location',''), d.get('course_interest',''), d.get('status','New'), d.get('notes',''))
    )
    lid = cur.lastrowid
    conn.commit()
    row = dict(conn.execute("SELECT * FROM sales_leads WHERE id=?", (lid,)).fetchone())
    conn.close()
    return jsonify(row), 201

@app.route('/api/admin/sales/leads/<int:lid>', methods=['PUT'])
def sales_leads_update(lid):
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    d = request.get_json() or {}
    conn = get_conn()
    conn.execute(
        "UPDATE sales_leads SET name=?,type=?,phone=?,email=?,location=?,course_interest=?,status=?,notes=?,updated_at=datetime('now') WHERE id=?",
        (d.get('name',''), d.get('type','Student'), d.get('phone',''), d.get('email',''),
         d.get('location',''), d.get('course_interest',''), d.get('status','New'), d.get('notes',''), lid)
    )
    conn.commit()
    row = dict(conn.execute("SELECT * FROM sales_leads WHERE id=?", (lid,)).fetchone())
    conn.close()
    return jsonify(row)

@app.route('/api/admin/sales/leads/<int:lid>', methods=['DELETE'])
def sales_leads_delete(lid):
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    conn = get_conn()
    conn.execute("DELETE FROM sales_leads WHERE id=?", (lid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/admin/sales/orders', methods=['GET'])
def sales_orders_list():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    conn = get_conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM sales_orders ORDER BY created_at DESC").fetchall()]
    conn.close()
    return jsonify(rows)

@app.route('/api/admin/sales/orders', methods=['POST'])
def sales_orders_create():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    d = request.get_json() or {}
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO sales_orders (lead_id, lead_name, course_name, amount, order_date, status, notes) VALUES (?,?,?,?,?,?,?)",
        (d.get('lead_id') or None, d.get('lead_name',''), d.get('course_name',''),
         float(d.get('amount', 0)), d.get('order_date',''), d.get('status','Pending'), d.get('notes',''))
    )
    oid = cur.lastrowid
    conn.commit()
    row = dict(conn.execute("SELECT * FROM sales_orders WHERE id=?", (oid,)).fetchone())
    conn.close()
    return jsonify(row), 201

@app.route('/api/admin/sales/orders/<int:oid>', methods=['PUT'])
def sales_orders_update(oid):
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    d = request.get_json() or {}
    conn = get_conn()
    conn.execute(
        "UPDATE sales_orders SET lead_name=?,course_name=?,amount=?,order_date=?,status=?,notes=? WHERE id=?",
        (d.get('lead_name',''), d.get('course_name',''), float(d.get('amount',0)),
         d.get('order_date',''), d.get('status','Pending'), d.get('notes',''), oid)
    )
    conn.commit()
    row = dict(conn.execute("SELECT * FROM sales_orders WHERE id=?", (oid,)).fetchone())
    conn.close()
    return jsonify(row)

@app.route('/api/admin/sales/orders/<int:oid>', methods=['DELETE'])
def sales_orders_delete(oid):
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    conn = get_conn()
    conn.execute("DELETE FROM sales_orders WHERE id=?", (oid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/admin/sales/outreach', methods=['GET'])
def sales_outreach_list():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    conn = get_conn()
    lead_id = request.args.get('lead_id', '')
    sql = "SELECT o.*, l.name AS lead_name FROM sales_outreach o LEFT JOIN sales_leads l ON o.lead_id=l.id WHERE 1=1"
    params = []
    if lead_id: sql += " AND o.lead_id=?"; params.append(int(lead_id))
    sql += " ORDER BY o.created_at DESC"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return jsonify(rows)

@app.route('/api/admin/sales/outreach', methods=['POST'])
def sales_outreach_create():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    d = request.get_json() or {}
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO sales_outreach (lead_id, channel, message, delivery_status) VALUES (?,?,?,?)",
        (d.get('lead_id'), d.get('channel','WhatsApp'), d.get('message',''), d.get('delivery_status','Sent'))
    )
    rid = cur.lastrowid
    conn.commit()
    row = dict(conn.execute(
        "SELECT o.*, l.name AS lead_name FROM sales_outreach o LEFT JOIN sales_leads l ON o.lead_id=l.id WHERE o.id=?",
        (rid,)
    ).fetchone())
    conn.close()
    return jsonify(row), 201

SALES_STATUS_NEXT = {
    'New':          'Contacted',
    'Contacted':    'Negotiating',
    'Negotiating':  'Order Placed',
    'Order Placed': 'Order Placed',
}

def _sales_send_email(lead, subject, message_text):
    """Send a plain outreach email to a sales lead using existing SMTP."""
    if not lead.get('email'):
        return False, 'No email address on lead'
    body_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
      <p style="color:#333;line-height:1.6">{message_text.replace(chr(10), '<br>')}</p>
      <hr style="border:none;border-top:1px solid #eee;margin:24px 0"/>
      <p style="font-size:12px;color:#999">
        NR AI Orbit Learning Portal &nbsp;·&nbsp; Hyderabad, Telangana<br/>
        To unsubscribe, reply with "STOP".
      </p>
    </div>"""
    try:
        send_email(lead['email'], subject, body_html)
        return True, 'sent'
    except Exception as ex:
        return False, str(ex)


@app.route('/api/admin/sales/outreach/<int:oid>/send', methods=['POST'])
def sales_outreach_send(oid):
    """Send the email for an outreach log entry and move lead to Contacted."""
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    conn = get_conn()
    entry = conn.execute("SELECT * FROM sales_outreach WHERE id=?", (oid,)).fetchone()
    if not entry:
        conn.close()
        return jsonify({'error': 'Outreach not found'}), 404
    entry = dict(entry)
    lead  = conn.execute("SELECT * FROM sales_leads WHERE id=?", (entry['lead_id'],)).fetchone()
    if not lead:
        conn.close()
        return jsonify({'error': 'Lead not found'}), 404
    lead = dict(lead)
    ok, reason = _sales_send_email(lead, f"Physics courses at NR AI Orbit — {lead['name']}", entry['message'])
    new_status = 'Sent' if ok else entry['delivery_status']
    conn.execute("UPDATE sales_outreach SET delivery_status=? WHERE id=?", (new_status, oid))
    if ok and lead['status'] == 'New':
        conn.execute(
            "UPDATE sales_leads SET status='Contacted', updated_at=datetime('now') WHERE id=?",
            (lead['id'],)
        )
        lead['status'] = 'Contacted'
    conn.commit()
    updated_entry = dict(conn.execute(
        "SELECT o.*, l.name AS lead_name FROM sales_outreach o LEFT JOIN sales_leads l ON o.lead_id=l.id WHERE o.id=?",
        (oid,)
    ).fetchone())
    updated_lead = dict(conn.execute("SELECT * FROM sales_leads WHERE id=?", (lead['id'],)).fetchone())
    conn.close()
    return jsonify({'outreach': updated_entry, 'lead': updated_lead, 'email_sent': ok, 'reason': reason})


@app.route('/api/admin/sales/leads/<int:lid>/respond', methods=['POST'])
def sales_lead_respond(lid):
    """Log a response from the lead, advance status, AI-draft + send follow-up."""
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    conn = get_conn()
    lead = conn.execute("SELECT * FROM sales_leads WHERE id=?", (lid,)).fetchone()
    if not lead:
        conn.close()
        return jsonify({'error': 'Lead not found'}), 404
    lead = dict(lead)

    # 1 — advance status
    next_status = SALES_STATUS_NEXT.get(lead['status'], lead['status'])
    conn.execute(
        "UPDATE sales_leads SET status=?, updated_at=datetime('now') WHERE id=?",
        (next_status, lid)
    )
    lead['status'] = next_status

    # 2 — log the response
    conn.execute(
        "INSERT INTO sales_outreach (lead_id, channel, message, delivery_status) VALUES (?,?,?,?)",
        (lid, 'Email', f"[Response received from {lead['name']}]", 'Read')
    )
    conn.commit()

    # 3 — AI-draft follow-up if not at final stage
    follow_up = None
    email_sent = False
    if next_status != 'Order Placed' and ANTHROPIC_API_KEY and lead.get('email'):
        stage_context = {
            'Contacted':   'They showed interest. Now pitch specific course details, pricing, and offer a demo.',
            'Negotiating': 'They are seriously considering. Address objections, offer a discount or payment plan.',
        }.get(next_status, 'Continue the conversation.')
        prompt = f"""You are a sales assistant for NR AI Orbit Learning Portal, a physics coaching academy.

The lead has responded and their status is now "{next_status}". Write a follow-up email.

Lead: {lead['name']} | Course: {lead['course_interest'] or 'Physics'} | Location: {lead['location'] or 'AP/TS'}
Stage context: {stage_context}

Write a short, warm follow-up email (3-4 sentences). No subject line. Address them by first name. Be helpful and specific. Under 100 words."""
        try:
            resp = http_requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={'x-api-key': ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
                json={'model': 'claude-haiku-4-5-20251001', 'max_tokens': 200,
                      'messages': [{'role': 'user', 'content': prompt}]},
                timeout=20
            )
            if resp.ok:
                follow_up = resp.json()['content'][0]['text'].strip()
                ok, _ = _sales_send_email(lead, f"Following up — {lead['course_interest'] or 'Physics'} at NR AI Orbit", follow_up)
                email_sent = ok
                status = 'Sent' if ok else 'Draft'
                cur = conn.execute(
                    "INSERT INTO sales_outreach (lead_id, channel, message, delivery_status) VALUES (?,?,?,?)",
                    (lid, 'Email', follow_up, status)
                )
                conn.commit()
        except Exception:
            pass

    updated_lead = dict(conn.execute("SELECT * FROM sales_leads WHERE id=?", (lid,)).fetchone())
    conn.close()
    return jsonify({
        'lead': updated_lead,
        'follow_up_drafted': follow_up is not None,
        'follow_up_sent': email_sent,
        'new_status': next_status
    })


@app.route('/api/admin/sales/sync-enquiries', methods=['POST'])
def sales_sync_enquiries():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    conn = get_conn()
    enquiries = conn.execute(
        "SELECT * FROM enquiries ORDER BY created_at DESC"
    ).fetchall()
    created = []
    skipped = 0
    for e in enquiries:
        phone = (e['phone'] or '').strip()
        email = (e['email'] or '').strip()
        if not phone and not email:
            skipped += 1
            continue
        existing = None
        if phone:
            existing = conn.execute(
                "SELECT id FROM sales_leads WHERE phone = ?", (phone,)
            ).fetchone()
        if not existing and email:
            existing = conn.execute(
                "SELECT id FROM sales_leads WHERE email = ?", (email,)
            ).fetchone()
        if existing:
            skipped += 1
            continue
        cur = conn.execute(
            "INSERT INTO sales_leads (name, type, phone, email, location, course_interest, status, notes) VALUES (?,?,?,?,?,?,?,?)",
            (e['full_name'], 'Student', phone, email, '', e['course'] or '', 'New', e['message'] or '')
        )
        lid = cur.lastrowid
        conn.commit()
        row = dict(conn.execute("SELECT * FROM sales_leads WHERE id=?", (lid,)).fetchone())
        created.append(row)
    conn.close()
    return jsonify({'created': created, 'created_count': len(created), 'skipped': skipped})


@app.route('/api/admin/sales/draft-message', methods=['POST'])
def sales_draft_message():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'ANTHROPIC_API_KEY not set'}), 503
    d = request.get_json() or {}
    lead_id = d.get('lead_id')
    channel = d.get('channel', 'WhatsApp')
    conn = get_conn()
    lead = conn.execute("SELECT * FROM sales_leads WHERE id=?", (lead_id,)).fetchone()
    conn.close()
    if not lead:
        return jsonify({'error': 'Lead not found'}), 404
    lead = dict(lead)
    first_name = lead['name'].split()[0]
    channel_style = {
        'WhatsApp': 'casual and warm WhatsApp message (under 80 words)',
        'Email':    'professional email (subject line + 3-4 sentences)',
        'SMS':      'brief SMS (under 40 words, no links)',
    }.get(channel, 'short message')
    prompt = f"""You are a sales assistant for NR AI Orbit Learning Portal, a physics coaching academy in Andhra Pradesh/Telangana, India.

Write a {channel_style} to follow up with this lead:
- Name: {lead['name']} (address as {first_name})
- Type: {lead['type']}
- Course Interest: {lead['course_interest'] or 'Physics'}
- Location: {lead['location'] or 'Andhra Pradesh'}
- Current Status: {lead['status']}
- Notes: {lead['notes'] or 'None'}

Guidelines:
- Warm, friendly, not pushy
- Mention their specific course interest
- Offer a free demo class or to answer questions
- End with a soft call to action (reply / call / WhatsApp)
- Use Indian English naturally
- No generic filler phrases like "I hope this message finds you well"

Output only the message text, nothing else."""
    try:
        resp = http_requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json'
            },
            json={
                'model': 'claude-haiku-4-5-20251001',
                'max_tokens': 300,
                'messages': [{'role': 'user', 'content': prompt}]
            },
            timeout=30
        )
        data = resp.json()
        if resp.ok:
            return jsonify({'message': data['content'][0]['text'].strip()})
        return jsonify({'error': data.get('error', {}).get('message', 'AI request failed')}), 502
    except Exception as ex:
        return jsonify({'error': str(ex)}), 503


@app.route('/api/admin/sales/run-all-new', methods=['POST'])
def sales_run_all_new():
    """Draft + send an outreach email for every lead with status='New'."""
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    conn = get_conn()
    new_leads = [dict(r) for r in conn.execute(
        "SELECT * FROM sales_leads WHERE status='New' ORDER BY created_at ASC"
    ).fetchall()]
    conn.close()
    processed, emails_sent, errors = [], 0, []
    for lead in new_leads:
        first_name = lead['name'].split()[0]
        channel = 'Email' if lead.get('email') else 'WhatsApp'
        channel_style = {
            'WhatsApp': 'casual and warm WhatsApp message (under 80 words)',
            'Email':    'professional email (subject line + 3-4 sentences)',
        }.get(channel, 'short message')
        prompt = f"""You are a sales assistant for NR AI Orbit Learning Portal, a physics coaching academy in Andhra Pradesh/Telangana, India.

Write a {channel_style} to follow up with this lead:
- Name: {lead['name']} (address as {first_name})
- Type: {lead.get('type','Student')}
- Course Interest: {lead.get('course_interest') or 'Physics'}
- Location: {lead.get('location') or 'Andhra Pradesh'}
- Notes: {lead.get('notes') or 'None'}

Guidelines:
- Warm, friendly, not pushy
- Mention their specific course interest
- Offer a free demo class or to answer questions
- End with a soft call to action (reply / call / WhatsApp)
- Use Indian English naturally
- No generic filler phrases

Output only the message text, nothing else."""
        try:
            resp = http_requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={
                    'x-api-key': ANTHROPIC_API_KEY,
                    'anthropic-version': '2023-06-01',
                    'content-type': 'application/json'
                },
                json={'model': 'claude-haiku-4-5-20251001', 'max_tokens': 300,
                      'messages': [{'role': 'user', 'content': prompt}]},
                timeout=30
            )
            data = resp.json()
            if not resp.ok:
                errors.append({'lead_id': lead['id'], 'error': 'AI draft failed'})
                continue
            message = data['content'][0]['text'].strip()
        except Exception as ex:
            errors.append({'lead_id': lead['id'], 'error': str(ex)})
            continue

        conn = get_conn()
        cur = conn.execute(
            "INSERT INTO sales_outreach (lead_id, channel, message, delivery_status) VALUES (?,?,?,?)",
            (lead['id'], channel, message, 'Draft')
        )
        oid = cur.lastrowid
        conn.commit()
        conn.close()

        email_sent = False
        if lead.get('email'):
            email_sent, _ = _sales_send_email(lead, f"Invitation: {lead.get('course_interest','Physics')} at NR AI Orbit", message)
            conn = get_conn()
            conn.execute(
                "UPDATE sales_outreach SET delivery_status=? WHERE id=?",
                ('Sent' if email_sent else 'Failed', oid)
            )
            conn.execute(
                "UPDATE sales_leads SET status='Contacted', updated_at=datetime('now') WHERE id=?",
                (lead['id'],)
            )
            conn.commit()
            lead_row = dict(conn.execute("SELECT * FROM sales_leads WHERE id=?", (lead['id'],)).fetchone())
            conn.close()
            if email_sent:
                emails_sent += 1
        else:
            lead_row = lead

        processed.append({'lead': lead_row, 'outreach_id': oid, 'email_sent': email_sent})

    return jsonify({
        'processed': processed,
        'processed_count': len(processed),
        'emails_sent': emails_sent,
        'errors': errors
    })


@app.route('/api/admin/sales/follow-up-stale', methods=['POST'])
def sales_follow_up_stale():
    """Auto-send follow-up reminders to leads stuck in Contacted for 2+ days.
    Guards: skip if already emailed today OR last email was a sent follow-up
    awaiting response (no duplicate until lead replies).
    """
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    conn = get_conn()
    stale_leads = [dict(r) for r in conn.execute(
        "SELECT * FROM sales_leads WHERE status='Contacted' AND updated_at < datetime('now', '-2 days')"
    ).fetchall()]

    processed, emails_sent, errors, skipped_no_reply = [], 0, [], 0
    for lead in stale_leads:
        # Guard 1 — already emailed this lead today
        emailed_today = conn.execute(
            "SELECT id FROM sales_outreach WHERE lead_id=? AND channel='Email' "
            "AND DATE(created_at)=DATE(datetime('now'))",
            (lead['id'],)
        ).fetchone()
        if emailed_today:
            skipped_no_reply += 1
            continue

        # Guard 2 — last email was a sent follow-up with no response since
        last_outreach = conn.execute(
            "SELECT * FROM sales_outreach WHERE lead_id=? AND channel='Email' "
            "ORDER BY created_at DESC LIMIT 1",
            (lead['id'],)
        ).fetchone()
        if last_outreach:
            last = dict(last_outreach)
            is_sent_followup = last['delivery_status'] == 'Sent' and not last['message'].startswith('[Response received')
            if is_sent_followup:
                skipped_no_reply += 1
                continue

        if not lead.get('email'):
            errors.append({'lead_id': lead['id'], 'error': 'No email address'})
            continue

        first_name = lead['name'].split()[0]
        prompt = f"""You are a sales assistant for NR AI Orbit Learning Portal.

Write a brief, friendly reminder email to {lead['name']} (address as {first_name}) who showed interest in {lead.get('course_interest') or 'our physics courses'} but hasn't responded to our earlier message.

- Keep it under 3 sentences
- Warm and non-pushy
- Mention we're happy to answer questions or schedule a free demo
- Use Indian English naturally

Output only the email text, nothing else."""
        try:
            resp = http_requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={'x-api-key': ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
                json={'model': 'claude-haiku-4-5-20251001', 'max_tokens': 200,
                      'messages': [{'role': 'user', 'content': prompt}]},
                timeout=30
            )
            data = resp.json()
            if not resp.ok:
                errors.append({'lead_id': lead['id'], 'error': 'AI draft failed'})
                continue
            message = data['content'][0]['text'].strip()
        except Exception as ex:
            errors.append({'lead_id': lead['id'], 'error': str(ex)})
            continue

        email_sent, _ = _sales_send_email(
            lead,
            f"Following up: {lead.get('course_interest','Physics')} at NR AI Orbit",
            message
        )
        cur = conn.execute(
            "INSERT INTO sales_outreach (lead_id, channel, message, delivery_status) VALUES (?,?,?,?)",
            (lead['id'], 'Email', message, 'Sent' if email_sent else 'Failed')
        )
        oid = cur.lastrowid
        conn.execute(
            "UPDATE sales_leads SET updated_at=datetime('now') WHERE id=?",
            (lead['id'],)
        )
        conn.commit()

        if email_sent:
            emails_sent += 1
        processed.append({'lead_id': lead['id'], 'outreach_id': oid, 'email_sent': email_sent})

    conn.close()
    return jsonify({
        'processed': processed,
        'processed_count': len(processed),
        'emails_sent': emails_sent,
        'skipped_awaiting_reply': skipped_no_reply,
        'errors': errors
    })


@app.route('/api/admin/sales/send-daily-report', methods=['POST'])
def sales_send_daily_report():
    """Email admin a daily summary of agent activity."""
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code

    # Get admin email
    admin_id = session['user_id'] if isinstance(session, dict) else None
    conn = get_conn()
    admin = conn.execute("SELECT email, name FROM admins WHERE id=?", (admin_id,)).fetchone() if admin_id else None
    to_addr = dict(admin)['email'] if admin else FROM_EMAIL
    if not to_addr:
        conn.close()
        return jsonify({'error': 'No admin email found'}), 400

    from datetime import date as _date
    today = _date.today().isoformat()

    new_leads    = conn.execute("SELECT COUNT(*) FROM sales_leads WHERE DATE(created_at)=?", (today,)).fetchone()[0]
    emails_sent  = conn.execute("SELECT COUNT(*) FROM sales_outreach WHERE channel='Email' AND delivery_status='Sent' AND DATE(created_at)=?", (today,)).fetchone()[0]
    orders_today = conn.execute("SELECT COUNT(*) FROM sales_orders WHERE DATE(created_at)=?", (today,)).fetchone()[0]
    revenue_today = conn.execute("SELECT COALESCE(SUM(amount),0) FROM sales_orders WHERE DATE(created_at)=? AND status!='Cancelled'", (today,)).fetchone()[0]

    pipeline = {}
    for s in ['New', 'Contacted', 'Negotiating', 'Order Placed']:
        pipeline[s] = conn.execute("SELECT COUNT(*) FROM sales_leads WHERE status=?", (s,)).fetchone()[0]

    total_leads   = conn.execute("SELECT COUNT(*) FROM sales_leads").fetchone()[0]
    total_revenue = conn.execute("SELECT COALESCE(SUM(amount),0) FROM sales_orders WHERE status!='Cancelled'").fetchone()[0]
    conn.close()

    conversion = round((pipeline['Order Placed'] / total_leads * 100) if total_leads else 0, 1)

    body_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;background:#0a0a12;color:#f0f0f5;border-radius:12px;overflow:hidden">
      <div style="background:linear-gradient(135deg,#FF6600,#FF4400);padding:24px 28px">
        <h1 style="margin:0;font-size:1.3rem;font-weight:900;color:#fff">🤖 Sales Agent — Daily Report</h1>
        <p style="margin:4px 0 0;font-size:.85rem;color:rgba(255,255,255,.75)">{today} · NR AI Orbit Learning Portal</p>
      </div>
      <div style="padding:24px 28px">
        <h2 style="font-size:.9rem;font-weight:700;color:#FF8800;text-transform:uppercase;letter-spacing:.06em;margin:0 0 14px">Today's Activity</h2>
        <table style="width:100%;border-collapse:collapse">
          <tr><td style="padding:8px 0;color:rgba(255,255,255,.6);font-size:.85rem">New Leads</td><td style="text-align:right;font-weight:800;color:#fff;font-size:1rem">{new_leads}</td></tr>
          <tr><td style="padding:8px 0;color:rgba(255,255,255,.6);font-size:.85rem">Emails Sent</td><td style="text-align:right;font-weight:800;color:#22c55e;font-size:1rem">{emails_sent}</td></tr>
          <tr><td style="padding:8px 0;color:rgba(255,255,255,.6);font-size:.85rem">Orders Placed</td><td style="text-align:right;font-weight:800;color:#FF8800;font-size:1rem">{orders_today}</td></tr>
          <tr><td style="padding:8px 0;color:rgba(255,255,255,.6);font-size:.85rem">Revenue Today</td><td style="text-align:right;font-weight:800;color:#FFAA00;font-size:1rem">₹{float(revenue_today):,.0f}</td></tr>
        </table>
        <hr style="border:none;border-top:1px solid rgba(255,255,255,.1);margin:18px 0"/>
        <h2 style="font-size:.9rem;font-weight:700;color:#FF8800;text-transform:uppercase;letter-spacing:.06em;margin:0 0 14px">Pipeline</h2>
        <table style="width:100%;border-collapse:collapse">
          {''.join(f'<tr><td style="padding:6px 0;color:rgba(255,255,255,.6);font-size:.85rem">{s}</td><td style="text-align:right;font-weight:700;color:#fff">{pipeline[s]}</td></tr>' for s in ['New','Contacted','Negotiating','Order Placed'])}
        </table>
        <hr style="border:none;border-top:1px solid rgba(255,255,255,.1);margin:18px 0"/>
        <table style="width:100%;border-collapse:collapse">
          <tr><td style="color:rgba(255,255,255,.6);font-size:.85rem">Total Leads</td><td style="text-align:right;color:#fff;font-weight:700">{total_leads}</td></tr>
          <tr><td style="color:rgba(255,255,255,.6);font-size:.85rem">Conversion Rate</td><td style="text-align:right;color:#FF6600;font-weight:800">{conversion}%</td></tr>
          <tr><td style="color:rgba(255,255,255,.6);font-size:.85rem">Total Revenue</td><td style="text-align:right;color:#FFAA00;font-weight:800">₹{float(total_revenue):,.0f}</td></tr>
        </table>
      </div>
      <div style="padding:14px 28px;background:rgba(255,255,255,.04);font-size:.75rem;color:rgba(255,255,255,.3)">
        Sent automatically by Sales Agent · NR AI Orbit Learning Portal
      </div>
    </div>"""

    try:
        send_email(to_addr, f'Sales Agent Daily Report — {today}', body_html)
        return jsonify({'ok': True, 'sent_to': to_addr, 'date': today,
                        'new_leads': new_leads, 'emails_sent': emails_sent,
                        'orders_today': orders_today, 'pipeline': pipeline})
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)}), 500


@app.route('/api/admin/test-email', methods=['POST'])
def admin_test_email():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    d = request.get_json() or {}
    to_addr = d.get('to') or (session.get('email') if isinstance(session, dict) else None)
    if not to_addr:
        return jsonify({'error': 'No recipient — pass {"to":"your@email.com"}'}), 400
    config = {
        'SMTP_HOST': SMTP_HOST, 'SMTP_PORT': SMTP_PORT,
        'SMTP_USER': SMTP_USER or '(not set)',
        'SMTP_PASS': '(set)' if SMTP_PASS else '(not set)',
        'FROM_EMAIL': FROM_EMAIL or '(not set)',
    }
    try:
        send_email(to_addr, 'NR AI Orbit — SMTP test', '<p>SMTP is working correctly.</p>')
        return jsonify({'ok': True, 'message': f'Test email sent to {to_addr}', 'config': config})
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex), 'config': config}), 500


@app.route('/api/admin/sales/report/daily', methods=['GET'])
def sales_report_daily():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    from datetime import date as _date
    today = _date.today().isoformat()
    conn = get_conn()
    leads_today    = conn.execute("SELECT COUNT(*) FROM sales_leads WHERE DATE(created_at)=?",   (today,)).fetchone()[0]
    orders_today   = conn.execute("SELECT COUNT(*) FROM sales_orders WHERE DATE(created_at)=?",  (today,)).fetchone()[0]
    outreach_today = conn.execute("SELECT COUNT(*) FROM sales_outreach WHERE DATE(created_at)=?",(today,)).fetchone()[0]
    revenue_today  = conn.execute("SELECT COALESCE(SUM(amount),0) FROM sales_orders WHERE DATE(created_at)=? AND status!='Cancelled'", (today,)).fetchone()[0]
    total_leads    = conn.execute("SELECT COUNT(*) FROM sales_leads").fetchone()[0]
    total_revenue  = conn.execute("SELECT COALESCE(SUM(amount),0) FROM sales_orders WHERE status!='Cancelled'").fetchone()[0]
    converted      = conn.execute("SELECT COUNT(*) FROM sales_leads WHERE status='Order Placed'").fetchone()[0]
    conversion_rate = round((converted / total_leads * 100) if total_leads else 0, 1)
    pipeline = {}
    for s in ['New','Contacted','Negotiating','Order Placed']:
        pipeline[s] = conn.execute("SELECT COUNT(*) FROM sales_leads WHERE status=?", (s,)).fetchone()[0]
    conn.close()
    return jsonify({
        'leads_today': leads_today, 'orders_today': orders_today,
        'outreach_today': outreach_today, 'revenue_today': float(revenue_today),
        'total_leads': total_leads, 'total_revenue': float(total_revenue),
        'conversion_rate': conversion_rate, 'pipeline': pipeline
    })


# ── Main ─────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys

    init_db()

    conn = get_conn()
    student_count    = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    admin_count      = conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
    instructor_count = conn.execute("SELECT COUNT(*) FROM instructors").fetchone()[0]
    conn.close()

    if os.environ.get('SEED_DB', '').lower() == 'true':
        print("  SEED_DB=true — running seed...")
        import seed
        seed.seed()

    port  = int(os.environ.get("PORT", 3000))
    debug = os.environ.get("FLASK_ENV", "production") == "development"

    print(f"\n  NR AI Orbit Learning Portal server  ->  http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
