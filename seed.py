import bcrypt
from db import get_conn, init_db

students = [
    {"full_name": "Arjun Kumar",  "email": "arjun@test.com",  "phone": "9000000001", "password": "student123", "course": "Physics Foundation",   "plan": "Annual"},
    {"full_name": "Priya Sharma", "email": "priya@test.com",  "phone": "9000000002", "password": "student123", "course": "Physics Advanced",     "plan": "6 Months"},
    {"full_name": "Rohit Verma",  "email": "rohit@test.com",  "phone": "9000000003", "password": "student123", "course": "Physics Crash Course", "plan": "6 Months"},
    {"full_name": "Sneha Reddy",  "email": "sneha@test.com",  "phone": "9000000004", "password": "test@123",   "course": "Full Physics Package", "plan": "Annual"},
    {"full_name": "Kiran Babu",   "email": "kiran@test.com",  "phone": "9000000005", "password": "test@123",   "course": "Physics Foundation",   "plan": "6 Months"},
]

admins = [
    {"name": "Admin",        "email": "admin@nraiorbit.com",  "password": "admin@123"},
    {"name": "S. Rajireddy", "email": "rajireddys999@gmail.com", "password": "admin@123"},
]

instructors = [
    {"name": "Dr. Ramesh Kumar",  "email": "ramesh@nraiorbit.com",  "phone": "9500000001", "password": "teacher@123", "subject": "Physics", "bio": "15 years teaching IIT-JEE Physics"},
    {"name": "Prof. Anita Verma", "email": "anita@nraiorbit.com",   "phone": "9500000002", "password": "teacher@123", "subject": "Physics", "bio": "NEET Physics specialist"},
]

enquiries = [
    {"full_name": "Rahul Nair", "email": "rahul@mail.com", "phone": "9111111111", "course": "Physics Foundation",   "message": "Please call for demo class details.", "status": "new"},
    {"full_name": "Divya Rao",  "email": "divya@mail.com", "phone": "9222222222", "course": "Full Physics Package", "message": "What is the fee for annual plan?",     "status": "contacted"},
    {"full_name": "Anil Mehta", "email": "",               "phone": "9333333333", "course": "Physics Crash Course", "message": "",                                    "status": "new"},
]

sample_lessons = [
    {"topic": "mechanics",  "title": "Introduction to Newton's Laws",       "video_type": "youtube", "video_url": "https://www.youtube.com/watch?v=ZM8ECpBuQYE", "duration": "18 min", "description": "Basic concepts of Newton's 3 laws of motion with examples."},
    {"topic": "mechanics",  "title": "Work, Energy and Power",              "video_type": "youtube", "video_url": "https://www.youtube.com/watch?v=2WS1sG9fhOk", "duration": "22 min", "description": "Work-energy theorem, kinetic and potential energy explained."},
    {"topic": "thermo",     "title": "Heat and Temperature Concepts",       "video_type": "youtube", "video_url": "https://www.youtube.com/watch?v=vqDbMEdLiCs", "duration": "20 min", "description": "Difference between heat and temperature, thermal equilibrium."},
    {"topic": "electro",    "title": "Electrostatics and Coulomb's Law",    "video_type": "youtube", "video_url": "https://www.youtube.com/watch?v=mc979OhitAg", "duration": "25 min", "description": "Electric charge, Coulomb's law, electric field basics."},
    {"topic": "optics",     "title": "Ray Optics — Mirrors and Lenses",     "video_type": "youtube", "video_url": "https://www.youtube.com/watch?v=uhsL5VzGMSA", "duration": "30 min", "description": "Reflection, refraction, mirror and lens formula derivations."},
    {"topic": "modern",     "title": "Photoelectric Effect",                "video_type": "youtube", "video_url": "https://www.youtube.com/watch?v=FXfrncRey-4", "duration": "19 min", "description": "Einstein's photoelectric equation, threshold frequency, work function."},
]

def seed():
    init_db()
    conn = get_conn()
    c = conn.cursor()
    print("\nSeeding database...\n")

    for s in students:
        hashed = bcrypt.hashpw(s["password"].encode(), bcrypt.gensalt()).decode()
        try:
            c.execute("""
                INSERT OR IGNORE INTO students (full_name, email, phone, password, course, plan)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (s["full_name"], s["email"], s["phone"], hashed, s["course"], s["plan"]))
            print(f"  [OK] Student    : {s['email']:<32}  password: {s['password']}")
        except Exception as e:
            print(f"  [SKIP] Student  : {s['email']} ({e})")

    for a in admins:
        hashed = bcrypt.hashpw(a["password"].encode(), bcrypt.gensalt()).decode()
        try:
            c.execute("""
                INSERT OR IGNORE INTO admins (name, email, password)
                VALUES (?, ?, ?)
            """, (a["name"], a["email"], hashed))
            print(f"  [OK] Admin      : {a['email']:<32}  password: {a['password']}")
        except Exception as e:
            print(f"  [SKIP] Admin    : {a['email']} ({e})")

    for inst in instructors:
        hashed = bcrypt.hashpw(inst["password"].encode(), bcrypt.gensalt()).decode()
        try:
            c.execute("""
                INSERT OR IGNORE INTO instructors (name, email, phone, password, subject, bio)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (inst["name"], inst["email"], inst["phone"], hashed, inst["subject"], inst["bio"]))
            print(f"  [OK] Instructor : {inst['email']:<32}  password: {inst['password']}")
        except Exception as e:
            print(f"  [SKIP] Instructor: {inst['email']} ({e})")

    # Seed sample lessons (attached to first instructor)
    conn.commit()
    first_instructor = c.execute("SELECT id FROM instructors LIMIT 1").fetchone()
    if first_instructor:
        iid = first_instructor['id']
        for i, lesson in enumerate(sample_lessons):
            existing = c.execute(
                "SELECT id FROM lessons WHERE title = ? AND instructor_id = ?",
                (lesson["title"], iid)
            ).fetchone()
            if not existing:
                c.execute("""
                    INSERT INTO lessons (instructor_id, topic, title, description, video_type, video_url, duration, order_num)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (iid, lesson["topic"], lesson["title"], lesson["description"],
                      lesson["video_type"], lesson["video_url"], lesson["duration"], i + 1))
                print(f"  [OK] Lesson     : [{lesson['topic']}] {lesson['title']}")

    for e in enquiries:
        c.execute("""
            INSERT INTO enquiries (full_name, email, phone, course, message, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (e["full_name"], e["email"], e["phone"], e["course"], e["message"], e["status"]))
        print(f"  [OK] Enquiry    : {e['full_name']}")

    # ── Sales Leads ──────────────────────────────────────────────
    sales_leads = [
        {"name": "Arjun Reddy",     "type": "Student", "phone": "9100000001", "email": "arjun.r@gmail.com",   "location": "Hyderabad",   "course_interest": "MPC",      "status": "New"},
        {"name": "Priya Lakshmi",   "type": "Student", "phone": "9100000002", "email": "priya.l@gmail.com",   "location": "Vijayawada",  "course_interest": "BiPC",     "status": "Contacted"},
        {"name": "Rohit Kumar",     "type": "Student", "phone": "9100000003", "email": "rohit.k@gmail.com",   "location": "Guntur",      "course_interest": "MPC",      "status": "Negotiating"},
        {"name": "Sneha Patel",     "type": "Student", "phone": "9100000004", "email": "sneha.p@gmail.com",   "location": "Tirupati",    "course_interest": "Commerce", "status": "Order Placed"},
        {"name": "Kiran Babu",      "type": "Student", "phone": "9100000005", "email": "kiran.b@gmail.com",   "location": "Warangal",    "course_interest": "BiPC",     "status": "New"},
        {"name": "Divya Sharma",    "type": "Student", "phone": "9100000006", "email": "divya.s@gmail.com",   "location": "Hyderabad",   "course_interest": "MPC",      "status": "Contacted"},
        {"name": "Rahul Nair",      "type": "Student", "phone": "9100000007", "email": "rahul.n@gmail.com",   "location": "Vijayawada",  "course_interest": "Commerce", "status": "New"},
        {"name": "Anita Rao",       "type": "Student", "phone": "9100000008", "email": "anita.r@gmail.com",   "location": "Guntur",      "course_interest": "MPC",      "status": "Negotiating"},
        {"name": "Vijay Krishna",   "type": "Student", "phone": "9100000009", "email": "vijay.k@gmail.com",   "location": "Tirupati",    "course_interest": "BiPC",     "status": "Contacted"},
        {"name": "Meera Devi",      "type": "Student", "phone": "9100000010", "email": "meera.d@gmail.com",   "location": "Hyderabad",   "course_interest": "Commerce", "status": "New"},
        {"name": "Sri Venkateswara Junior College", "type": "College", "phone": "9200000001", "email": "admin@svjc.edu",  "location": "Tirupati",   "course_interest": "MPC",  "status": "Contacted"},
        {"name": "Nagarjuna Degree College",        "type": "College", "phone": "9200000002", "email": "info@ndc.edu",    "location": "Vijayawada", "course_interest": "BiPC", "status": "Negotiating"},
        {"name": "Kakatiya Junior College",         "type": "College", "phone": "9200000003", "email": "principal@kjc.edu","location": "Warangal",   "course_interest": "MPC",  "status": "New"},
    ]
    lead_ids = []
    for sl in sales_leads:
        existing_lead = c.execute("SELECT id FROM sales_leads WHERE phone=?", (sl["phone"],)).fetchone()
        if existing_lead:
            lead_ids.append(existing_lead["id"])
            continue
        c.execute("""
            INSERT INTO sales_leads (name, type, phone, email, location, course_interest, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (sl["name"], sl["type"], sl["phone"], sl["email"], sl["location"], sl["course_interest"], sl["status"]))
        lead_ids.append(c.lastrowid if hasattr(c, 'lastrowid') else c.execute("SELECT last_insert_rowid()").fetchone()[0])
        print(f"  [OK] SalesLead  : {sl['name']} ({sl['type']}, {sl['location']})")

    # ── Sales Orders (5 samples) ──────────────────────────────────
    if c.execute("SELECT COUNT(*) FROM sales_orders").fetchone()[0] == 0 and len(lead_ids) >= 4:
        sample_orders = [
            {"lead_name": "Sneha Patel",     "course_name": "MPC Foundation Annual",      "amount": 1998, "order_date": "2026-05-01", "status": "Confirmed"},
            {"lead_name": "Rohit Kumar",     "course_name": "Physics Advanced 6M",         "amount": 999,  "order_date": "2026-05-03", "status": "Pending"},
            {"lead_name": "Sri Venkateswara Junior College", "course_name": "College MPC Package", "amount": 85000, "order_date": "2026-05-04", "status": "Confirmed"},
            {"lead_name": "Divya Sharma",    "course_name": "BiPC Crash Course",           "amount": 1499, "order_date": "2026-05-05", "status": "Confirmed"},
            {"lead_name": "Anita Rao",       "course_name": "Commerce Foundation 9M",      "amount": 1499, "order_date": "2026-05-06", "status": "Pending"},
        ]
        for so in sample_orders:
            c.execute("""
                INSERT INTO sales_orders (lead_name, course_name, amount, order_date, status)
                VALUES (?, ?, ?, ?, ?)
            """, (so["lead_name"], so["course_name"], so["amount"], so["order_date"], so["status"]))
            print(f"  [OK] SalesOrder : {so['lead_name']} — ₹{so['amount']}")

    conn.commit()
    conn.close()
    print("\n[DONE] Database seeded -> laxmi_academy.db\n")

if __name__ == "__main__":
    seed()
