from flask import Flask, render_template, request, redirect, url_for, flash
import os
from werkzeug.utils import secure_filename
import example
import refine
from flask import jsonify
from bson import ObjectId, json_util
import json
from collections import Counter
from pymongo import MongoClient
client = MongoClient("mongodb://localhost:27017/")

# Access (or create) your database
db = client['document_verification']

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'files'  # set your folder name here
app.secret_key = 'your_secret_key'  # Needed for flashing messages

# Allowed file extensions
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

bs = None
cs = None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/home', methods=['GET', 'POST'])
def home():
    flag = None
    risk = None
    stat = None
    if request.method == 'POST':
        if 'files' not in request.files:
            flash('No file part')
            return redirect(request.url)
        files = request.files.getlist('files')
        success = False
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                success = True
                
                
                ##### main processing logic here #####
                input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                res = example.process_pdf(input_path, f"output.json")
                print(f"Processed {filename}, results saved to output.json")
                flag , risk , stat,name1 = refine.main()
                
                
                 
        if success:
            flash('File(s) successfully uploaded')
        else:
            flash('No allowed file(s) selected')
        # return redirect(request.url)
        return render_template(
        'home.html',
        flag = flag,
        name = name1,
        risk = risk,
        stat = stat,        
        active_tab='upload'
        )
    return render_template(
        'home.html',
        flag = flag,
        risk = risk,
        stat = stat,        
        active_tab='upload'
    )


# @app.route('/dashboard')
# def dashboard():
#     return render_template(
#         'dashboard.html',
#         total_score=0,
#         total_docs=0,
#         verified_count=0,
#         flagged_count=0,
#         documents=[], # Or your list of documents dicts
#         active_tab='dashboard'
#     )

#
# ... (keep all your existing code before this point) ...
#

def get_document_data():
    """
    A helper function to fetch all documents from MongoDB and calculate stats.
    This avoids code duplication between the dashboard and documents routes.
    """
    all_docs = []
    # Fetch documents from all relevant collections
    for col_name in ['passport', 'pan', 'aadhaar', 'invoice', 'documents']:
        col = db[col_name]
        for d in col.find():
            # Use .get() to prevent errors if keys are missing
            validation_info = d.get('validation')
            document_info = d.get('document')
            flags = validation_info.get("flags", [])

            all_docs.append({
                "_id": str(d.get('_id')),  # Important: Add the document's unique ID
                "name": document_info.get("doc_number", "N/A"),
                "type": document_info.get("doc_type", "Unknown").upper(),
                "status": validation_info.get("status", "Pending"),
                "risk_score": validation_info.get("risk_score", 0),
                "flag": flags[0] if flags else "No Flags",
            })

    total_docs = len(all_docs)
    verified_count = len([doc for doc in all_docs if doc["status"].strip().upper() == "PASS"])
    flagged_count = len([doc for doc in all_docs if doc["flag"] and doc["flag"].strip().upper() != "NO FLAGS"])

    return {
        "documents": all_docs,
        "total_docs": total_docs,
        "verified_count": verified_count,
        "flagged_count": flagged_count,
    }


@app.route('/dashboard')
def dashboard():
    """
    This route now only fetches the summary counts for the dashboard cards.
    """
    data = get_document_data()
    return render_template(
        'dashboard.html',
        total_docs=data['total_docs'],
        verified_count=data['verified_count'],
        flagged_count=data['flagged_count'],
        active_tab='dashboard'
    )


@app.route('/documents')
def documents():
    """
    This route fetches the complete list of documents to display in the table.
    """
    data = get_document_data()
    return render_template(
        'documents.html',
        documents=data['documents'],
        active_tab='documents'
    )
    
    
@app.route('/api/document/<doc_id>')
def get_single_document(doc_id):
    # Loop through all collections to find the document
    for col_name in ['passport', 'pan', 'aadhaar', 'invoice', 'documents']:
        col = db[col_name]
        try:
            doc = col.find_one({'_id': ObjectId(doc_id)})
        except Exception:
            continue  # Ignore invalid ObjectId or other issues
        if doc:
            doc['_id'] = str(doc['_id'])  # Ensure ObjectId is serializable
            return jsonify(doc)
    return jsonify({"error": "Document not found"}), 404

#
# ... (keep all your existing code after this point, like if __name__ == '__main__':) ...
#

# Add detail/view route if needed
# @app.route('/document/<int:doc_id>')...

@app.route('/api/chart-data')
def chart_data():
    """API endpoint to provide data for dashboard charts."""
    pipeline = [
        {
            "$project": {
                "status": "$validation.status",
                "type": "$document.doc_type"
            }
        }
    ]
    
    all_docs_data = []
    for col_name in ['passport', 'pan', 'aadhaar', 'invoice', 'documents']:
        all_docs_data.extend(list(db[col_name].aggregate(pipeline)))

    # Count occurrences of each status and type
    status_counts = Counter(d.get('status', 'Unknown').strip().upper() for d in all_docs_data)
    type_counts = Counter(d.get('type', 'Unknown').strip().upper() for d in all_docs_data)

    chart_data = {
        "status_distribution": {
            "labels": list(status_counts.keys()),
            "data": list(status_counts.values())
        },
        "type_distribution": {
            "labels": list(type_counts.keys()),
            "data": list(type_counts.values())
        }
    }
    
    return jsonify(chart_data)

if __name__ == '__main__':
    app.run(debug=True)
