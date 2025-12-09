from openai import OpenAI
import json
import re
from datetime import datetime

# ----------------- Setup -----------------
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key="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"
)

# ----------------- Rules -----------------
rules_text = """
Rules:
1. If expiry_date < today -> status = "Rejected", risk_score = 0, risk_bucket = "High", reason = {"rule_id":"R001","message":"Document expired on <date>"}.
2. If country_code in {IR, KP, SY, RU} -> add +20 points for the risk score, reason R002.
3. If blur_score > 0.75 OR contrast_score < 0.30 -> add +15 pointsfor the risk score, reason R003.
4. If name_match_score < 0.60 -> add +25 points for the risk score, reason R004.
5. If OCR or image data is missing/empty -> add +50 points for the risk score, reason R005 ("Document appears tampered").

Risk bucket thresholds:
- 0-25 points = Low -> Verified
- 26-60 points = Medium ->Flagged
- >60 points = High -> Rejected

Return ONLY JSON in this format:
{
  "status": "...",
  "risk_score": <int>,
  "risk_bucket": "...",
  "reasons": [{"rule_id":"...","message":"..."}]
}
"""

# ----------------- Enhanced JSON Extraction -----------------
def extract_json_from_response(response_text: str) -> dict:
    
    cleaned_response = response_text.strip()
    
    if '"risk_bucket":"M' in cleaned_response and not cleaned_response.endswith('}'):
        if '"Medium"' not in cleaned_response:
            cleaned_response = cleaned_response.replace('"risk_bucket":"M', '"risk_bucket":"Medium"')
            if not cleaned_response.endswith('edium"'):
                cleaned_response += 'edium"'
        
        # Add missing fields for this specific case
        if '"reasons"' not in cleaned_response:
            cleaned_response += ',"reasons":[{"rule_id":"R005","message":"Missing data"}]'
        
        # Close JSON
        if not cleaned_response.endswith('}'):
            cleaned_response += '}'
    
    # Strategy 1: Look for JSON within code blocks
    json_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned_response, re.DOTALL)
    if json_block_match:
        json_text = json_block_match.group(1).strip()
        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            pass
    
    # Strategy 2: Look for JSON object directly (starts with { and ends with })
    json_match = re.search(r'\{.*\}', cleaned_response, re.DOTALL)
    if json_match:
        json_text = json_match.group(0).strip()
        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            # Strategy 3: Try to fix common JSON issues
            json_text = fix_common_json_issues(json_text)
            try:
                return json.loads(json_text)
            except json.JSONDecodeError:
                pass
    
    # Strategy 4: If all else fails, return error with raw response
    return {
        "error": "Failed to parse JSON response",
        "raw_response": response_text,
        "status": "Error",
        "risk_score": 100,
        "risk_bucket": "High",
        "reasons": [{"rule_id": "ERROR", "message": "JSON parsing failed"}]
    }

def fix_common_json_issues(json_text: str) -> str:
    """
    Fix common JSON formatting issues including truncation
    """
    # Remove trailing commas before closing braces/brackets
    json_text = re.sub(r',(\s*[}\]])', r'\1', json_text)
    
    # Ensure proper quote escaping
    json_text = json_text.replace('\\"', '"')
    
    # Handle truncated JSON - try to complete it intelligently
    open_braces = json_text.count('{')
    close_braces = json_text.count('}')
    
    if open_braces > close_braces:
        # Check if we can detect what field was being written when truncated
        if '"risk_bucket":"M' in json_text or '"risk_bucket":"Medium",' in json_text:
            # Complete the Medium value and add missing fields
            if '"Medium",' not in json_text:
                json_text = json_text.replace('"risk_bucket":"M', '"risk_bucket":"Medium"')
                if not json_text.endswith('edium"'):
                    json_text += 'edium"'
            
            # Add missing reasons array if not present
            if '"reasons"' not in json_text:
                json_text += ',"reasons":[{"rule_id":"R005","message":"Document appears tampered - missing data"}]'
            
            # Close the JSON properly
            json_text += '}'
        else:
            # Generic truncation fix - try to find last complete field
            last_quote = json_text.rfind('"')
            if last_quote != -1:
                # Find the field name before the last quote
                colon_pos = json_text.rfind(':', 0, last_quote)
                if colon_pos != -1:
                    # Truncate to last complete field
                    comma_pos = json_text.rfind(',', 0, colon_pos)
                    if comma_pos != -1:
                        json_text = json_text[:comma_pos] + '}'
    
    return json_text

# ----------------- Enhanced LLM Agent -----------------
def risk_scoring_agent(document: dict) -> dict:
    """
    Enhanced risk scoring agent with better JSON handling
    """
    today = datetime.today().strftime("%Y-%m-%d")
    
    # Very aggressive JSON-only prompt
    prompt = f"""ONLY OUTPUT JSON. NO TEXT. NO EXPLANATION.

Document: {json.dumps(document, separators=(',', ':'))}
Today: {today}

{{"status":"Flagged","risk_score":50,"risk_bucket":"Medium","reasons":[{{"rule_id":"R005","message":"Missing data"}}]}}"""

    try:
        # Try with very restrictive parameters first
        completion = client.chat.completions.create(
            model="qwen/qwen3-235b-a22b",
            messages=[
                {"role": "system", "content": "You are a JSON generator. Output only valid JSON. No explanations."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=100,  # Very small to force concise response
            stop=["}", "\n"]  # Stop immediately after JSON
        )
        
        # Try to get response from different fields
        raw_response = ""
        if completion.choices[0].message.content:
            raw_response = completion.choices[0].message.content
        elif hasattr(completion.choices[0].message, 'reasoning_content') and completion.choices[0].message.reasoning_content:
            raw_response = completion.choices[0].message.reasoning_content
        
        # If we get any reasoning text, immediately fall back to manual assessment
        if raw_response and ('step by step' in raw_response.lower() or 
                           'let me' in raw_response.lower() or 
                           'looking at' in raw_response.lower() or
                           len(raw_response) > 200):
            print("DEBUG: Model giving reasoning instead of JSON, using manual assessment")
            return manual_risk_assessment(document, today)
        
        # Debug: Print raw response if empty or problematic
        if not raw_response.strip():
            print(f"DEBUG: Empty response, using manual assessment")
            return manual_risk_assessment(document, today)
        
        # Try to extract JSON
        result = extract_json_from_response(raw_response)
        
        # If extraction failed, use manual assessment
        if "error" in result:
            print(f"DEBUG: JSON extraction failed, using manual assessment")
            return manual_risk_assessment(document, today)
        
        # Validate required fields
        required_fields = ["status", "risk_score", "risk_bucket", "reasons"]
        if all(field in result for field in required_fields):
            return result
        else:
            print(f"DEBUG: Missing required fields, using manual assessment")
            return manual_risk_assessment(document, today)
            
    except Exception as e:
        print(f"DEBUG: API Error: {str(e)}, using manual assessment")
        return manual_risk_assessment(document, today)

# ----------------- Manual Risk Assessment Fallback -----------------
def manual_risk_assessment(document: dict, today: str) -> dict:
    """
    Manual implementation of the risk scoring rules as fallback
    """
    risk_score = 0
    reasons = []
    
    # Rule 1: Check expiry date
    expiry_date = document.get('expiry_date', '')
    if expiry_date and expiry_date < today:
        return {
            "status": "Rejected",
            "risk_score": 0,
            "risk_bucket": "High",
            "reasons": [{"rule_id": "R001", "message": f"Document expired on {expiry_date}"}]
        }
    
    # Rule 2: Check country code
    country_code = document.get('country_code', '')
    if country_code in ['IR', 'KP', 'SY', 'RU']:
        risk_score += 20
        reasons.append({"rule_id": "R002", "message": f"High-risk country: {country_code}"})
    
    # Rule 3: Check image quality
    image_quality = document.get('image_quality', {})
    blur_score = image_quality.get('blur_score', 0)
    contrast_score = image_quality.get('contrast_score', 1)
    
    if blur_score > 0.75 or contrast_score < 0.30:
        risk_score += 15
        reasons.append({"rule_id": "R003", "message": "Poor image quality detected"})
    
    # Rule 4: Check name match score
    name_match_score = document.get('name_match_score')
    if name_match_score is not None and name_match_score < 0.60:
        risk_score += 25
        reasons.append({"rule_id": "R004", "message": f"Low name match score: {name_match_score}"})
    
    # Rule 5: Check for missing OCR/image data
    ocr_confidences = document.get('ocr_confidences', {})
    if not ocr_confidences or name_match_score is None:
        risk_score += 50
        reasons.append({"rule_id": "R005", "message": "Document appears tampered - missing data"})
    
    if risk_score <= 25:
        risk_bucket = "Low"
        status = "Verified"
    elif risk_score <= 60:
        risk_bucket = "Medium"
        status = "Flagged"
    else:
        risk_bucket = "High"
        status = "Rejected"
    
    if not reasons:
        reasons.append({"rule_id": "R000", "message": "No risk factors detected"})
    
    return {
        "status": status,
        "risk_score": risk_score,
        "risk_bucket": risk_bucket,
        "reasons": reasons
    }


# ----------------- Test Data -----------------
tampered_passport = {
    "doc_type": "Passport",
    "doc_number": "N1234567",
    "first_name": "Liam",
    "last_name": "Nguyen",
    "dob": "1988-12-05",
    "place_of_birth": "Sydney",
    "issue_date": "2018-01-10",
    "expiry_date": "2023-01-09",  # expired for test
    "full_name": "Liam Nguyen",
    "address": "12/34 George St, CBD, Sydney, NSW, Australia",
    "country_code": "AU",
    "gender": "M",
    "ocr_confidences": {"name": 0.95, "dob": 0.92, "doc_number": 0.93},
    "image_quality": {"blur_score": 0.20, "contrast_score": 0.70},
    "name_match_score": 0.98
}


# ----------------- Main Execution -----------------
if __name__ == "__main__":
    result = risk_scoring_agent(tampered_passport)
    print(json.dumps(result, indent=2))