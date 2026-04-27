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
    {"name": "Admin",        "email": "admin@laxmiacademy.com", "password": "admin@123"},
    {"name": "S. Rajireddy", "email": "rajireddys999@gmail.com", "password": "admin@123"},
]

enquiries = [
    {"full_name": "Rahul Nair", "email": "rahul@mail.com", "phone": "9111111111", "course": "Physics Foundation",   "message": "Please call for demo class details.", "status": "new"},
    {"full_name": "Divya Rao",  "email": "divya@mail.com", "phone": "9222222222", "course": "Full Physics Package", "message": "What is the fee for annual plan?",     "status": "contacted"},
    {"full_name": "Anil Mehta", "email": "",               "phone": "9333333333", "course": "Physics Crash Course", "message": "",                                    "status": "new"},
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
            print(f"  [OK] Student : {s['email']:<30}  password: {s['password']}")
        except Exception as e:
            print(f"  [SKIP] Student : {s['email']} ({e})")

    for a in admins:
        hashed = bcrypt.hashpw(a["password"].encode(), bcrypt.gensalt()).decode()
        try:
            c.execute("""
                INSERT OR IGNORE INTO admins (name, email, password)
                VALUES (?, ?, ?)
            """, (a["name"], a["email"], hashed))
            print(f"  [OK] Admin   : {a['email']:<30}  password: {a['password']}")
        except Exception as e:
            print(f"  [SKIP] Admin : {a['email']} ({e})")

    for e in enquiries:
        c.execute("""
            INSERT INTO enquiries (full_name, email, phone, course, message, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (e["full_name"], e["email"], e["phone"], e["course"], e["message"], e["status"]))
        print(f"  [OK] Enquiry : {e['full_name']}")

    conn.commit()
    conn.close()
    print("\n[DONE] Database seeded successfully -> laxmi_academy.db\n")

if __name__ == "__main__":
    seed()
