import os
import sqlite3
import json
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from matcher import extract_text_from_pdf, calculate_match_score, extract_contact_info
from email_service import send_status_email

app = Flask(__name__)
app.secret_key = 'super_secret_jobportal_key_2026'
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    # Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    ''')
    # Jobs Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recruiter_id INTEGER,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            description TEXT NOT NULL,
            cutoff_score INTEGER DEFAULT 40,
            FOREIGN KEY (recruiter_id) REFERENCES users (id)
        )
    ''')
    # Applications Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            candidate_id INTEGER,
            candidate_name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            degree TEXT,
            resume_filename TEXT NOT NULL,
            match_score REAL,
            matched_skills TEXT,
            missing_skills TEXT,
            status TEXT DEFAULT 'Under Review',
            FOREIGN KEY (job_id) REFERENCES jobs (id),
            FOREIGN KEY (candidate_id) REFERENCES users (id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- Auth Routes ---
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']
        
        hashed_pwd = generate_password_hash(password)
        conn = get_db()
        try:
            conn.execute('INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)',
                         (name, email, hashed_pwd, role))
            conn.commit()
            flash('Account created successfully! Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already registered. Try logging in.', 'danger')
        finally:
            conn.close()
            
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['name'] = user['name']
            session['email'] = user['email']
            session['role'] = user['role']
            flash(f"Welcome back, {user['name']}!", 'info')
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password.', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# --- Job & Application Routes ---
@app.route('/')
def index():
    conn = get_db()
    jobs = conn.execute('SELECT * FROM jobs ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('index.html', jobs=jobs)

@app.route('/post-job', methods=['GET', 'POST'])
def post_job():
    if session.get('role') != 'recruiter':
        flash('Only recruiters can post jobs.', 'warning')
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        title = request.form['title']
        company = request.form['company']
        description = request.form['description']
        cutoff = request.form.get('cutoff_score', 40)
        recruiter_id = session.get('user_id')
        
        conn = get_db()
        conn.execute('INSERT INTO jobs (recruiter_id, title, company, description, cutoff_score) VALUES (?, ?, ?, ?, ?)', 
                     (recruiter_id, title, company, description, cutoff))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))
    return render_template('post_job.html')

@app.route('/apply/<int:job_id>', methods=['GET', 'POST'])
def apply(job_id):
    if session.get('role') != 'candidate':
        flash('Please login as a Candidate to apply for jobs.', 'warning')
        return redirect(url_for('login'))

    conn = get_db()
    job = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()

    # Pehle se apply kiya hua toh check karein
    existing_app = conn.execute('SELECT * FROM applications WHERE job_id = ? AND candidate_id = ?', 
                                (job_id, session.get('user_id'))).fetchone()
    if existing_app:
        conn.close()
        flash('You have already applied for this position.', 'info')
        return redirect(url_for('candidate_dashboard'))

    if request.method == 'POST':
        file = request.files['resume']

        if file and file.filename.endswith('.pdf'):
            filename = secure_filename(f"{session.get('user_id')}_{file.filename}")
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            resume_text = extract_text_from_pdf(file_path)
            phone, degree = extract_contact_info(resume_text)
            score, matched_skills, missing_recommendations = calculate_match_score(resume_text, job['description'])

            status = 'Shortlisted' if score >= job['cutoff_score'] else 'Under Review'

            conn.execute('''
                INSERT INTO applications 
                (job_id, candidate_id, candidate_name, email, phone, degree, resume_filename, match_score, matched_skills, missing_skills, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (job_id, session.get('user_id'), session.get('name'), session.get('email'), 
                  phone, degree, filename, score, 
                  json.dumps(matched_skills), json.dumps(missing_recommendations), status))
            conn.commit()
            conn.close()

            return render_template('result.html', name=session.get('name'), score=score, 
                                   job_title=job['title'], matched_skills=matched_skills, 
                                   missing_recommendations=missing_recommendations,
                                   cutoff=job['cutoff_score'])

    conn.close()
    return render_template('apply.html', job=job)

@app.route('/my-applications')
def candidate_dashboard():
    if session.get('role') != 'candidate':
        flash('Access restricted to candidates.', 'warning')
        return redirect(url_for('login'))

    conn = get_db()
    my_apps = conn.execute('''
        SELECT applications.*, jobs.title, jobs.company 
        FROM applications 
        JOIN jobs ON applications.job_id = jobs.id 
        WHERE applications.candidate_id = ?
        ORDER BY applications.id DESC
    ''', (session.get('user_id'),)).fetchall()
    conn.close()

    return render_template('candidate_dashboard.html', applications=my_apps)

@app.route('/recruiter/job/<int:job_id>')
def view_candidates(job_id):
    if session.get('role') != 'recruiter':
        flash('Only recruiters can view applicant dashboards.', 'warning')
        return redirect(url_for('login'))

    conn = get_db()
    job = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
    
    # Check agar ye job isi recruiter ne post ki hai
    if job['recruiter_id'] and job['recruiter_id'] != session.get('user_id'):
        conn.close()
        flash('You are not authorized to view applicants for this posting.', 'danger')
        return redirect(url_for('index'))

    raw_apps = conn.execute('''
        SELECT * FROM applications WHERE job_id = ? ORDER BY match_score DESC
    ''', (job_id,)).fetchall()
    conn.close()

    applications = []
    for app_row in raw_apps:
        keys = app_row.keys()
        applications.append({
            'id': app_row['id'],
            'name': app_row['candidate_name'],
            'email': app_row['email'],
            'phone': app_row['phone'] if 'phone' in keys else 'N/A',
            'degree': app_row['degree'] if 'degree' in keys else 'N/A',
            'resume': app_row['resume_filename'],
            'score': app_row['match_score'],
            'matched': json.loads(app_row['matched_skills']) if 'matched_skills' in keys and app_row['matched_skills'] else [],
            'missing': json.loads(app_row['missing_skills']) if 'missing_skills' in keys and app_row['missing_skills'] else [],
            'status': app_row['status'] if 'status' in keys else 'Under Review'
        })

    return render_template('recruiter_dashboard.html', job=job, applications=applications)

@app.route('/update-status/<int:app_id>/<string:new_status>/<int:job_id>')
def update_status(app_id, new_status, job_id):
    if session.get('role') != 'recruiter':
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))

    conn = get_db()
    app_data = conn.execute('SELECT candidate_name, email FROM applications WHERE id = ?', (app_id,)).fetchone()
    job_data = conn.execute('SELECT title FROM jobs WHERE id = ?', (job_id,)).fetchone()
    
    conn.execute('UPDATE applications SET status = ? WHERE id = ?', (new_status, app_id))
    conn.commit()
    conn.close()

    if app_data and job_data:
        send_status_email(
            candidate_email=app_data['email'],
            candidate_name=app_data['candidate_name'],
            job_title=job_data['title'],
            status=new_status
        )

    return redirect(url_for('view_candidates', job_id=job_id))

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)