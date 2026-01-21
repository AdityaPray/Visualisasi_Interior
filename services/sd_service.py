import os
import joblib
import requests
import base64
import re
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

device = "cuda" if torch.cuda.is_available() else "cpu"

class AIService:
    def __init__(self):
        # URL BASE dari Ngrok Colab
        self.colab_base_url = "https://unrighted-allie-ferruginous.ngrok-free.dev" 
        
        # Inisialisasi placeholder model
        self.t5_model = None
        self.t5_tokenizer = None
        self.rf_model = None
        self.tfidf = None

    def load_models(self, base_path):
        """Memuat semua model: T5 Lokal dan Sentiment Analysis Lokal"""
        
        # 1. Load T5 (Prompt Generator)
        try:
            t5_dir = os.path.join(base_path, "prompt_generator_final_model_t5")
            self.t5_tokenizer = AutoTokenizer.from_pretrained(t5_dir, use_fast=False) 
            self.t5_model = AutoModelForSeq2SeqLM.from_pretrained(t5_dir).to(device)
            print("✅ INFO: Model T5 Lokal Berhasil Dimuat.")
        except Exception as e:
            print(f"⚠️ WARN: Gagal memuat T5 lokal: {e}")

        # 2. Load Sentiment Analysis (Random Forest & TF-IDF)
        try:
            model_path = os.path.join(base_path, "model_reviewer_rf.pkl")
            tfidf_path = os.path.join(base_path, "tfidf_reviewer.pkl")
            self.rf_model = joblib.load(model_path)
            self.tfidf = joblib.load(tfidf_path)
            print("✅ INFO: Model Sentimen Berhasil Dimuat.")
        except Exception as e:
            print(f"❌ ERROR: Gagal memuat model sentimen: {e}")

        print("ℹ️ INFO: Chatbot & Stable Diffusion dialihkan ke Cloud (Colab).")

    # --- FUNGSI SENTIMEN (LOKAL) ---
    def clean_text(self, text):
        text = str(text).lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\d+', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def predict_sentiment(self, text):
        """Fungsi untuk memprediksi sentimen ulasan"""
        if not self.rf_model or not self.tfidf:
            return None, "Model belum dimuat"
            
        cleaned = self.clean_text(text)
        vec = self.tfidf.transform([cleaned])
        prediction = int(self.rf_model.predict(vec)[0])
        
        # Tentukan label
        if prediction >= 4:
            label = "POSITIF"
        elif prediction <= 2:
            label = "NEGATIF"
        else:
            label = "NETRAL"
            
        return prediction, label

    # --- FUNGSI CHATBOT (CLOUD) ---
    def get_chat_response(self, user_input):
        try:
            url = f"{self.colab_base_url}/chat"
            payload = {"message": user_input}
            response = requests.post(url, json=payload, timeout=60)
            if response.status_code == 200:
                return response.json().get("reply", "Maaf, tidak ada jawaban.")
            return f"Error Server Cloud ({response.status_code})"
        except Exception as e:
            return f"Gagal terhubung ke Cloud: {str(e)}"

    # --- FUNGSI IMAGE GENERATION (CLOUD) ---
    def generate_staged_image(self, prompt, negative_prompt, canny_image_path):
        try:
            with open(canny_image_path, "rb") as img_file:
                img_b64 = base64.b64encode(img_file.read()).decode('utf-8')

            url = f"{self.colab_base_url}/generate"
            payload = {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "image": img_b64
            }
            response = requests.post(url, json=payload, timeout=180)
            if response.status_code == 200:
                result_data = response.json().get("generated_image")
                return base64.b64decode(result_data)
            return None
        except Exception as e:
            print(f"Gagal generate di Cloud: {e}")
            return None

    # --- FUNGSI PROMPT GENERATOR (LOKAL) ---
    def generate_prompt(self, room_type, style, w, l, h):
        input_text = f"generate prompt: jenis_ruangan: {room_type}, gaya: {style}, lebar: {w}m, panjang: {l}m, tinggi: {h}m"
        ids = self.t5_tokenizer.encode(input_text, return_tensors="pt").to(device)
        outputs = self.t5_model.generate(ids, max_length=128, num_beams=4, do_sample=True)
        return self.t5_tokenizer.decode(outputs[0], skip_special_tokens=True)

# Inisialisasi Singleton
ai_service = AIService()