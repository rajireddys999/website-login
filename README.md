# Laxmi Academy — Physics Student Portal

Full-stack web application for Laxmi Academy — School of Knowledge, Hyderabad.  
Physics-focused coaching portal with student login, course access, and admin management.

---

## Live URLs

| Service | URL |
|---|---|
| **Website (Netlify)** | https://resplendent-florentine-e8ae7a.netlify.app |
| **API Backend (Render)** | https://website-login-wyxt.onrender.com |
| **GitHub Repository** | https://github.com/rajireddys999/website-login |

---

## Table of Contents

1. [Project Structure](#project-structure)
2. [Pages](#pages)
3. [Database Tables](#database-tables)
4. [API Endpoints](#api-endpoints)
5. [Test Credentials](#test-credentials)
6. [Local Development](#local-development)
7. [GitHub Setup](#github-setup)
8. [Backend Deployment — Render](#backend-deployment--render)
9. [Frontend Deployment — Netlify](#frontend-deployment--netlify)
10. [Course Access Logic](#course-access-logic)

---

## Project Structure

```
website-login/
├── index.html            # Main public website (Physics courses, hero, contact)
├── login.html            # Student / Admin login page
├── signup.html           # New student registration
├── dashboard.html        # Student dashboard (courses, schedule, profile)
├── admin-dashboard.html  # Admin panel (manage students, enquiries, sessions)
├── style.css             # Legacy styles (used by signup.html)
├── logo.png.jpeg         # Academy logo
│
├── server.py             # Flask backend — all API routes
├── db.py                 # SQLite database setup — creates all tables
├── seed.py               # Seeds test students, admins, and enquiries
│
├── netlify.toml          # Netlify config — proxy /api/* to Render backend
├── render.yaml           # Render config — Python web service definition
├── requirements.txt      # Python dependencies
├── .gitignore            # Excludes laxmi_academy.db, __pycache__
└── README.md             # This file
```

---

## Pages

### `index.html` — Main Website
Public-facing marketing page with:
- Animated hero section with quick enquiry form
- Physics topic cards (Mechanics, Thermodynamics, Electromagnetism, Optics, Modern Physics)
- Stats counter (students, experience, ranks, success rate)
- Why Choose Us section
- Batch schedule (Foundation, Advanced, Crash Course)
- Testimonials with star ratings
- Rankers gallery
- Contact form + Google Maps embed
- Floating WhatsApp button

### `login.html` — Student / Admin Login
- Student tab and Admin tab
- Email or phone login
- Show/hide password toggle
- Forgot password flow
- Redirects students → `dashboard.html`
- Redirects admins → `admin-dashboard.html`

### `dashboard.html` — Student Dashboard
Post-login portal showing:
- Welcome banner with enrolled course
- Stats: course name, plan, topics unlocked, member since
- Physics topic cards (locked/unlocked based on course)
- Weekly class schedule with Today/Done/Upcoming badges
- Upcoming tests list
- Profile page with student details

### `admin-dashboard.html` — Admin Panel
- **Dashboard** — 6 stat cards, recent signups, course enrollment chart
- **Students** — searchable/filterable table with Revoke, Restore, Delete actions
- **Enquiries** — table with Contacted / Enrolled status management
- **Sessions** — all active login tokens

---

## Database Tables

Database file: `laxmi_academy.db` (SQLite)

### `students`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `full_name` | TEXT | Student full name |
| `email` | TEXT UNIQUE | Login email |
| `phone` | TEXT UNIQUE | Login phone (alternative to email) |
| `password` | TEXT | bcrypt hashed password |
| `course` | TEXT | Enrolled course name |
| `plan` | TEXT | Subscription plan (6 Months / Annual) |
| `is_active` | INTEGER | 1 = active, 0 = revoked |
| `created_at` | TEXT | Registration timestamp |

### `admins`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `name` | TEXT | Admin display name |
| `email` | TEXT UNIQUE | Admin login email |
| `password` | TEXT | bcrypt hashed password |
| `created_at` | TEXT | Created timestamp |

### `sessions`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `token` | TEXT UNIQUE | UUID session token |
| `user_id` | INTEGER | References student or admin ID |
| `role` | TEXT | `student` or `admin` |
| `created_at` | TEXT | Login timestamp |
| `expires_at` | TEXT | Expiry (7 days from login) |

### `enquiries`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `full_name` | TEXT | Enquirer name |
| `email` | TEXT | Contact email |
| `phone` | TEXT | Contact phone |
| `course` | TEXT | Course interested in |
| `message` | TEXT | Enquiry message |
| `status` | TEXT | `new` / `contacted` / `enrolled` |
| `created_at` | TEXT | Submitted timestamp |

### View tables in DB Browser for SQLite

```sql
-- List all tables
SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;

-- View all students
SELECT id, full_name, email, course, plan, is_active, created_at FROM students;

-- View all admins
SELECT id, name, email, created_at FROM admins;

-- Active sessions
SELECT * FROM sessions WHERE expires_at > datetime('now');

-- Enquiries by status
SELECT * FROM enquiries WHERE status = 'new';
```

---

## API Endpoints

Base URL (local): `http://localhost:3000`  
Base URL (production): `https://website-login-wyxt.onrender.com`

### Public

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/login` | Login — body: `{ identifier, password, role }` |
| `POST` | `/api/register` | Register student — body: `{ full_name, email, phone, password, course, plan }` |
| `POST` | `/api/logout` | Logout — header: `Authorization: Bearer <token>` |
| `GET` | `/api/me` | Get current user — header: `Authorization: Bearer <token>` |
| `POST` | `/api/enquiry` | Submit enquiry — body: `{ full_name, phone, email, course, message }` |
| `GET` | `/api/status` | Health check — returns table counts |

### Admin only (requires admin token)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/admin/stats` | Dashboard stats + recent signups + course breakdown |
| `GET` | `/api/admin/students` | All students list |
| `PATCH` | `/api/admin/students/<id>/toggle` | Revoke or restore student access |
| `DELETE` | `/api/admin/students/<id>` | Permanently delete student |
| `GET` | `/api/admin/enquiries` | All enquiries |
| `PATCH` | `/api/admin/enquiries/<id>/status` | Update enquiry status |
| `GET` | `/api/admin/sessions` | All active sessions |

---

## Test Credentials

### Students

| Name | Email | Password | Course |
|---|---|---|---|
| Arjun Kumar | arjun@test.com | student123 | Physics Foundation |
| Priya Sharma | priya@test.com | student123 | Physics Advanced |
| Rohit Verma | rohit@test.com | student123 | Physics Crash Course |
| Sneha Reddy | sneha@test.com | test@123 | Full Physics Package |
| Kiran Babu | kiran@test.com | test@123 | Physics Foundation |

### Admins

| Name | Email | Password |
|---|---|---|
| Admin | admin@laxmiacademy.com | admin@123 |
| S. Rajireddy | rajireddys999@gmail.com | admin@123 |

---

## Local Development

### Prerequisites
- Python 3.10+
- Git
- Node.js (for Netlify CLI, optional)

### Setup

```bash
# 1. Clone the repository
git clone https://github.com/rajireddys999/website-login.git
cd website-login

# 2. Install Python dependencies
pip install flask flask-cors bcrypt

# 3. Seed the database with test data
python seed.py

# 4. Start the server
python server.py
```

Open **http://localhost:3000** in your browser.

### View database (GUI)
Install DB Browser for SQLite:
```bash
winget install --id DBBrowserForSQLite.DBBrowserForSQLite --accept-source-agreements --accept-package-agreements
```
Then open `laxmi_academy.db` in DB Browser.

---

## GitHub Setup

### Initial setup used in this project

```bash
# Install GitHub CLI
winget install --id GitHub.cli --accept-source-agreements --accept-package-agreements

# Login
gh auth login

# Clone the repo
gh repo clone rajireddys999/website-login
```

### Branch and PR workflow

```bash
# Create feature branch
git checkout -b feature/your-feature-name

# Make changes, then commit
git add .
git commit -m "Your commit message"
git push origin feature/your-feature-name

# Create PR via GitHub CLI
gh pr create --title "PR Title" --body "Description"

# Merge PR
gh pr merge <PR-number> --merge
```

---

## Backend Deployment — Render

The Flask backend is hosted on Render (free tier).

### Initial Setup

1. Go to **https://render.com** → Sign up with GitHub
2. Click **New → Web Service**
3. Connect repo: `rajireddys999/website-login`
4. Configure:
   - **Runtime:** Python 3
   - **Root Directory:** *(leave blank)*
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python server.py`
   - **Environment Variable:** `FLASK_ENV = production`
5. Click **Deploy**

### Important notes
- Render's **free tier spins down** after 15 minutes of inactivity
- First request after idle takes ~30 seconds to wake up
- SQLite database is **ephemeral** on free tier — data resets on redeploy
- The server auto-seeds test data on startup if the database is empty

### Redeploy after code changes
Push to `main` — Render auto-deploys on every push to GitHub.

---

## Frontend Deployment — Netlify

The static HTML/CSS/JS files are hosted on Netlify with API calls proxied to Render.

### How the proxy works (`netlify.toml`)

```toml
[[redirects]]
  from = "/api/*"
  to   = "https://website-login-wyxt.onrender.com/api/:splat"
  status = 200
  force  = true
```

Any `/api/*` request on the Netlify site is transparently forwarded to the Render backend.

### Initial Setup

```bash
# Install Netlify CLI
npm install -g netlify-cli

# Login
netlify login

# Deploy
netlify deploy --dir . --prod
```

### Redeploy after changes

```bash
netlify deploy --dir . --prod
```

Or connect the GitHub repo in Netlify dashboard for **automatic deploys on every push**.

---

## Course Access Logic

Physics topics unlocked per enrolled course:

| Course | Mechanics | Thermodynamics | Electromagnetism | Optics & Waves | Modern Physics |
|---|:---:|:---:|:---:|:---:|:---:|
| Physics Foundation | ✅ | ✅ | 🔒 | 🔒 | 🔒 |
| Physics Advanced | 🔒 | 🔒 | ✅ | ✅ | ✅ |
| Physics Crash Course | ✅ | ✅ | ✅ | ✅ | ✅ |
| Full Physics Package | ✅ | ✅ | ✅ | ✅ | ✅ |

Locked topics show a 🔒 overlay on the student dashboard. Revoking a student's access (`is_active = 0`) immediately invalidates all their sessions.

---

*Built with Flask · SQLite · Tailwind CSS · Netlify · Render*
