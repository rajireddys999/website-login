import uuid
import bcrypt
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from db import get_conn, init_db

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

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
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '').strip()
    session = get_session(token)
    if not session:
        return None, jsonify({'error': 'Unauthorised. Please log in.'}), 401
    return session, None, None

def row_to_dict(row):
    return dict(row) if row else None

# ── Serve static files (HTML pages) ──────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)

# ── POST /api/login ──────────────────────────────────────────────

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or {}
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
    else:
        user = conn.execute(
            "SELECT id, name, email, created_at FROM admins WHERE id = ?",
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

# ── GET /api/admin/students ──────────────────────────────────────

@app.route('/api/admin/students', methods=['GET'])
def admin_students():
    session, err_resp, err_code = require_auth()
    if err_resp:
        return err_resp, err_code
    if session['role'] != 'admin':
        return jsonify({'error': 'Admin access only.'}), 403

    conn = get_conn()
    rows = conn.execute(
        "SELECT id, full_name, email, phone, course, plan, is_active, created_at FROM students ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ── GET /api/admin/enquiries ─────────────────────────────────────

@app.route('/api/admin/enquiries', methods=['GET'])
def admin_enquiries():
    session, err_resp, err_code = require_auth()
    if err_resp:
        return err_resp, err_code
    if session['role'] != 'admin':
        return jsonify({'error': 'Admin access only.'}), 403

    conn = get_conn()
    rows = conn.execute("SELECT * FROM enquiries ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ── GET /api/admin/stats ─────────────────────────────────────────

@app.route('/api/admin/stats', methods=['GET'])
def admin_stats():
    session, err_resp, err_code = require_auth()
    if err_resp:
        return err_resp, err_code
    if session['role'] != 'admin':
        return jsonify({'error': 'Admin access only.'}), 403

    conn = get_conn()
    stats = {
        'total_students':    conn.execute("SELECT COUNT(*) FROM students").fetchone()[0],
        'active_students':   conn.execute("SELECT COUNT(*) FROM students WHERE is_active=1").fetchone()[0],
        'revoked_students':  conn.execute("SELECT COUNT(*) FROM students WHERE is_active=0").fetchone()[0],
        'total_enquiries':   conn.execute("SELECT COUNT(*) FROM enquiries").fetchone()[0],
        'new_enquiries':     conn.execute("SELECT COUNT(*) FROM enquiries WHERE status='new'").fetchone()[0],
        'active_sessions':   conn.execute("SELECT COUNT(*) FROM sessions WHERE expires_at > datetime('now')").fetchone()[0],
        'courses': [dict(r) for r in conn.execute(
            "SELECT course, COUNT(*) as count FROM students GROUP BY course ORDER BY count DESC"
        ).fetchall()],
        'recent_students': [dict(r) for r in conn.execute(
            "SELECT id, full_name, email, course, created_at FROM students ORDER BY created_at DESC LIMIT 5"
        ).fetchall()],
    }
    conn.close()
    return jsonify(stats)

# ── PATCH /api/admin/students/<id>/toggle ────────────────────────

@app.route('/api/admin/students/<int:sid>/toggle', methods=['PATCH'])
def toggle_student(sid):
    session, err_resp, err_code = require_auth()
    if err_resp:
        return err_resp, err_code
    if session['role'] != 'admin':
        return jsonify({'error': 'Admin access only.'}), 403

    conn = get_conn()
    student = conn.execute("SELECT id, full_name, is_active FROM students WHERE id=?", (sid,)).fetchone()
    if not student:
        conn.close()
        return jsonify({'error': 'Student not found.'}), 404

    new_status = 0 if student['is_active'] else 1
    conn.execute("UPDATE students SET is_active=? WHERE id=?", (new_status, sid))
    # Revoke all sessions if deactivating
    if new_status == 0:
        conn.execute("DELETE FROM sessions WHERE user_id=? AND role='student'", (sid,))
    conn.commit()
    conn.close()
    return jsonify({'id': sid, 'is_active': new_status,
                    'message': f"Access {'restored' if new_status else 'revoked'} for {student['full_name']}."})

# ── DELETE /api/admin/students/<id> ─────────────────────────────

@app.route('/api/admin/students/<int:sid>', methods=['DELETE'])
def delete_student(sid):
    session, err_resp, err_code = require_auth()
    if err_resp:
        return err_resp, err_code
    if session['role'] != 'admin':
        return jsonify({'error': 'Admin access only.'}), 403

    conn = get_conn()
    student = conn.execute("SELECT full_name FROM students WHERE id=?", (sid,)).fetchone()
    if not student:
        conn.close()
        return jsonify({'error': 'Student not found.'}), 404

    conn.execute("DELETE FROM sessions WHERE user_id=? AND role='student'", (sid,))
    conn.execute("DELETE FROM students WHERE id=?", (sid,))
    conn.commit(); conn.close()
    return jsonify({'message': f"{student['full_name']} deleted successfully."})

# ── PATCH /api/admin/enquiries/<id>/status ────────────────────────

@app.route('/api/admin/enquiries/<int:eid>/status', methods=['PATCH'])
def update_enquiry_status(eid):
    session, err_resp, err_code = require_auth()
    if err_resp:
        return err_resp, err_code
    if session['role'] != 'admin':
        return jsonify({'error': 'Admin access only.'}), 403

    data   = request.get_json() or {}
    status = data.get('status', '')
    if status not in ('new', 'contacted', 'enrolled'):
        return jsonify({'error': 'status must be new, contacted, or enrolled.'}), 400

    conn = get_conn()
    conn.execute("UPDATE enquiries SET status=? WHERE id=?", (status, eid))
    conn.commit(); conn.close()
    return jsonify({'id': eid, 'status': status})

# ── GET /api/admin/sessions ───────────────────────────────────────

@app.route('/api/admin/sessions', methods=['GET'])
def admin_sessions():
    session, err_resp, err_code = require_auth()
    if err_resp:
        return err_resp, err_code
    if session['role'] != 'admin':
        return jsonify({'error': 'Admin access only.'}), 403

    conn = get_conn()
    rows = conn.execute("""
        SELECT s.id, s.token, s.role, s.created_at, s.expires_at,
               CASE s.role
                 WHEN 'student' THEN (SELECT full_name FROM students WHERE id = s.user_id)
                 WHEN 'admin'   THEN (SELECT name       FROM admins   WHERE id = s.user_id)
               END as user_name
        FROM sessions s
        WHERE s.expires_at > datetime('now')
        ORDER BY s.created_at DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ── GET /api/status ──────────────────────────────────────────────

@app.route('/api/status', methods=['GET'])
def status():
    conn = get_conn()
    counts = {
        'students':  conn.execute("SELECT COUNT(*) FROM students").fetchone()[0],
        'admins':    conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0],
        'sessions':  conn.execute("SELECT COUNT(*) FROM sessions WHERE expires_at > datetime('now')").fetchone()[0],
        'enquiries': conn.execute("SELECT COUNT(*) FROM enquiries").fetchone()[0],
    }
    conn.close()
    return jsonify({'status': 'ok', 'database': 'laxmi_academy.db', 'counts': counts})

# ── Main ─────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    print("\n  Laxmi Academy server  ->  http://localhost:3000")
    print("  API endpoints:")
    print("    POST  /api/login")
    print("    POST  /api/register")
    print("    POST  /api/logout")
    print("    GET   /api/me")
    print("    POST  /api/enquiry")
    print("    GET   /api/status")
    print("    GET   /api/admin/students   (admin only)")
    print("    GET   /api/admin/enquiries  (admin only)\n")
    app.run(port=3000, debug=True)
