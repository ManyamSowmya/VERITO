
import os
from main import detect_document_text, parse_text_from_document

# --- Configuration ---
# Ensure your Google credentials are set
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials.json'
# The name of the image file you want to test
TEST_IMAGE_PATH = "test_pan.jpg"

def run_test():
    """
    Runs a test on a single document image to check OCR and parsing.
    """
    print(f"--- Starting test for: {TEST_IMAGE_PATH} ---")
    
    # 1. Read the local image file into memory
    try:
        with open(TEST_IMAGE_PATH, "rb") as image_file:
            content = image_file.read()
        print("✅ Image file read successfully.")
    except FileNotFoundError:
        print(f"❌ ERROR: Test image not found at '{TEST_IMAGE_PATH}'.")
        print("Please make sure the image is in the same directory and the filename is correct.")
        return

    # 2. Call the OCR function to get raw text
    print("\n--- Step 1: Calling Google Vision API for OCR ---")
    try:
        full_text = detect_document_text(content)
        print("✅ OCR processing successful.")
        print("\n[Raw Text Extracted]")
        print("---------------------------------")
        print(full_text)
        print("---------------------------------")
    except Exception as e:
        print(f"❌ ERROR during OCR: {e}")
        return

    # 3. Call the parsing function to get structured data
    print("\n--- Step 2: Parsing raw text for specific fields ---")
    extracted_data = parse_text_from_document(full_text)
    print("✅ Parsing complete.")
    
    # 4. Print the final result
    print("\n--- Final Result: Structured Data ---")
    print(f"  Document Type: {extracted_data.document_type}")
    print(f"  Name:          {extracted_data.name}")
    print(f"  Date of Birth: {extracted_data.dob}")
    print(f"  PAN Number:    {extracted_data.pan_number}")
    print("\n--- Test Finished ---")


if __name__ == "__main__":
    run_test()