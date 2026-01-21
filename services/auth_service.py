import os
from flask.cli import load_dotenv
from flask_dance.contrib.google import make_google_blueprint
from dotenv import load_dotenv
# Tambahkan ini di baris awal sebelum inisialisasi lainnya
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
os.environ['PREFERRED_URL_SCHEME'] = 'https'

def create_google_blueprint():
    # Nama blueprint adalah 'google'
    google_bp = make_google_blueprint(
        load_dotenv()
        CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
        CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
        scope=[
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/userinfo.email",
            "openid"
        ],
        redirect_to="google_login_callback", # Nama fungsi di app.py
        offline=True
    )
    return google_bp