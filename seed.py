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
    {"name": "Admin",        "email": "admin@laxmiacademy.com",  "password": "admin@123"},
    {"name": "S. Rajireddy", "email": "rajireddys999@gmail.com", "password": "admin@123"},
]

instructors = [
    {"name": "Dr. Ramesh Kumar",  "email": "ramesh@laxmiacademy.com",  "phone": "9500000001", "password": "teacher@123", "subject": "Physics", "bio": "15 years teaching IIT-JEE Physics"},
    {"name": "Prof. Anita Verma", "email": "anita@laxmiacademy.com",   "phone": "9500000002", "password": "teacher@123", "subject": "Physics", "bio": "NEET Physics specialist"},
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

    conn.commit()
    conn.close()
    print("\n[DONE] Database seeded -> laxmi_academy.db\n")

if __name__ == "__main__":
    seed()
