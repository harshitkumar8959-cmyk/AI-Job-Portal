import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SENDER_EMAIL = "harshitkumar8959@gmail.com"
APP_PASSWORD = "xtxs ckqv qqgk oxpp"

def send_status_email(candidate_email, candidate_name, job_title, status):
    subject = f"Application Status Update: {job_title}"
    
    if status == 'Shortlisted':
        body = f"Dear {candidate_name},\n\nCongratulations!\n\nYour profile has been SHORTLISTED for the position of {job_title} based on our AI resume screening.\n\nOur team will connect with you soon.\n\nBest regards,\nTalent Acquisition Team"
    else:
        body = f"Dear {candidate_name},\n\nThank you for applying for the position of {job_title}.\n\nAfter reviewing your profile, we regret to inform you that we are not proceeding with your application at this time.\n\nBest regards,\nTalent Acquisition Team"

    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = candidate_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"[EMAIL SUCCESS] Mail sent to {candidate_email}")
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False