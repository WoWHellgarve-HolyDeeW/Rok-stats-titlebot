#!/usr/bin/env python3
"""
Teste para debugar o OCR do chat e ver o que está sendo capturado.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np
from PIL import Image

# ADB
ADB_PATH = "deps/platform-tools/adb.exe"
DEVICE = "localhost:5555"

# Tesseract config
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSDATA_PATH = os.path.join(os.path.dirname(__file__), 'deps', 'tessdata')
os.environ['TESSDATA_PREFIX'] = TESSDATA_PATH

import pytesseract
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

def screenshot():
    """Captura screenshot via ADB."""
    import subprocess
    result = subprocess.run(
        [ADB_PATH, "-s", DEVICE, "exec-out", "screencap", "-p"],
        capture_output=True
    )
    if result.returncode != 0:
        return None
    nparr = np.frombuffer(result.stdout, np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)

def main():
    print("Debug OCR Chat\n")
    
    screen = screenshot()
    if screen is None:
        print("ERROR: Não consegui capturar screenshot")
        return
    
    # Área do chat: (0, 500, 500, 850)
    x1, y1, x2, y2 = 0, 500, 500, 850
    chat_area = screen[y1:y2, x1:x2]
    
    # Salvar para referência
    cv2.imwrite("debug/chat_area_ocr.png", chat_area)
    print("Screenshot salva em debug/chat_area_ocr.png")
    
    pil_img = Image.fromarray(cv2.cvtColor(chat_area, cv2.COLOR_BGR2RGB))
    
    # Método 1: image_to_string
    print("\n=== image_to_string ===")
    text = pytesseract.image_to_string(pil_img, config='--psm 6')
    print(text)
    
    # Método 2: image_to_data
    print("\n=== image_to_data (palavras) ===")
    data = pytesseract.image_to_data(pil_img, config='--psm 6', output_type=pytesseract.Output.DICT)
    
    for i in range(len(data['text'])):
        word = data['text'][i].strip()
        if word:
            top = data['top'][i]
            left = data['left'][i]
            print(f"  Y={top:3d} X={left:3d}: '{word}'")
    
    # Procurar tags [XXXX]
    print("\n=== Procurar tags [XXXX] ===")
    import re
    for i, word in enumerate(data['text']):
        match = re.search(r'\[([A-Za-z0-9]{2,5})\]', word)
        if match:
            print(f"  Tag encontrada: {match.group(0)} (palavra: '{word}')")
    
    # Procurar no texto completo
    matches = re.findall(r'\[([A-Za-z0-9]{2,5})\]', text)
    if matches:
        print(f"  Tags no texto completo: {matches}")
    else:
        print("  Nenhuma tag encontrada no texto completo")

if __name__ == "__main__":
    main()
