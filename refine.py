#!/usr/bin/env python3
"""
Refine OCR-extracted JSON using Gemini API and apply advanced validation rules.
Input:  output1.json (line-delimited JSON from OCR pipeline)
Output: output_perfect.jsonl (clean, normalized, and validated fields)
"""

import json
import google.generativeai as genai
import re
from datetime import datetime
from difflib import SequenceMatcher
import dbintegration

# ---------- Config ----------
INPUT_FILE = "output.json"
OUTPUT_FILE = "output_perfect.jsonl"
GEMINI_MODEL = "gemini-1.5-flash"
API_KEY = "AIzaSyC9JVyWVJTZ0tJvq3nu6rj3cQ5YU_wxqbo"  # 👈 put your Gemini API key here

# ---------- Rule Engine Configuration ----------

# R002: High-risk jurisdictions (ISO codes, names, keywords)
HIGH_RISK_JURISDICTIONS = {
    "IR", "IRN", "IRAN",
    "KP", "PRK", "NORTH KOREA",
    "SY", "SYR", "SYRIA",
    "RU", "RUS", "RUSSIA", "RUSSIAN FEDERATION"
}

# R005: Simulated watchlist for Politically Exposed Persons (PEPs) or sanctioned individuals
# In a real system, this would be a call to an external API (e.g., OFAC, World-Check)
WATCHLIST = [
    {"first_name": "JOHN", "last_name": "DOE", "dob": "1980-01-15"},
    {"first_name": "JANE", "last_name": "SMITH", "dob": None}, # Match by name only
    {"first_name": "IVAN", "last_name": "PETROV", "dob": "1975-08-22"},
]

# ---------- Gemini client ----------
# Ensure you have the library installed: pip install google-generativeai
try:
    genai.configure(api_key=API_KEY)
    client = genai.GenerativeModel(GEMINI_MODEL)
except Exception as e:
    print(f"Error initializing Gemini client: {e}")
    print("Please ensure your API key is correct and you have the necessary permissions.")
    exit(1)

# ---------- Prompt Template (Unchanged) ----------
PROMPT_TEMPLATE = """
You are an expert in document information extraction for banking KYC.
Given OCR JSON of an ID/passport/bank statement, normalize it into structured JSON.

OCR JSON:
{ocr_json}

Return only JSON in this schema:
{{
  "doc_type": "...",
  "doc_number": "...",
  "first_name": "...",
  "last_name": "...",
  "dob": "...",
  "father_name": "...",
  "mother_name": "...",
  "place_of_birth": "...",
  "issue_date": "...",
  "expiry_date": "...",
  "address": "..."
}}
If a field is missing, put null. Do not add extra commentary.
"""

# ---------- Processing Functions ----------

def refine_with_gemini(entry):
    """Sends the OCR JSON to Gemini for cleaning and structuring."""
    # Using a slightly more robust prompt from your original code
    prompt = f"""
    Clean and extract structured details from this OCR JSON.
    Ensure correct names, dates, numbers, and document type.
    Return only valid JSON based on the schema provided.

    OCR JSON:
    {json.dumps(entry, ensure_ascii=False, indent=2)}
    
    SCHEMA:
    {{
      "doc_type": "...",
      "doc_number": "...",
      "first_name": "...",
      "last_name": "...",
      "dob": "...",
      "father_name": "...",
      "mother_name": "...",
      "place_of_birth": "...",
      "issue_date": "...",
      "expiry_date": "...",
      "address": "..."
    }}
    """
    try:
        resp = client.generate_content(contents=[prompt])
        cleaned_text = resp.candidates[0].content.parts[0].text.strip()

        # Remove ```json ... ``` wrappers if present
        if cleaned_text.startswith("```"):
            cleaned_text = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned_text)
            cleaned_text = re.sub(r"```$", "", cleaned_text)

        return json.loads(cleaned_text)
    except Exception as e:
        return {"error": f"Gemini API or JSON parsing failed: {e}", "raw": locals().get('cleaned_text', 'N/A')}

def check_watchlist(doc: dict):
    """
    Simulates checking a document's details against a predefined watchlist.
    Returns a dictionary with the match score.
    """
    
    if doc is None:
        return {"watchlist_match_score": 0.0}
    
    if(doc.get('doc_type') is None):
        return {"watchlist_match_score": 0.0}
    
    max_score = 0.0
    doc_first = doc.get("first_name", "").upper()
    doc_last = doc.get("last_name", "").upper()
    doc_name = f"{doc_first} {doc_last}".strip()

    if not doc_name:
        return {"watchlist_match_score": 0.0}

    for person in WATCHLIST:
        if not person.get("first_name") and not person.get("last_name"):
            continue # Skip invalid watchlist entries
        watch_first = person.get("first_name", "").upper()
        watch_last = person.get("last_name", "").upper()
        watch_name = f"{watch_first} {watch_last}".strip()

        # Calculate name similarity using SequenceMatcher
        name_similarity = SequenceMatcher(None, doc_name, watch_name).ratio()
        
        current_score = name_similarity
        
        # If names are a strong match, check DOB for a bonus
        if name_similarity > 0.8 and person.get("dob") and person["dob"] == doc.get("dob"):
            current_score = (current_score + 1.0) / 2 # Boost score for DOB match

        if current_score > max_score:
            max_score = current_score
            
    return {"watchlist_match_score": round(max_score, 2)}

def validate_document(doc: dict):
    """
    Apply risk rules to a single, cleaned document and return validation details.
    """
    result = {
        "status": "PASS",
        "risk_score": 0,
        "flags": []
    }

    doc_type = doc.get("doc_type")

    if not doc_type or doc_type.strip().upper() == "UNKNOWN":
        result["status"] = "REJECTED"
        result["risk_score"] = 100
        result["flags"].append("Missing document type")
        return result

    
    today = datetime.today().date()

    # --- Rule R001: Check for expired document (Hard Fail) ---
    # This logic remains from your original code.
    expiry_date_str = doc.get("expiry_date") or doc.get("date_of_expiry")
    if expiry_date_str:
        try:
            expiry_date = datetime.strptime(expiry_date_str, "%Y-%m-%d").date()
            if today > expiry_date:
                result["status"] = "REJECTED"
                result["risk_score"] = 100 # Set high score for clear rejection signal
                result["flags"].append("Expired document")
                return result # Hard fail, stop further checks
        except (ValueError, TypeError):
            # Invalid date format is a data quality issue, not a hard fail here.
            # Could add a flag if needed, e.g., result["flags"].append("Invalid expiry date format")
            pass

    # --- Rule R002: Check for high-risk country ---
    country_code = (doc.get("country_code") or "").upper().strip()
    place_of_birth = (doc.get("place_of_birth") or "").upper()
    address = (doc.get("address") or "").upper()

    is_high_risk_country = False

    # Exact match for codes
    if country_code in HIGH_RISK_JURISDICTIONS:
        is_high_risk_country = True
    # Substring search for names/keywords
    elif any(risk_item in place_of_birth for risk_item in HIGH_RISK_JURISDICTIONS) \
        or any(risk_item in address for risk_item in HIGH_RISK_JURISDICTIONS):
        is_high_risk_country = True

    if is_high_risk_country:
        result["risk_score"] += 20
        result["status"] = "REJECTED"
        result["flags"].append("High-risk country")


    # --- Rule R005: Check watchlist score ---
    # This rule relies on the score calculated by the `check_watchlist` function.
    if doc.get("watchlist_match_score", 0.0) > 0.5:
        result["risk_score"] += 30
        result["flags"].append("Watchlist hit")
    
    # --- Rule R006: Poor image quality (blur/contrast) ---
    image_quality = doc.get("image_quality", {})
    blur_score = image_quality.get("blur_score")
    contrast_score = image_quality.get("contrast_score")

    if (blur_score is not None and blur_score > 0.60) or (contrast_score is not None and contrast_score < 0.30):
        result["risk_score"] += 15
        result["flags"].append("Poor image quality")
    
    # --- Rule R007: PAN card validation (India-specific) ---
    # Format: 5 letters, 4 digits, 1 letter (e.g., ABCDE1234F)
    pan_number = doc.get("doc_number", "")
    last_name = doc.get("last_name", "").strip().upper() if doc.get("last_name") else None
    if pan_number and re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$", pan_number):
        # Check surname initial (5th letter in PAN should match last name's initial)
        if last_name and len(last_name) > 0:
            pan_surname_letter = pan_number[4]  # 5th letter (0-indexed)
            if pan_surname_letter != last_name[0]:
                result["status"] = "REJECTED"
                result["risk_score"] = 100
                result["flags"].append("PAN surname mismatch (possible tampering)")
                return result
    elif pan_number:  
        # PAN exists but invalid format
        result["status"] = "REJECTED"
        result["risk_score"] = 100
        result["flags"].append("Invalid PAN format")
        return result

    # --- Rule R008: DOB should not be in the future ---
    dob_str = doc.get("dob")
    if dob_str:
        try:
            dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
            if dob > today:
                result["status"] = "REJECTED"
                result["risk_score"] = 100
                result["flags"].append("DOB is in the future (tampering suspected)")
                return result
        except (ValueError, TypeError):
            result["flags"].append("Invalid DOB format")

    # --- Rule R009: Issue date cannot be after expiry date ---
    issue_date_str = doc.get("issue_date")
    expiry_date_str = doc.get("expiry_date")
    if issue_date_str and expiry_date_str:
        try:
            issue_date = datetime.strptime(issue_date_str, "%Y-%m-%d").date()
            expiry_date = datetime.strptime(expiry_date_str, "%Y-%m-%d").date()
            if issue_date > expiry_date:
                result["status"] = "REJECTED"
                result["risk_score"] = 100
                result["flags"].append("Issue date after expiry date (tampering suspected)")
                return result
        except (ValueError, TypeError):
            result["flags"].append("Invalid issue/expiry date format")

    # --- Rule R010: Expiry date should not be unrealistically far in future ---
    if expiry_date_str:
        try:
            expiry_date = datetime.strptime(expiry_date_str, "%Y-%m-%d").date()
            if (expiry_date - today).days > 365 * 15:  # More than 15 years validity
                result["status"] = "ESCALATE"
                result["flags"].append("Unusually long document validity period")
        except (ValueError, TypeError):
            pass
    # --- Rule R011: Name should not contain numbers or special chars ---
    for field in ["first_name", "last_name", "father_name", "mother_name"]:
        if doc.get(field):
            if re.search(r"[^A-Z\s]", doc[field].upper()):  # Allow only alphabets + spaces
                result["status"] = "ESCALATE"
                result["flags"].append(f"Suspicious characters in {field} (tampering suspected)")
    # --- Rule R014: Document number should not be too short ---
    if doc.get("doc_number") and len(doc["doc_number"]) < 6:
        result["status"] = "ESCALATE"
        result["flags"].append("Suspiciously short document number")

    # --- Rule R016: Address check (should not be empty or just numbers) ---
    if doc.get("address"):
        if re.fullmatch(r"\d+", doc["address"].strip()):
            result["status"] = "ESCALATE"
            result["flags"].append("Address contains only digits (tampering suspected)")
    else:
        result["flags"].append("Missing address field")
        result["status"] = "ESCALATE"

    if "escalate" in doc and doc["escalate"] is True:
        result["status"] = "ESCALATE"
        result["flags"].append("Escalated for manual review")

    
    return result

# def calculate_name_consistency(results: list):
#     """
#     Calculates a name consistency score across multiple documents.
#     Returns a dictionary with a flag and score adjustment if names mismatch.
#     """
#     # Rule R004: Check name match score across documents
#     if not doc:
#         return None
#     docs = [r["document"] for r in results if "document" in r]
#     if len(docs) < 2:
#         return None # Not applicable for a single document

#     names = []
#     for doc in docs:
#         first_name = doc.get("first_name", "").strip().upper()
#         last_name = doc.get("last_name", "").strip().upper()
#         if first_name and last_name:
#             names.append(f"{first_name} {last_name}")

#     if len(names) < 2:
#         return None # Not enough valid names to compare
        
#     # Compare the first name against all others
#     base_name = names[0]
#     total_similarity = 0
#     for i in range(1, len(names)):
#         total_similarity += SequenceMatcher(None, base_name, names[i]).ratio()
    
#     avg_similarity = total_similarity / (len(names) - 1)
    
#     if avg_similarity < 0.60:
#         return {
#             "score_adjustment": 25,
#             "flag": f"Low name consistency across documents (Score: {avg_similarity:.2f})"
#         }
#     return None



def calculate_name_consistency(results: list):
    """
    Calculates a name consistency score across multiple documents.
    Returns a dictionary with a flag and score adjustment if names mismatch.
    """
    if not results:
        return None

    docs = [r.get("document") for r in results if "document" in r]
    if len(docs) < 2:
        return None  # Not applicable for a single document

    names = []
    for doc in docs:
        if doc.get("first_name") is not None and doc.get("last_name") is not None:
            first_name = doc.get("first_name", "").strip().upper()
            last_name = doc.get("last_name", "").strip().upper()
            if first_name and last_name:
                names.append(f"{first_name} {last_name}")

            if len(names) < 2:
                return None  # Not enough valid names to compare

            base_name = names[-1]
            total_similarity = 0
            for i in range(1, len(names)):
                total_similarity += SequenceMatcher(None, base_name, names[i]).ratio()

            avg_similarity = total_similarity / (len(names) - 1)

    if avg_similarity != None:
        if avg_similarity < 0.60:
            return {
                "score_adjustment": 25,
                "flag": f"Low name consistency across documents (Score: {avg_similarity:.2f})"
            }
    return None


def main():
    """Main function to run the processing and validation pipeline."""
    try:
        with open(INPUT_FILE, "r", encoding="utf8") as f:
            entries = [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        print(f"❌ Error: Input file not found at '{INPUT_FILE}'")
        return
    except json.JSONDecodeError:
        print(f"❌ Error: Could not parse JSON from '{INPUT_FILE}'. Please ensure it's a valid line-delimited JSON file.")
        return

    results = []
    cumulative = {
        "status": "PASS",
        "risk_score": 0,
        "flags": []
    }

    for i, entry in enumerate(entries, start=1):
        print(f"🔹 Processing document {i}/{len(entries)}...")
        cleaned = refine_with_gemini(entry)
        for key in ["image_quality", "ocr_conf_mean", "page"]:
            if key in entry and key not in cleaned:
                cleaned[key] = entry[key]
        if "error" in cleaned:
            print(f"   - ⚠️  Skipping validation due to processing error: {cleaned['error']}")
            results.append({"document": cleaned, "validation": {"status": "ERROR", "flags": [cleaned['error']]}})
            continue
            
        
        validation = validate_document(cleaned)

        final_entry = {
            "document": cleaned,
            "validation": validation
        }
        results.append(final_entry)
        print(results)
        # print(dbintegration.fin(final_entry))
        if(dbintegration.fin(final_entry) is not None):
            print("Document already exists in the database. Skipping insertion.")
        else:
            dbintegration.insert(final_entry)  # Insert into MongoDB)
        # print(final_entry)  # For debugging

        # ---- Update cumulative results ----
        if validation["status"] == "REJECTED":
            cumulative["status"] = "REJECTED"
        elif validation["status"] == "ESCALATE" and cumulative["status"] != "REJECTED":
            cumulative["status"] = "ESCALATE"

        cumulative["risk_score"] += validation["risk_score"]
        for flag in validation["flags"]:
            if flag not in cumulative["flags"]:
                cumulative["flags"].append(flag)

    # --- New Step: Post-processing for cross-document consistency ---
    name_check_result = calculate_name_consistency(results)
    if name_check_result:
        print(f"🔹 Applying cross-document name consistency rule...")
        cumulative["risk_score"] += name_check_result["score_adjustment"]
        if name_check_result["flag"] not in cumulative["flags"]:
            cumulative["flags"].append(name_check_result["flag"])

    # Append cumulative summary at the end
    results.append({"cumulative_validation": cumulative})

    # Save results
    with open(OUTPUT_FILE, "w", encoding="utf8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False, indent=2) + "\n")

    print(f"\n✅ Done! Saved refined and validated results to {OUTPUT_FILE}")
    print(f"   - Final Status: {cumulative['status']}")
    print(f"   - Total Risk Score: {cumulative['risk_score']}")
    print(f"   - Flags Raised: {cumulative['flags']}")
    return cumulative["flags"],cumulative["risk_score"],cumulative["status"],cleaned['first_name']

if __name__ == "__main__":
    main()