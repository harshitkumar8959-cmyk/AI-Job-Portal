import os
import re
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Local matcher helper import with fallback
try:
    from matcher import extract_skills_and_match
except ImportError:
    COMMON_SKILLS = [
        "python", "flask", "django", "sql", "sqlite", "mysql", "postgresql",
        "machine learning", "deep learning", "nlp", "scikit-learn", "tensorflow",
        "keras", "pytorch", "git", "github", "docker", "kubernetes", "aws",
        "rest apis", "rest api", "fastapi", "html", "css", "javascript", "react"
    ]
    def extract_skills_and_match(resume_text, job_desc):
        resume_lower = resume_text.lower()
        desc_lower = job_desc.lower()
        
        req_skills = [s for s in COMMON_SKILLS if re.search(r'\b' + re.escape(s) + r'\b', desc_lower)]
        if not req_skills:
            req_skills = ["python", "sql", "git"]
            
        matched = [s.title() for s in req_skills if re.search(r'\b' + re.escape(s) + r'\b', resume_lower)]
        missing = [s.title() for s in req_skills if s.title() not in matched]
        return matched, missing

# Safe email service handling
try:
    from email_service import send_status_email
except ImportError:
    def send_status_email(to_email, status, job_title):
        print(f"Notification: {to_email} | Status: {status} | Job: {job_title}")

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.secret_key = "ai_job_portal_super_permanent_key_2026"
app.config['SESSION_COOKIE_NAME'] = 'job_portal_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

DB_NAME = 'database.db'

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recruiter_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            cutoff INTEGER NOT NULL,
            description TEXT NOT NULL,
            FOREIGN KEY (recruiter_id) REFERENCES users (id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            candidate_name TEXT,
            candidate_email TEXT,
            phone TEXT,
            experience_level TEXT,
            resume_path TEXT NOT NULL,
            match_score REAL NOT NULL,
            matched_skills TEXT,
            missing_skills TEXT,
            status TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def extract_text_from_pdf(pdf_path):
    text = ""
    try:
        reader = PdfReader(pdf_path)
        for page in reader.pages:
            content = page.extract_text()
            if content:
                text += content + " "
    except Exception as e:
        print(f"Error reading PDF: {e}")
    return text

def extract_phone(text):
    match = re.search(r'(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', text)
    return match.group(0) if match else "+91 9876543210"

def calculate_match_score(resume_text, job_desc):
    if not resume_text.strip() or not job_desc.strip():
        return 0.0
    try:
        documents = [resume_text, job_desc]
        vectorizer = TfidfVectorizer(stop_words='english')
        tfidf_matrix = vectorizer.fit_transform(documents)
        similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
        return round(float(similarity) * 100, 1)
    except Exception as e:
        print(f"Scoring calculation failed: {e}")
        return 0.0

@app.route('/')
def home():
    if 'user_id' in session:
        role = str(session.get('role', '')).strip().lower()
        if role == 'recruiter':
            return redirect(url_for('recruiter_dashboard'))
        return redirect(url_for('candidate_dashboard'))
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        role = request.form.get('role', 'Candidate').strip().capitalize()

        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)',
                         (name, email, password, role))
            conn.commit()
            flash('Registration successful! Please login.')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already registered.')
        finally:
            conn.close()

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE LOWER(email) = ? AND password = ?', (email, password)).fetchone()
        conn.close()

        if user:
            session.clear()
            session['user_id'] = int(user['id'])
            session['name'] = str(user['name'])
            user_role = str(user['role']).strip().capitalize()
            session['role'] = user_role

            if user_role == 'Recruiter':
                return redirect(url_for('recruiter_dashboard'))
            return redirect(url_for('candidate_dashboard'))
        else:
            flash('Invalid email or password.')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/recruiter/dashboard')
def recruiter_dashboard():
    role = str(session.get('role', '')).strip().lower()
    if 'user_id' not in session or role != 'recruiter':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    jobs = conn.execute('SELECT * FROM jobs WHERE recruiter_id = ?', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('recruiter_dashboard.html', jobs=jobs)

@app.route('/recruiter/post-job', methods=['GET', 'POST'])
def post_job():
    role = str(session.get('role', '')).strip().lower()
    if 'user_id' not in session or role != 'recruiter':
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        company = request.form.get('company', '').strip()
        cutoff = int(request.form.get('cutoff', 50))
        description = request.form.get('description', '').strip()

        conn = get_db_connection()
        conn.execute('INSERT INTO jobs (recruiter_id, title, company, cutoff, description) VALUES (?, ?, ?, ?, ?)',
                     (session['user_id'], title, company, cutoff, description))
        conn.commit()
        conn.close()
        return redirect(url_for('recruiter_dashboard'))

    return render_template('post_job.html')

@app.route('/recruiter/applications/<int:job_id>')
def view_applications(job_id):
    role = str(session.get('role', '')).strip().lower()
    if 'user_id' not in session or role != 'recruiter':
        return redirect(url_for('login'))

    conn = get_db_connection()
    job = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
    raw_apps = conn.execute('''
        SELECT applications.*, users.name as u_name, users.email as u_email
        FROM applications
        JOIN users ON applications.user_id = users.id
        WHERE applications.job_id = ?
        ORDER BY applications.match_score DESC
    ''', (job_id,)).fetchall()
    conn.close()

    applications = []
    for app_row in raw_apps:
        item = dict(app_row)
        matched_str = item.get('matched_skills') or ""
        missing_str = item.get('missing_skills') or ""
        item['matched_list'] = [s.strip() for s in matched_str.split(',') if s.strip()]
        item['missing_list'] = [s.strip() for s in missing_str.split(',') if s.strip()]
        item['resume_filename'] = os.path.basename(item.get('resume_path', ''))
        applications.append(item)

    return render_template('result.html', job=job, applications=applications)

@app.route('/download-resume/<filename>')
def download_resume(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/update-status/<int:app_id>/<string:status>/<int:job_id>')
def update_status(app_id, status, job_id):
    role = str(session.get('role', '')).strip().lower()
    if 'user_id' not in session or role != 'recruiter':
        return redirect(url_for('login'))

    conn = get_db_connection()
    conn.execute('UPDATE applications SET status = ? WHERE id = ?', (status, app_id))
    conn.commit()

    data = conn.execute('''
        SELECT users.email, users.name, jobs.title 
        FROM applications 
        JOIN users ON applications.user_id = users.id 
        JOIN jobs ON applications.job_id = jobs.id 
        WHERE applications.id = ?
    ''', (app_id,)).fetchone()
    conn.close()

    if data:
        try:
            send_status_email(data['email'], status, data['title'])
        except Exception as e:
            print(f"Email bypass: {e}")

    return redirect(url_for('view_applications', job_id=job_id))

@app.route('/candidate/dashboard')
def candidate_dashboard():
    role = str(session.get('role', '')).strip().lower()
    if 'user_id' not in session or role != 'candidate':
        return redirect(url_for('login'))

    conn = get_db_connection()
    jobs = conn.execute('SELECT * FROM jobs').fetchall()
    my_applications = conn.execute('''
        SELECT applications.*, jobs.title, jobs.company, jobs.cutoff 
        FROM applications 
        JOIN jobs ON applications.job_id = jobs.id 
        WHERE applications.user_id = ?
    ''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('candidate_dashboard.html', jobs=jobs, my_applications=my_applications)

@app.route('/apply/<int:job_id>', methods=['GET', 'POST'])
def apply_job(job_id):
    role = str(session.get('role', '')).strip().lower()
    if 'user_id' not in session or role != 'candidate':
        return redirect(url_for('login'))

    conn = get_db_connection()
    job = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()

    if request.method == 'POST':
        file = request.files.get('resume')
        if file and file.filename.endswith('.pdf'):
            filename = secure_filename(f"user_{session['user_id']}_{file.filename}")
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            resume_text = extract_text_from_pdf(file_path)
            score = calculate_match_score(resume_text, job['description'])
            matched_skills, missing_skills = extract_skills_and_match(resume_text, job['description'])
            
            initial_status = 'Shortlisted' if score >= job['cutoff'] else 'Under Review'
            phone = extract_phone(resume_text)
            exp_level = "Graduate / Fresher"

            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO applications (
                    job_id, user_id, candidate_name, candidate_email, phone,
                    experience_level, resume_path, match_score, matched_skills,
                    missing_skills, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                job_id, session['user_id'], session.get('name'), session.get('email', 'Candidate'),
                phone, exp_level, file_path, score,
                ", ".join(matched_skills), ", ".join(missing_skills), initial_status
            ))
            app_id = cursor.lastrowid
            conn.commit()
            conn.close()

            # Candidate Competency Analysis page render
            return render_template(
                'apply.html',
                analysis_done=True,
                candidate_name=session.get('name'),
                target_role=job['title'],
                match_score=score,
                cutoff=job['cutoff'],
                status=initial_status,
                matched_skills=matched_skills,
                missing_skills=missing_skills,
                job=job
            )

    conn.close()
    return render_template('apply.html', job=job, analysis_done=False)

if __name__ == '__main__':
    app.run(debug=True)
