#!/usr/bin/env python3
"""
Extract key fields from ID card images inside a PDF (PAN / Aadhaar / generic).
Outputs JSON per page.

Notes:
- Requires poppler (pdf2image) and tesseract installed on system.
- Tweak preprocessing thresholds for your image quality.
"""

import json
import re
from pathlib import Path
from pdf2image import convert_from_path
import pytesseract
import cv2
import numpy as np
from dateutil import parser as dateparser
from fuzzywuzzy import fuzz

# ---------- Config ----------
PDF_PATH = r"C:\\Users\\Rohith Macharla\\OneDrive\\Desktop\\bnp\\Data\\IN-Arjun Mehta.pdf"   # 👈 set your PDF here
OUTPUT_JSONL = r"output1.json"
POPPLER_PATH = r"C:\\poppler-25.07.0\\Library\\bin"   # 👈 path to poppler/bin
pytesseract.pytesseract.tesseract_cmd = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"

# ---------- Regex patterns ----------
PAN_REGEX = r'\b([A-Z]{5}[0-9]{4}[A-Z])\b'
AADHAAR_REGEX = r'\b([0-9]{4}\s?[0-9]{4}\s?[0-9]{4})\b'
DOB_REGEX = r'(\d{2}[\/\-\s]\d{2}[\/\-\s]\d{4}|\d{4}[\/\-\s]\d{2}[\/\-\s]\d{2})'
YEAR_REGEX = r'\b(19|20)\d{2}\b'

NAME_LABELS = ['name', 'surname', 'given name', 'full name', 'नाम', 'name:']
DOB_LABELS = ['dob', 'date of birth', '.birth', 'D.O.B', 'जन्मतिथि', 'dob:']
FATHER_LABELS = ['father', "father's name", 'father name', 'paternal']
GENDER_LABELS = ['male', 'female', 'm', 'f']

# ---------- image helpers ----------
def pdf_to_images(pdf_path, dpi=300):
    return convert_from_path(pdf_path, dpi=dpi, poppler_path=POPPLER_PATH)

def preprocess_image(pil_image):
    img = np.array(pil_image)
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    if max(h, w) > 2000:
        scale = 2000 / max(h, w)
        gray = cv2.resize(gray, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)
    gray = cv2.fastNlMeansDenoising(gray, None, h=10)
    th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY, 25, 12)
    kernel = np.ones((1,1), np.uint8)
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, kernel)
    return th

def ocr_image(cv_image, lang='eng'):
    text = pytesseract.image_to_string(cv_image, lang=lang)
    try:
        data = pytesseract.image_to_data(cv_image, lang=lang, output_type=pytesseract.Output.DICT)
    except Exception:
        data = None
    return text, data

# ---------- extraction ----------
def find_pan(text):
    matches = re.findall(PAN_REGEX, text)
    if matches:
        for m in matches:
            cand = m.replace(' ', '').upper()
            if re.match(r'^[A-Z]{5}\d{4}[A-Z]$', cand):
                return cand
        return matches[0].replace(' ', '')
    return None

def find_aadhaar(text):
    matches = re.findall(AADHAAR_REGEX, text)
    if matches:
        for m in matches:
            digits = re.sub(r'\s+', '', m)
            if len(digits) == 12:
                return digits
        return re.sub(r'\s+', '', matches[0])
    return None

def find_dates(text):
    cand = re.findall(DOB_REGEX, text)
    parsed = []
    for c in cand:
        if isinstance(c, tuple):
            c = ''.join(c)
        try:
            dt = dateparser.parse(c, dayfirst=True, fuzzy=True)
            parsed.append(dt.date().isoformat())
        except Exception:
            yr = re.search(YEAR_REGEX, c)
            if yr:
                parsed.append(yr.group(0))
    return list(dict.fromkeys(parsed))

def find_name_from_lines(text_lines):
    for i, line in enumerate(text_lines):
        low = line.strip().lower()
        if any(lbl in low for lbl in NAME_LABELS):
            if ':' in line:
                parts = line.split(':',1)
                name = parts[1].strip()
                if name: return name
            if i+1 < len(text_lines):
                n = text_lines[i+1].strip()
                if len(n.split()) <= 5 and len(n)>2:
                    return n
    for line in text_lines:
        if sum(1 for c in line if c.isalpha()) > 4 and line.strip() == line.strip().upper():
            return line.strip().title()
    lines = [l.strip() for l in text_lines if len(l.strip())>2]
    return max(lines, key=len) if lines else None

def extract_fields_from_text(text):
    out = {}
    txt = text.replace('\r','\n')
    lines = [l for l in (ln.strip() for ln in txt.split('\n')) if l]
    joined = '\n'.join(lines)
    out['raw_text'] = joined

    pan = find_pan(joined)
    aad = find_aadhaar(joined)
    out['doc_number_candidates'] = {'pan': pan, 'aadhaar': aad}
    name_guess = find_name_from_lines(lines)
    dob_candidates = find_dates(joined)
    out['name_guess'] = name_guess
    out['dob_candidates'] = dob_candidates

    father = None
    for l in lines:
        if 'father' in l.lower():
            parts = l.split(':',1)
            if len(parts)>1 and parts[1].strip():
                father = parts[1].strip()
                break
    out['father_name_guess'] = father

    if pan:
        out['doc_type'] = 'PAN'
        out['doc_number'] = pan
    elif aad:
        out['doc_type'] = 'AADHAAR'
        out['doc_number'] = aad
    else:
        out['doc_type'] = 'UNKNOWN'
        out['doc_number'] = None

    out['dob'] = dob_candidates[0] if dob_candidates else None
    return out

# ---------- pipeline ----------
def process_pdf(input_pdf, output_jsonl_path):
    pages = pdf_to_images(input_pdf, dpi=300)
    results = []
    for page_idx, pil_img in enumerate(pages, start=1):
        img = preprocess_image(pil_img)
        text, data = ocr_image(img, lang='eng')
        fields = extract_fields_from_text(text)

        # --- FIXED confidence block ---
        if data and 'conf' in data:
            confs = []
            for x in data['conf']:
                try:
                    val = int(x)
                    if val != -1:
                        confs.append(val)
                except (ValueError, TypeError):
                    continue
            fields['ocr_conf_mean'] = sum(confs)/len(confs)/100.0 if confs else None
        else:
            fields['ocr_conf_mean'] = None

        # --- Image quality ---
        try:
            arr = np.array(pil_img.convert('L'))
            lap = cv2.Laplacian(arr, cv2.CV_64F).var()
            blur_score = 1.0 if lap < 50 else 0.0 if lap > 300 else (300-lap)/250.0
            contrast_score = float(np.std(arr))/128.0
            fields['image_quality'] = {
                'blur_score': min(max(0.0, blur_score), 1.0),
                'contrast_score': min(max(0.0, contrast_score), 1.0)
            }
        except Exception:
            fields['image_quality'] = {'blur_score': None, 'contrast_score': None}

        fields['page'] = page_idx
        fields['name_match_score'] = None
        results.append(fields)

    out_path = Path(output_jsonl_path)
    with out_path.open('w', encoding='utf8') as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    return results

# ---------- run directly ----------
if __name__ == '__main__':
    print(f"Processing {PDF_PATH} ...")
    res = process_pdf(PDF_PATH, OUTPUT_JSONL)
    print(f"✅ Extracted {len(res)} pages. Saved to {OUTPUT_JSONL}")
