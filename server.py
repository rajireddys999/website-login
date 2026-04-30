import uuid, os, re, json, base64, hashlib, secrets, smtplib
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

# ── Email config ─────────────────────────────────────────────────
SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')
FROM_EMAIL = os.environ.get('FROM_EMAIL', SMTP_USER)

def send_email(to_addr, subject, body_html):
    if not SMTP_USER or not SMTP_PASS:
        app.logger.warning("SMTP not configured — skipping email to %s", to_addr)
        return
    msg = MIMEText(body_html, 'html')
    msg['Subject'] = subject
    msg['From']    = f"Laxmi Academy <{FROM_EMAIL}>"
    msg['To']      = to_addr
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(FROM_EMAIL, [to_addr], msg.as_string())
    except Exception as exc:
        app.logger.error("Email send failed to %s: %s", to_addr, exc)

def send_verification_email(email, full_name, token):
    verify_url = f"{APP_BASE_URL}/verify-email.html?token={token}"
    body = f"""
    <p>Hi {full_name},</p>
    <p>Please verify your email address to activate your Laxmi Academy account:</p>
    <p><a href="{verify_url}" style="background:#6366f1;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none">Verify Email</a></p>
    <p>This link expires in 24 hours. If you did not sign up, ignore this email.</p>
    """
    send_email(email, "Verify your Laxmi Academy account", body)

# ── PhonePe config (UAT sandbox by default) ───────────────────────
PHONEPE_MERCHANT_ID = os.environ.get('PHONEPE_MERCHANT_ID', 'PGTESTPAYUAT86')
PHONEPE_SALT_KEY    = os.environ.get('PHONEPE_SALT_KEY',    '96434309-7796-489d-8924-ab56988a6076')
PHONEPE_SALT_INDEX  = os.environ.get('PHONEPE_SALT_INDEX',  '1')
PHONEPE_BASE_URL    = os.environ.get('PHONEPE_BASE_URL',    'https://api-preprod.phonepe.com/apis/pg-sandbox')
APP_BASE_URL        = os.environ.get('APP_BASE_URL',        'http://localhost:3000')

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

    if role == 'student' and not user.get('email_verified', 1):
        return jsonify({'error': 'Please verify your email before logging in. Check your inbox for the verification link.', 'email_unverified': True}), 403

    token = create_session(user['id'], role)
    safe  = {k: v for k, v in dict(user).items() if k != 'password'}
    payment_pending = role == 'student' and user['payment_status'] != 'paid'
    return jsonify({'token': token, 'role': role, 'user': safe, 'payment_pending': payment_pending})

# ── POST /api/register ───────────────────────────────────────────

@app.route('/api/register', methods=['POST'])
def register():
    VALID_COURSES = [
        'NEET - BI-PC',
        'JEE MAINS - Physics',
        'EAMCET - Physics',
        'Intermediate - 1-Year Physics',
        'Intermediate - 2-Year Physics',
    ]
    data      = request.get_json() or {}
    full_name = data.get('full_name', '').strip()
    email     = data.get('email', '').strip()
    phone     = data.get('phone', '').strip()
    password  = data.get('password', '')
    course    = data.get('course', '').strip()
    plan      = data.get('plan', '6 Months')

    if course not in VALID_COURSES:
        course = 'JEE MAINS - Physics'

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
        "INSERT INTO students (full_name, email, phone, password, course, plan, is_active, payment_status, email_verified) VALUES (?, ?, ?, ?, ?, ?, 0, 'pending', 0)",
        (full_name, email, phone, hashed, course, plan)
    )
    conn.commit()
    student_id = cursor.lastrowid

    # Create verification token (24-hour expiry)
    verify_token = secrets.token_urlsafe(32)
    expires_at   = (datetime.utcnow() + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    conn.execute(
        "INSERT INTO email_verifications (student_id, token, expires_at) VALUES (?, ?, ?)",
        (student_id, verify_token, expires_at)
    )
    conn.commit()
    conn.close()

    send_verification_email(email, full_name, verify_token)

    session_token = create_session(student_id, 'student')
    return jsonify({
        'token': session_token, 'role': 'student', 'student_id': student_id,
        'message': 'Account created. Please check your email to verify your account.',
        'email_verification_required': True
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

    send_verification_email(email, student['full_name'] if student else '', verify_token)
    return jsonify({'message': 'If that email is registered, a new verification link has been sent.'})

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
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, full_name, email, phone, course, plan, is_active, payment_status, created_at FROM students ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ── ADMIN: enquiries ─────────────────────────────────────────────

@app.route('/api/admin/enquiries', methods=['GET'])
def admin_enquiries():
    session, err_resp, err_code = require_role('admin')
    if err_resp:
        return err_resp, err_code
    conn = get_conn()
    rows = conn.execute("SELECT * FROM enquiries ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

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
    conn = get_conn()
    rows = conn.execute("""
        SELECT l.*, i.name as instructor_name
        FROM lessons l JOIN instructors i ON l.instructor_id = i.id
        ORDER BY l.created_at DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

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

    conn = get_conn()
    rows = conn.execute("""
        SELECT p.*, s.full_name, s.email
        FROM payments p JOIN students s ON p.student_id = s.id
        ORDER BY p.created_at DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ── Main ─────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys

    init_db()

    conn = get_conn()
    student_count    = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    admin_count      = conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
    instructor_count = conn.execute("SELECT COUNT(*) FROM instructors").fetchone()[0]
    conn.close()

    if student_count == 0 or admin_count == 0 or instructor_count == 0:
        print("  Empty database detected — running seed...")
        import seed
        seed.seed()

    port  = int(os.environ.get("PORT", 3000))
    debug = os.environ.get("FLASK_ENV", "production") == "development"

    print(f"\n  Laxmi Academy server  ->  http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
