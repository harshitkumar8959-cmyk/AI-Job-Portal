import pypdf
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Skill Roadmap Links
SKILL_ROADMAPS = {
    'python': 'https://roadmap.sh/python',
    'flask': 'https://flask.palletsprojects.com/en/latest/tutorial/',
    'sql': 'https://www.w3schools.com/sql/',
    'sqlite': 'https://www.sqlitetutorial.net/',
    'machine learning': 'https://www.coursera.org/learn/machine-learning',
    'scikit-learn': 'https://scikit-learn.org/stable/tutorial/index.html',
    'docker': 'https://roadmap.sh/docker',
    'git': 'https://roadmap.sh/git-github',
    'rest apis': 'https://restfulapi.net/',
    'react': 'https://roadmap.sh/react',
    'javascript': 'https://roadmap.sh/javascript'
}

def extract_text_from_pdf(pdf_path):
    text = ""
    try:
        reader = pypdf.PdfReader(pdf_path)
        for page in reader.pages:
            content = page.extract_text()
            if content:
                text += content + " "
    except Exception as e:
        print(f"Error reading PDF: {e}")
    return text.lower()

def extract_contact_info(text):
    phone_pattern = r'(\+?\d{1,3}[\s-]?)?\(?\d{3,5}\)?[\s.-]?\d{3,5}[\s.-]?\d{3,5}'
    phone_match = re.search(phone_pattern, text)
    phone = phone_match.group(0).strip() if phone_match else "Not Found"

    degrees = ['b.tech', 'm.tech', 'bca', 'mca', 'b.sc', 'm.sc', 'bachelor', 'master', 'b.e', 'diploma']
    found_degree = "Graduate / Fresher"
    for deg in degrees:
        if re.search(r'\b' + re.escape(deg) + r'\b', text):
            found_degree = deg.upper()
            break

    return phone, found_degree

def calculate_match_score(resume_text, job_desc):
    resume_clean = resume_text.lower()
    desc_clean = job_desc.lower()

    # 1. Detect required skills in JD
    required_skills = [skill for skill in SKILL_ROADMAPS.keys() if skill in desc_clean]
    
    # Agar JD me koi pre-listed skill nahi likhi toh default 3-4 standard skills assume karein
    if not required_skills:
        required_skills = ['python', 'sql', 'git']

    # 2. Check matched & missing skills
    matched_skills = [skill.title() for skill in required_skills if skill in resume_clean]
    missing_skills = [skill for skill in required_skills if skill not in resume_clean]

    # Skill match ratio (0.0 to 1.0)
    skill_ratio = len(matched_skills) / len(required_skills) if required_skills else 1.0

    # 3. TF-IDF Contextual Similarity
    vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = vectorizer.fit_transform([resume_clean, desc_clean])
    tfidf_sim = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]

    # 4. HYBRID WEIGHTED SCORE:
    # 70% weightage to actual required skills + 30% weightage to text/context similarity
    final_score = (skill_ratio * 70.0) + (tfidf_sim * 30.0)
    final_score = round(min(final_score, 100.0), 1)

    # Missing recommendations formatting
    missing_recommendations = []
    for skill in missing_skills:
        missing_recommendations.append({
            'skill': skill.title(),
            'link': SKILL_ROADMAPS.get(skill, 'https://google.com/search?q=' + skill + '+tutorial')
        })

    return final_score, matched_skills, missing_recommendations