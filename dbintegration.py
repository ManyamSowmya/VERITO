from pymongo import MongoClient
import json
# Connect to your local MongoDB server
client = MongoClient("mongodb://localhost:27017/")

# Access (or create) your database
db = client['document_verification']

# Create collections for document types
aadhaar_col = db['aadhaar']
passport_col = db['passport']
pan_col = db['pan']
invoice_col = db['invoice']

def fin(doc_data):
    doc_data1 = doc_data.get('document')
    doc_type = doc_data1.get("doc_type") or doc_data1.get("document_type")
    if not doc_type:
        raise ValueError("Document type not specified.")

    if doc_type.lower() == 'aadhaar':
        result = aadhaar_col.find_one(doc_data)
    elif doc_type.lower() == 'passport':
        result = passport_col.find_one(doc_data)
    elif doc_type.lower() == 'pan' or doc_type.lower() == 'pan card':
        result = pan_col.find_one(doc_data)
    elif doc_type.lower() == 'tax invoice':
        result = invoice_col.find_one(doc_data)
    else:
        # For unknown types, insert in a generic collection
        result = db['documents'].find_one(doc_data)
    return result

    

def insert_document(doc_data):
    doc_data1 = doc_data.get('document')
    doc_type = doc_data1.get("doc_type") or doc_data1.get("document_type")
    if not doc_type:
        raise ValueError("Document type not specified.")

    if doc_type.lower() == 'aadhaar':
        result = aadhaar_col.insert_one(doc_data)
    elif doc_type.lower() == 'passport':
        result = passport_col.insert_one(doc_data)
    elif doc_type.lower() == 'pan' or doc_type.lower() == 'pan card':
        result = pan_col.insert_one(doc_data)
    elif doc_type.lower() == 'tax invoice':
        result = invoice_col.insert_one(doc_data)
    else:
        # For unknown types, insert in a generic collection
        result = db['documents'].insert_one(doc_data)

    print(f"Inserted document with id: {result.inserted_id}")
    return result.inserted_id


def insert(jstr):
    json_str = json.dumps(jstr)
    doc_data = json.loads(json_str)
    insert_document(doc_data)
    
