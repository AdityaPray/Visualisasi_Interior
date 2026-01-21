import os
import time
import torch
import jwt
import datetime
import threading
import gc
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from flask_dance.contrib.google import google
from PIL import Image
from werkzeug.middleware.proxy_fix import ProxyFix


# Import modul internal
from extension import db, bcrypt, login_manager
from models import Feedback, User, ImageHistory
from services.auth_service import create_google_blueprint
from services.image_service import get_canny_image
from services.sd_service import ai_service 
from sqlalchemy import func

app = Flask(__name__)
@app.after_request
def add_header(response):
    # 1. Set header 'ngrok-skip-browser-warning' dengan nilai apa saja
    response.headers['ngrok-skip-browser-warning'] = 'true'
    
    # 2. Set cookie untuk memastikan browser/bot yang mendukung cookie juga lolos
    response.set_cookie('ngrok-skip-browser-warning', 'true')
    
    # 3. Set User-Agent custom/non-standard (Saran kedua dari ngrok)
    # Ini akan menipu ngrok agar menganggap ini bukan browser standar yang butuh proteksi
    response.headers['User-Agent'] = 'CapstoneProject-Bot-Testing'
    
    return response
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = "capstone_staging_ai_secret"
app.config["SQLALCHEMY_DATABASE_URI"] = "mysql+pymysql://root@localhost/staging_ai"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config['GENERATED_FOLDER'] = os.path.join('static', 'outputs')

if not os.path.exists(app.config['GENERATED_FOLDER']):
    os.makedirs(app.config['GENERATED_FOLDER'])

# Inisialisasi Extensions
db.init_app(app)
bcrypt.init_app(app)
login_manager.init_app(app)

# Lock untuk mencegah Double Inference
generation_lock = threading.Lock()

# Register Google Blueprint (Untuk Web)
app.register_blueprint(create_google_blueprint(), url_prefix="/login")

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# ================= JWT DECORATOR (Untuk Android) =================

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        try:
            # Format: Authorization: Bearer <token>
            token = token.split(" ")[1] 
            data = jwt.decode(token, app.secret_key, algorithms=["HS256"])
            current_user_api = db.session.get(User, data['user_id'])
            if not current_user_api:
                raise Exception("User not found")
        except:
            return jsonify({'message': 'Token is invalid!'}), 401
        return f(current_user_api, *args, **kwargs)
    return decorated


# ================= API ROUTES (UNTUK ANDROID) =================

@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.json
    email = data.get("email")
    
    if User.query.filter_by(email=email).first():
        return jsonify({"message": "Email sudah terdaftar"}), 400
        
    hashed_pw = bcrypt.generate_password_hash(data.get("password")).decode('utf-8')
    # Tambahkan role='user' untuk memastikan mereka bukan admin
    new_user = User(name=data.get("name"), email=email, password=hashed_pw, role='user') 
    db.session.add(new_user)
    db.session.commit()
    
    return jsonify({"status": "success", "message": "Registrasi berhasil"})

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json
    user = User.query.filter_by(email=data.get("email")).first()
    if user and user.password and bcrypt.check_password_hash(user.password, data.get("password")):
        token = jwt.encode({
            'user_id': user.id,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        }, app.secret_key, algorithm="HS256")
        return jsonify({"token": token, "status": "success"})
    return jsonify({"message": "Email atau password salah"}), 401

@app.route("/api/login-google", methods=["POST"])
def api_login_google():
    data = request.json
    email = data.get("email")
    user = User.query.filter_by(email=email).first()
    
    if not user:
        user = User(name=data.get("name"), email=email, google_id=data.get("google_id"), role='user')
        db.session.add(user)
        db.session.commit()
    
    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    }, app.secret_key, algorithm="HS256")
    
    return jsonify({"token": token, "status": "success"})

@app.route("/api/history", methods=["GET"])
@token_required
def api_get_history(current_user_api):
    histories = ImageHistory.query.filter_by(user_id=current_user_api.id).order_by(ImageHistory.id.desc()).all()
    data = [{
        "id": h.id,
        "prompt": h.prompt,
        "image_url": url_for('display_image', filename=h.image_filename, _external=True),
        "created_at": h.created_at
    } for h in histories]
    return jsonify({"status": "success", "data": data})

@app.route("/api/history/delete/<int:history_id>", methods=["DELETE"])
@token_required
def api_delete_history(current_user_api, history_id):
    history = ImageHistory.query.filter_by(id=history_id, user_id=current_user_api.id).first()
    if not history:
        return jsonify({"message": "Histori tidak ditemukan"}), 404
    try:
        # Hapus file fisik
        file_path = os.path.join("static/outputs", history.image_filename)
        if os.path.exists(file_path):
            os.remove(file_path)
        
        db.session.delete(history)
        db.session.commit()
        return jsonify({"status": "success", "message": "Histori berhasil dihapus"})
    except Exception as e:
        return jsonify({"message": str(e)}), 500

# ================= FEEDBACK ROUTES (API) =================

@app.route("/api/feedback", methods=["POST"])
@token_required
def api_submit_feedback(current_user_api):
    data = request.json
    content = data.get("content")
    star_rating = data.get("star_rating")

    # PANGGIL FUNGSI DARI AISERVICE
    score, label = ai_service.predict_sentiment(content)

    new_fb = Feedback(
        user_id=current_user_api.id,
        content=content,
        star_rating=star_rating,
        ai_score=score,
        sentiment=label
    )
    db.session.add(new_fb)
    db.session.commit()

    return jsonify({"status": "success", "sentiment": label})

# ================= PROFILE ROUTES (API) =================

@app.route("/api/profile", methods=["GET"])
@token_required
def api_get_profile(current_user_api):
    # Mengambil data user yang login berdasarkan token
    return jsonify({
        "status": "success",
        "data": {
            "id": current_user_api.id,
            "name": current_user_api.name,
            "email": current_user_api.email,
            "google_id": current_user_api.google_id
        }
    })

@app.route("/api/profile/update", methods=["POST"])
@token_required
def api_update_profile(current_user_api):
    data = request.json
    new_name = data.get("name")
    new_email = data.get("email", "").strip()
    new_password = data.get("password")

    if not new_name or not new_email:
        return jsonify({"message": "Nama dan Email wajib diisi"}), 400

    try:
        # Ambil user langsung dari DB agar objek terikat dengan session aktif
        user = db.session.get(User, current_user_api.id)
        
        if not user:
            return jsonify({"message": "User tidak ditemukan"}), 404

        # Cek duplikasi email (kecuali email milik user itu sendiri)
        if new_email != user.email:
            existing_user = User.query.filter_by(email=new_email).first()
            if existing_user:
                return jsonify({"message": "Email sudah digunakan oleh akun lain"}), 400

        # Update data
        user.name = new_name
        user.email = new_email
        
        if new_password and len(new_password.strip()) >= 6:
            # PENTING: Gunakan bcrypt (bukan werkzeug) agar sinkron dengan login
            user.password = bcrypt.generate_password_hash(new_password).decode('utf-8')
            print(f"DEBUG: Password diupdate untuk {user.email}")
        
        # Eksekusi simpan
        db.session.commit()
        
        return jsonify({"status": "success", "message": "Profil berhasil diperbarui"})
    
    except Exception as e:
        db.session.rollback() # Batalkan jika ada error
        print(f"CRITICAL ERROR: {str(e)}") 
        return jsonify({
            "status": "error",
            "message": "Gagal menyimpan ke database.",
            "details": str(e)
        }), 500
    

# ================= CHATBOT API ROUTES =================

@app.route("/api/chat", methods=["POST"])
@token_required
def api_chat(current_user_api):
    data = request.json
    user_message = data.get("message")

    if not user_message:
        return jsonify({"message": "Pesan tidak boleh kosong"}), 400

    try:
        # Panggil fungsi yang baru kita buat di ai_service (sd_service.py)
        # Fungsi ini akan otomatis mengirim pesan ke Colab via Ngrok
        answer = ai_service.get_chat_response(user_message)

        return jsonify({
            "status": "success",
            "reply": answer
        })

    except Exception as e:
        print(f"CHAT ERROR: {str(e)}")
        return jsonify({
            "message": "Gagal memproses pesan ke chatbot cloud", 
            "error": str(e)
        }), 500
    
# ================= GENERATE LOGIC (UNIFIED - CLOUD MODE) =================

@app.route("/generate", methods=["POST"])
@login_required
def generate():
    return _process_generation(current_user, is_api=False)

@app.route("/api/generate", methods=["POST"])
@token_required
def api_generate(current_user_api):
    return _process_generation(current_user_api, is_api=True)

def _process_generation(user_obj, is_api=False):
    # 1. Lock agar tidak ada proses bersamaan (Concurrency Control)
    if not generation_lock.acquire(blocking=False):
        msg = "Server sibuk memproses gambar lain."
        if is_api:
            return jsonify({"message": msg}), 429
        else:
            flash(msg, "warning")
            return redirect(url_for("index"))

    try:
        # 2. Validasi Input Gambar
        file = request.files.get("image")
        if not file:
            msg = "File gambar tidak ditemukan."
            if is_api:
                return jsonify({"message": msg}), 400
            else:
                flash(msg, "danger")
                return redirect(url_for("index"))

        # 3. Proses Canny Lokal (Laptop)
        # Kita resize ke 512x512 agar proses upload ke Colab lebih cepat
        pil_img = Image.open(file).convert("RGB")
        canny_img = get_canny_image(pil_img).resize((512, 512))
        
        # Simpan canny sementara sebagai perantara
        canny_temp_path = f"temp_canny_{user_obj.id}.png"
        canny_img.save(canny_temp_path)
        # 5. Generate Prompt Menggunakan T5 (Lokal di Laptop)
        # Menghasilkan deskripsi AI berdasarkan tipe ruangan & gaya
        prompt_ai = ai_service.generate_prompt(
        request.form.get('room_type'), request.form.get('style'),
        request.form.get('width'), request.form.get('length'), request.form.get('height')
        )
        negative_prompt = "low quality, blurry, distorted, messy room, low resolution, bad anatomy"
        full_prompt = f"{prompt_ai}, photorealistic, 8k, interior photography, highly detailed"
        
        # 6. PANGGIL COLAB API (Proses AI Berat di Cloud)
        print(f"Mengirim permintaan generate ke Colab untuk user {user_obj.id}...")
        output_bytes = ai_service.generate_staged_image(full_prompt, negative_prompt, canny_temp_path)
        
        if not output_bytes:
            raise Exception("Colab tidak mengembalikan gambar. Pastikan Colab aktif & Ngrok benar.")

        # 7. Simpan Hasil Akhir ke Folder Static
        output_filename = f"gen_{user_obj.id}_{int(time.time())}.png"
        output_path = os.path.join(app.config['GENERATED_FOLDER'], output_filename)
        
        with open(output_path, "wb") as f:
            f.write(output_bytes)

        # 8. Simpan ke Database (Sesuaikan nama kolom dengan model Anda)
        # Diasumsikan model database Anda bernama 'Generation'
        new_history = ImageHistory(
        user_id=user_obj.id, 
        prompt=full_prompt, 
        image_filename=output_filename, # Sesuai nama kolom di models.py
        created_at=int(time.time())      # Sesuai tipe data Integer di models.py
        )
        db.session.add(new_history)
        db.session.commit()

        # 9. Bersihkan File Temporary
        if os.path.exists(canny_temp_path):
            os.remove(canny_temp_path)

        # 10. Return Response
        if is_api:
            # Gunakan url_for agar Flutter mendapatkan URL lengkap (http://IP:PORT/...)
            full_image_url = url_for('display_image', filename=output_filename, _external=True)
            return jsonify({
                "status": "success",
                "message": "Gambar berhasil dibuat",
                "image_url": full_image_url, # BENAR: Mengirim URL lengkap
                "prompt": full_prompt
            })
        else:
            flash("Gambar berhasil dibuat!", "success")
            return redirect(url_for("history"))

    except Exception as e:
        print(f"GENERATION ERROR: {str(e)}")
        error_msg = f"Gagal memproses gambar: {str(e)}"
        if is_api:
            return jsonify({"message": error_msg}), 500
        else:
            flash(error_msg, "danger")
            return redirect(url_for("index"))
            
    finally:
        # Selalu buka lock di akhir proses, baik sukses maupun gagal
        generation_lock.release()


# ================= WEB ROUTES =================

@app.route("/")
def index():
    # Jika sudah login, langsung ke dashboard, jika tidak ke login
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
    return redirect(url_for('login'))

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard'))
        
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        user = User.query.filter_by(email=email).first()
        
        # Validasi: Cek user ada, password cocok, dan dia adalah ADMIN
        if user and bcrypt.check_password_hash(user.password, password):
            if user.role == 'admin':
                login_user(user)
                flash("Selamat datang, Admin!", "success")
                return redirect(url_for("admin_dashboard"))
            else:
                flash("Akses ditolak: Anda bukan admin.", "danger")
        else:
            flash("Email atau password salah.", "danger")
            
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Anda telah keluar.", "info")
    return redirect(url_for("login"))

@app.route("/admin/dashboard")
@login_required
def admin_dashboard():
    # Proteksi: Hanya admin yang boleh masuk
    if current_user.role != 'admin':
        flash("Akses ditolak!", "danger")
        return redirect(url_for("login"))

    # Statistik untuk Diagram
    stats = db.session.query(
        Feedback.sentiment, func.count(Feedback.id)
    ).group_by(Feedback.sentiment).all()
    
    chart_data = {s[0]: s[1] for s in stats if s[0] is not None}
    
    # Ambil 5 review terbaru untuk tabel ringkasan
    recent_reviews = Feedback.query.order_by(Feedback.id.desc()).limit(5).all()

    return render_template("admin/dashboard.html", 
                           chart_data=chart_data, 
                           recent_reviews=recent_reviews)

@app.route("/admin/add-admin", methods=["GET", "POST"])
@login_required
def add_admin():
    if current_user.role != 'admin':
        return redirect(url_for("login"))

    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")

        if User.query.filter_by(email=email).first():
            flash("Email sudah terdaftar!", "warning")
        else:
            hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
            # Buat user baru dengan role ADMIN
            new_admin = User(name=name, email=email, password=hashed_pw, role='admin')
            db.session.add(new_admin)
            db.session.commit()
            flash(f"Admin {name} berhasil ditambahkan!", "success")
            return redirect(url_for("admin_dashboard"))

    return render_template("admin/add_admin.html")

@app.route("/admin/reviews")
@login_required
def admin_reviews():
    if current_user.role != 'admin':
        return redirect(url_for('login'))
    
    # Ambil semua ulasan dari database
    all_reviews = Feedback.query.order_by(Feedback.id.desc()).all()
    return render_template("admin/reviews.html", reviews=all_reviews)


@app.route('/static/outputs/<filename>')
def display_image(filename):
    return send_from_directory("static/outputs", filename)



if __name__ == "__main__":
    with app.app_context():
        ai_service.load_models("./models")
    app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=False)