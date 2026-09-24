import os
import sqlite3
from flask import Flask, render_template, render_template_string, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from jinja2.exceptions import TemplateNotFound

try:
    from email_service import send_status_email
except ImportError:
    def send_status_email(to_email, status, job_title):
        print(f"Notification: {to_email} -> Status: {status} for {job_title}")

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.secret_key = "ai_job_portal_super_permanent_secret_key_2026"
app.config['SESSION_COOKIE_NAME'] = 'job_portal_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = True

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

# --- CRASH-PROOF BUILT-IN HTML TEMPLATES ---
BASE_STYLE = """
<style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }
    .container { max-width: 900px; margin: 0 auto; }
    .card { background: #1e293b; padding: 25px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }
    .nav { display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; border-bottom: 1px solid #334155; padding-bottom: 15px; }
    .btn { display: inline-block; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-weight: bold; cursor: pointer; border: none; }
    .btn-blue { background: #2563eb; color: #fff; }
    .btn-green { background: #16a34a; color: #fff; }
    .btn-red { background: #dc2626; color: #fff; }
    table { width: 100%; border-collapse: collapse; margin-top: 15px; }
    th, td { padding: 12px; text-align: left; border-bottom: 1px solid #334155; }
    th { background: #0f172a; color: #38bdf8; }
    input, textarea { width: 100%; padding: 10px; border-radius: 6px; border: 1px solid #334155; background: #0f172a; color: #fff; box-sizing: border-box; margin-bottom: 15px; }
</style>
"""

HTML_RECRUITER_DASHBOARD = BASE_STYLE + """
<div class="container">
    <div class="nav">
        <h2>Recruiter Dashboard</h2>
        <div>
            <a href="/recruiter/post-job" class="btn btn-blue">+ Post New Job</a>
            <a href="/logout" class="btn btn-red" style="margin-left: 10px;">Logout</a>
        </div>
    </div>
    <div class="card">
        <h3>Your Posted Jobs</h3>
        {% if jobs %}
            <table>
                <tr>
                    <th>Job Title</th>
                    <th>Company</th>
                    <th>Cutoff</th>
                    <th>Action</th>
                </tr>
                {% for job in jobs %}
                <tr>
                    <td><b>{{ job['title'] }}</b></td>
                    <td>{{ job['company'] }}</td>
                    <td>{{ job['cutoff'] }}%</td>
                    <td><a href="/recruiter/applications/{{ job['id'] }}" class="btn btn-blue">View Applicants</a></td>
                </tr>
                {% endfor %}
            </table>
        {% else %}
            <p style="color: #94a3b8;">No jobs posted yet. Click "+ Post New Job" to start.</p>
        {% endif %}
    </div>
</div>
"""

HTML_POST_JOB = BASE_STYLE + """
<div class="container" style="max-width: 600px;">
    <div class="card">
        <h2>Post a New Job</h2>
        <form method="POST" action="/recruiter/post-job">
            <label>Job Title</label>
            <input type="text" name="title" required placeholder="e.g. Python Developer">
            <label>Company Name</label>
            <input type="text" name="company" required placeholder="e.g. TechCorp">
            <label>AI Match Cutoff Score (%)</label>
            <input type="number" name="cutoff" value="40" min="1" max="100" required>
            <label>Job Description & Skills Required</label>
            <textarea name="description" rows="5" required placeholder="Paste requirements here..."></textarea>
            <button type="submit" class="btn btn-blue" style="width: 100%;">Create Job</button>
        </form>
        <p style="text-align: center; margin-top: 15px;"><a href="/recruiter/dashboard" style="color: #38bdf8;">Back to Dashboard</a></p>
    </div>
</div>
"""

HTML_VIEW_APPLICATIONS = BASE_STYLE + """
<div class="container">
    <div class="nav">
        <h2>Applicants for {{ job['title'] }}</h2>
        <a href="/recruiter/dashboard" class="btn btn-blue">Back to Dashboard</a>
    </div>
    <div class="card">
        {% if applications %}
            <table>
                <tr>
                    <th>Candidate</th>
                    <th>Email</th>
                    <th>AI Match Score</th>
                    <th>Status</th>
                    <th>Actions</th>
                </tr>
                {% for app in applications %}
                <tr>
                    <td><b>{{ app['candidate_name'] }}</b></td>
                    <td>{{ app['candidate_email'] }}</td>
                    <td><span style="color: #38bdf8; font-weight: bold;">{{ app['match_score'] }}%</span></td>
                    <td><b>{{ app['status'] }}</b></td>
                    <td>
                        <a href="/update-status/{{ app['id'] }}/Shortlisted/{{ job['id'] }}" class="btn btn-green">Shortlist</a>
                        <a href="/update-status/{{ app['id'] }}/Rejected/{{ job['id'] }}" class="btn btn-red">Reject</a>
                    </td>
                </tr>
                {% endfor %}
            </table>
        {% else %}
            <p style="color: #94a3b8;">No applications received yet for this position.</p>
        {% endif %}
    </div>
</div>
"""

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

    try:
        return render_template('signup.html')
    except Exception:
        try:
            return render_template('register.html')
        except Exception:
            return render_template_string(HTML_POST_JOB)

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

    try:
        return render_template('recruiter_dashboard.html', jobs=jobs)
    except Exception:
        return render_template_string(HTML_RECRUITER_DASHBOARD, jobs=jobs)

@app.route('/recruiter/post-job', methods=['GET', 'POST'])
def post_job():
    role = str(session.get('role', '')).strip().lower()
    if 'user_id' not in session or role != 'recruiter':
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        company = request.form.get('company', '').strip()
        cutoff = int(request.form.get('cutoff', 40))
        description = request.form.get('description', '').strip()

        conn = get_db_connection()
        conn.execute('INSERT INTO jobs (recruiter_id, title, company, cutoff, description) VALUES (?, ?, ?, ?, ?)',
                     (session['user_id'], title, company, cutoff, description))
        conn.commit()
        conn.close()
        return redirect(url_for('recruiter_dashboard'))

    try:
        return render_template('post_job.html')
    except Exception:
        return render_template_string(HTML_POST_JOB)

@app.route('/recruiter/applications/<int:job_id>')
def view_applications(job_id):
    role = str(session.get('role', '')).strip().lower()
    if 'user_id' not in session or role != 'recruiter':
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

    try:
        return render_template('view_applications.html', job=job, applications=applications)
    except Exception:
        return render_template_string(HTML_VIEW_APPLICATIONS, job=job, applications=applications)

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
            print(f"Notification bypassed: {e}")

    return redirect(url_for('view_applications', job_id=job_id))

@app.route('/candidate/dashboard')
def candidate_dashboard():
    role = str(session.get('role', '')).strip().lower()
    if 'user_id' not in session or role != 'candidate':
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
    role = str(session.get('role', '')).strip().lower()
    if 'user_id' not in session or role != 'candidate':
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
