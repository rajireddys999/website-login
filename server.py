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
    <p>We received a request to reset your Laxmi Academy password. Click the button below to choose a new password:</p>
    <p><a href="{reset_url}" style="background:#6366f1;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none">Reset Password</a></p>
    <p>This link expires in <strong>1 hour</strong>. If you did not request a password reset, you can safely ignore this email.</p>
    """
    send_email(email, "Reset your Laxmi Academy password", body)
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
        # Backward-compatible: return plain list
        rows = conn.execute(
            "SELECT id, full_name, email, phone, course, plan, is_active, payment_status, created_at FROM students ORDER BY created_at DESC"
        ).fetchall()
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

    system = f"""You are an AI operations assistant embedded in the Mission Control dashboard for Laxmi Academy — a physics coaching centre in Hyderabad, India.

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
            watched         = MAX(watched, excluded.watched),
            completed       = MAX(completed, excluded.completed),
            watched_seconds = MAX(watched_seconds, excluded.watched_seconds),
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
        CREATE INDEX IF NOT EXISTS idx_doubts_student    ON doubts(student_id);
        CREATE INDEX IF NOT EXISTS idx_doubts_lesson     ON doubts(lesson_id);
        CREATE INDEX IF NOT EXISTS idx_doubts_status     ON doubts(status);
    """)

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
    _migrate_doubts(conn)
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
    _migrate_doubts(conn)
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
    _migrate_doubts(conn)
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
    _migrate_doubts(conn)
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
    cols = conn.execute("PRAGMA table_info(enquiries)").fetchall()
    col_names = [c[1] for c in cols]
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
    _migrate_discount_codes(conn)
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
    _migrate_discount_codes(conn)
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
    _migrate_discount_codes(conn)
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
        CREATE INDEX IF NOT EXISTS idx_dc_code ON discount_codes(code);
    """)

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
