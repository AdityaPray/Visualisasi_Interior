from datetime import datetime
from extension import db
from flask_login import UserMixin

class User(db.Model, UserMixin):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=True) # Sesuai gambar db, password bisa NULL jika OAuth
    google_id = db.Column(db.String(100), nullable=True) # Sesuai gambar db
    role = db.Column(db.String(20), default='user')
    feedbacks = db.relationship('Feedback', backref='user', lazy=True)

class ImageHistory(db.Model):
    __tablename__ = 'image_history'
    id = db.Column(db.Integer, primary_key=True) # Sesuai gambar db: AUTO_INCREMENT
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # Sesuai gambar db
    prompt = db.Column(db.Text, nullable=True) # Sesuai gambar db: text
    image_filename = db.Column(db.String(255), nullable=True) # Sesuai gambar db: varchar(255)
    created_at = db.Column(db.Integer, nullable=True) # Sesuai gambar db: int

# --- TABEL BARU UNTUK SENTIMEN ANALISIS ---
class Feedback(db.Model):
    __tablename__ = 'feedback'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Data ulasan asli
    content = db.Column(db.Text, nullable=False)
    star_rating = db.Column(db.Integer, nullable=False) # Rating 1-5 dari user
    
    # Data hasil olahan model AI (.pkl)
    ai_score = db.Column(db.Integer, nullable=True)     # Prediksi rating 1-5 oleh AI
    sentiment = db.Column(db.String(20), nullable=True)  # POSITIF, NEGATIF, atau NETRAL
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)