import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Optional email utility import
try:
    from email_service import send_status_email
except ImportError:
    def send_status_email(to_email, status, job_title):
        print(f"Mock email sent to {to_email} | Status: {status} | Job: {job_title}")

app = Flask(__name__)
app.secret_key = "ai_job_portal_secret_key"
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
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    ''')
    # Jobs table
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
    # Applications table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            resume_path TEXT NOT NULL,
            match_score REAL NOT NULL,
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

def calculate_match_score(resume_text, job_desc):
    if not resume_text.strip() or not job_desc.strip():
        return 0.0
    try:
        documents = [resume_text, job_desc]
        vectorizer = TfidfVectorizer(stop_words='english')
        tfidf_matrix = vectorizer.fit_transform(documents)
        similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
        return round(float(similarity) * 100, 2)
    except Exception as e:
        print(f"Scoring calculation failed: {e}")
        return 0.0

@app.route('/')
def home():
    if 'user_id' in session:
        if session.get('role') == 'Recruiter':
            return redirect(url_for('recruiter_dashboard'))
        return redirect(url_for('candidate_dashboard'))
    return redirect(url_for('login'))

# Dono routes (/signup aur /register) support karne ke liye:
@app.route('/signup', methods=['GET', 'POST'])
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']

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
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE email = ? AND password = ?', (email, password)).fetchone()
        conn.close()

        if user:
            session['user_id'] = user['id']
            session['name'] = user['name']
            session['role'] = user['role']
            if user['role'] == 'Recruiter':
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
    if session.get('role') != 'Recruiter':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    jobs = conn.execute('SELECT * FROM jobs WHERE recruiter_id = ?', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('recruiter_dashboard.html', jobs=jobs)

@app.route('/recruiter/post-job', methods=['GET', 'POST'])
def post_job():
    if session.get('role') != 'Recruiter':
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form['title']
        company = request.form['company']
        cutoff = int(request.form.get('cutoff', 40))
        description = request.form['description']

        conn = get_db_connection()
        conn.execute('INSERT INTO jobs (recruiter_id, title, company, cutoff, description) VALUES (?, ?, ?, ?, ?)',
                     (session['user_id'], title, company, cutoff, description))
        conn.commit()
        conn.close()
        return redirect(url_for('recruiter_dashboard'))
    return render_template('post_job.html')

@app.route('/recruiter/applications/<int:job_id>')
def view_applications(job_id):
    if session.get('role') != 'Recruiter':
        return redirect(url_for('login'))

    conn = get_db_connection()
    job = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
    applications = conn.execute('''
        SELECT applications.*, users.name as candidate_name, users.email as candidate_email
        FROM applications
        JOIN users ON applications.user_id = users.id
        WHERE applications.job_id = ?
        ORDER BY applications.match_score DESC
    ''', (job_id,)).fetchall()
    conn.close()
    return render_template('view_applications.html', job=job, applications=applications)

# Crash-proof status update route
@app.route('/update-status/<int:app_id>/<string:status>/<int:job_id>')
def update_status(app_id, status, job_id):
    if session.get('role') != 'Recruiter':
        return redirect(url_for('login'))

    conn = get_db_connection()
    # 1. Update status in database
    conn.execute('UPDATE applications SET status = ? WHERE id = ?', (status, app_id))
    conn.commit()

    # 2. Fetch details for notification
    data = conn.execute('''
        SELECT users.email, users.name, jobs.title 
        FROM applications 
        JOIN users ON applications.user_id = users.id 
        JOIN jobs ON applications.job_id = jobs.id 
        WHERE applications.id = ?
    ''', (app_id,)).fetchone()
    conn.close()

    # 3. Safe notification block
    if data:
        try:
            send_status_email(data['email'], status, data['title'])
        except Exception as e:
            print(f"Notification error bypassed safely: {e}")

    return redirect(url_for('view_applications', job_id=job_id))

@app.route('/candidate/dashboard')
def candidate_dashboard():
    if session.get('role') != 'Candidate':
        return redirect(url_for('login'))

    conn = get_db_connection()
    jobs = conn.execute('SELECT * FROM jobs').fetchall()
    my_applications = conn.execute('''
        SELECT applications.*, jobs.title, jobs.company 
        FROM applications 
        JOIN jobs ON applications.job_id = jobs.id 
        WHERE applications.user_id = ?
    ''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('candidate_dashboard.html', jobs=jobs, my_applications=my_applications)

@app.route('/apply/<int:job_id>', methods=['POST'])
def apply_job(job_id):
    if session.get('role') != 'Candidate':
        return redirect(url_for('login'))

    file = request.files.get('resume')
    if file and file.filename.endswith('.pdf'):
        filename = secure_filename(f"user_{session['user_id']}_{file.filename}")
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        resume_text = extract_text_from_pdf(file_path)

        conn = get_db_connection()
        job = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()

        if job:
            score = calculate_match_score(resume_text, job['description'])
            initial_status = 'Shortlisted' if score >= job['cutoff'] else 'Under Review'

            conn.execute('''
                INSERT INTO applications (job_id, user_id, resume_path, match_score, status)
                VALUES (?, ?, ?, ?, ?)
            ''', (job_id, session['user_id'], file_path, score, initial_status))
            conn.commit()
            flash(f'Application submitted! Initial Match Score: {score}%')
        conn.close()

    return redirect(url_for('candidate_dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
