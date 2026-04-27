import uuid, os, re
import bcrypt
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from db import get_conn, init_db
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

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
            "SELECT * FROM students WHERE (email = ? OR phone = ?) AND is_active = 1",
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

    token = create_session(user['id'], role)
    safe  = {k: v for k, v in dict(user).items() if k != 'password'}
    return jsonify({'token': token, 'role': role, 'user': safe})

# ── POST /api/register ───────────────────────────────────────────

@app.route('/api/register', methods=['POST'])
def register():
    data      = request.get_json() or {}
    full_name = data.get('full_name', '').strip()
    email     = data.get('email', '').strip()
    phone     = data.get('phone', '').strip()
    password  = data.get('password', '')
    course    = data.get('course', 'Physics Foundation')
    plan      = data.get('plan', '6 Months')

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
        "INSERT INTO students (full_name, email, phone, password, course, plan) VALUES (?, ?, ?, ?, ?, ?)",
        (full_name, email, phone, hashed, course, plan)
    )
    conn.commit()
    student_id = cursor.lastrowid
    conn.close()

    token = create_session(student_id, 'student')
    return jsonify({'token': token, 'role': 'student', 'message': 'Account created successfully.'}), 201

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
            "SELECT id, full_name, email, phone, course, plan, created_at FROM students WHERE id = ?",
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

    topic = request.args.get('topic', '')
    conn  = get_conn()
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

    data        = request.get_json() or {}
    topic       = data.get('topic', '').strip()
    title       = data.get('title', '').strip()
    video_url   = data.get('video_url', '').strip()
    description = data.get('description', '').strip()
    duration    = data.get('duration', '').strip()
    order_num   = int(data.get('order_num', 0))

    if not topic or not title or not video_url:
        return jsonify({'error': 'topic, title and video_url are required.'}), 400

    valid_topics = ['mechanics', 'thermo', 'electro', 'optics', 'modern']
    if topic not in valid_topics:
        return jsonify({'error': f'topic must be one of: {", ".join(valid_topics)}'}), 400

    # Resolve YouTube URL to embed-ready URL
    yt_id = extract_youtube_id(video_url)
    if yt_id:
        video_type      = 'youtube'
        stored_video_url = video_url  # store original; frontend extracts ID
    else:
        video_type      = 'youtube'
        stored_video_url = video_url

    conn = get_conn()
    cursor = conn.execute("""
        INSERT INTO lessons (instructor_id, topic, title, description, video_type, video_url, duration, order_num)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (session['user_id'], topic, title, description, video_type, stored_video_url, duration, order_num))
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

    topic       = request.form.get('topic', '').strip()
    title       = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    duration    = request.form.get('duration', '').strip()
    order_num   = int(request.form.get('order_num', 0))

    if not topic or not title:
        return jsonify({'error': 'topic and title are required.'}), 400

    valid_topics = ['mechanics', 'thermo', 'electro', 'optics', 'modern']
    if topic not in valid_topics:
        return jsonify({'error': f'topic must be one of: {", ".join(valid_topics)}'}), 400

    filename  = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
    filepath  = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    video_url = f'/uploads/videos/{filename}'

    conn = get_conn()
    cursor = conn.execute("""
        INSERT INTO lessons (instructor_id, topic, title, description, video_type, video_url, duration, order_num)
        VALUES (?, ?, ?, ?, 'upload', ?, ?, ?)
    """, (session['user_id'], topic, title, description, video_url, duration, order_num))
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
        "SELECT id, full_name, email, phone, course, plan, is_active, created_at FROM students ORDER BY created_at DESC"
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
        'recent_students': [dict(r) for r in conn.execute(
            "SELECT id, full_name, email, course, created_at FROM students ORDER BY created_at DESC LIMIT 5"
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
