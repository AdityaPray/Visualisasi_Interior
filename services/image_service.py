import cv2
import numpy as np
from PIL import Image

def get_canny_image(pil_image, low_threshold=100, high_threshold=200):
    # Konversi PIL ke Numpy (RGB)
    img_np = np.array(pil_image.convert("RGB"))
    
    # Konversi ke Grayscale untuk deteksi tepi
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    
    # Blur sedikit untuk mengurangi noise pada hasil generate
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    
    # Algoritma Canny
    canny = cv2.Canny(blurred, low_threshold, high_threshold)
    
    # Balikkan ke format PIL (Grayscale 'L')
    return Image.fromarray(canny).convert("L")