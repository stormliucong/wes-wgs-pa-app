from __future__ import annotations

import csv
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from io import StringIO

from flask import Flask, jsonify, render_template, request, send_file, session, redirect, url_for, make_response

# Local imports
from app.models import validate_submission, normalize_payload


app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("SECRET_KEY", "dev-key-change-in-production")

# Simple admin password - in production, use environment variable
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")


def validate_submission_against_test_patients(submission_data):
    """
    Validate a submission against test_patients_sample.jsonl
    Returns: dict with status ("matched", "new_patient", "not_matched") and details
    """
    test_file = Path(__file__).resolve().parent.parent / "test_patients_sample.jsonl"
    
    if not test_file.exists():
        return {
            "status": "error",
            "message": "Test patients file not found",
            "details": {}
        }
    
    # Key fields to match for patient identification
    key_fields = [
        "patient_first_name", "patient_last_name", "dob", "member_id"
    ]
    
    # Additional fields to validate for consistency
    validation_fields = [
        "sex", "patient_address", "provider_name", "provider_npi", 
        "test_type", "primary_diagnosis"
    ]
    
    try:
        with open(test_file, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                    
                try:
                    test_patient = json.loads(line)
                    
                    # Check if this is the same patient (exact match on key fields)
                    key_match = all(
                        submission_data.get(field, "").strip().lower() == 
                        str(test_patient.get(field, "")).strip().lower()
                        for field in key_fields
                        if submission_data.get(field) and test_patient.get(field)
                    )
                    
                    if key_match:
                        # Found matching patient, now check for data consistency
                        mismatches = []
                        matches = []
                        
                        for field in validation_fields:
                            sub_val = str(submission_data.get(field, "")).strip().lower()
                            test_val = str(test_patient.get(field, "")).strip().lower()
                            
                            if sub_val and test_val:  # Both values exist
                                if sub_val == test_val:
                                    matches.append(field)
                                else:
                                    mismatches.append({
                                        "field": field,
                                        "submission_value": submission_data.get(field, ""),
                                        "test_patient_value": test_patient.get(field, "")
                                    })
                        
                        # Determine overall status
                        if not mismatches:
                            status = "matched"
                        elif len(mismatches) <= 2:  # Allow minor discrepancies
                            status = "matched"
                        else:
                            status = "not_matched"
                        
                        return {
                            "status": status,
                            "test_patient_line": line_num,
                            "test_patient_name": f"{test_patient.get('patient_first_name', '')} {test_patient.get('patient_last_name', '')}".strip(),
                            "matches": matches,
                            "mismatches": mismatches,
                            "details": {
                                "total_fields_checked": len(validation_fields),
                                "matching_fields": len(matches),
                                "mismatched_fields": len(mismatches)
                            }
                        }
                        
                except json.JSONDecodeError:
                    continue
        
        # No matching patient found
        return {
            "status": "new_patient",
            "message": "Patient not found in test database",
            "details": {
                "patient_name": f"{submission_data.get('patient_first_name', '')} {submission_data.get('patient_last_name', '')}".strip(),
                "member_id": submission_data.get('member_id', ''),
                "dob": submission_data.get('dob', '')
            }
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error reading test patients file: {str(e)}",
            "details": {}
        }


@app.get("/")
def index():
    """Render the main multi-step form page."""
    return render_template("index.html")


@app.post("/submit")
def submit():
    """Accept form submission and store as a JSON file after validation."""
    # Prefer JSON payload; fall back to form-encoded
    payload = request.get_json(silent=True) or request.form.to_dict(flat=True)

    # Normalize types (lists, booleans, etc.)
    payload = normalize_payload(payload)

    valid, errors = validate_submission(payload)
    if not valid:
        return jsonify({"ok": False, "errors": errors}), 400

    # Ensure data directory exists
    data_dir = Path(__file__).resolve().parent.parent / "data" / "submissions"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Persist to file with timestamp + uuid
    filename = f"{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex}.json"
    filepath = data_dir / filename

    record = {
        "submitted_at": datetime.utcnow().isoformat() + "Z",
        "payload": payload,
    }

    with filepath.open("w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    return jsonify({"ok": True, "file": filename})


@app.get("/health")
def health():
    return {"status": "ok"}


def get_submissions_data():
    """Load all submission files and return as list with metadata."""
    data_dir = Path(__file__).resolve().parent.parent / "data" / "submissions"
    submissions = []
    
    if not data_dir.exists():
        return submissions
    
    for file_path in data_dir.glob("*.json"):
        try:
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                
            # Extract metadata
            submission = {
                "filename": file_path.name,
                "submitted_at": data.get("submitted_at", ""),
                "payload": data.get("payload", {}),
                "file_size": file_path.stat().st_size,
                "file_path": str(file_path)
            }
            
            # Add searchable fields from payload
            payload = submission["payload"]
            submission["patient_name"] = f"{payload.get('patient_first_name', '')} {payload.get('patient_last_name', '')}".strip()
            submission["provider_name"] = payload.get("provider_name", "")
            submission["test_type"] = payload.get("test_type", "")
            
            submissions.append(submission)
            
        except (json.JSONDecodeError, KeyError) as e:
            # Skip corrupted files
            continue
    
    # Sort by submission date (newest first)
    submissions.sort(key=lambda x: x["submitted_at"], reverse=True)
    return submissions


@app.get("/admin")
def admin_login():
    """Admin login page."""
    if session.get("admin_authenticated"):
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_login.html")


@app.post("/admin/login")
def admin_authenticate():
    """Handle admin login."""
    password = request.form.get("password", "")
    if password == ADMIN_PASSWORD:
        session["admin_authenticated"] = True
        return redirect(url_for("admin_dashboard"))
    else:
        return render_template("admin_login.html", error="Invalid password")


@app.get("/admin/dashboard")
def admin_dashboard():
    """Admin dashboard to view submissions."""
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin_login"))
    
    # Get filter parameters
    search = request.args.get("search", "").strip()
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    test_type = request.args.get("test_type", "")
    
    submissions = get_submissions_data()
    
    # Apply filters
    if search:
        submissions = [s for s in submissions if 
                      search.lower() in s["patient_name"].lower() or 
                      search.lower() in s["provider_name"].lower() or
                      search.lower() in s["filename"].lower()]
    
    if date_from:
        submissions = [s for s in submissions if s["submitted_at"] >= date_from]
    
    if date_to:
        # Add time to make it end of day
        date_to_end = date_to + "T23:59:59Z" if "T" not in date_to else date_to
        submissions = [s for s in submissions if s["submitted_at"] <= date_to_end]
    
    if test_type:
        submissions = [s for s in submissions if s["test_type"] == test_type]
    
    # Get unique test types for filter dropdown
    all_submissions = get_submissions_data()
    test_types = sorted(set(s["test_type"] for s in all_submissions if s["test_type"]))
    
    return render_template("admin.html", 
                         submissions=submissions, 
                         test_types=test_types,
                         current_filters={
                             "search": search,
                             "date_from": date_from,
                             "date_to": date_to,
                             "test_type": test_type
                         })


@app.get("/admin/download/<filename>")
def admin_download_single(filename):
    """Download a single submission JSON file."""
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin_login"))
    
    data_dir = Path(__file__).resolve().parent.parent / "data" / "submissions"
    file_path = data_dir / filename
    
    if not file_path.exists() or not file_path.suffix == ".json":
        return "File not found", 404
    
    return send_file(file_path, as_attachment=True, download_name=filename)


@app.get("/admin/export")
def admin_export_csv():
    """Export filtered submissions as CSV."""
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin_login"))
    
    # Get the same filters as dashboard
    search = request.args.get("search", "").strip()
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    test_type = request.args.get("test_type", "")
    
    submissions = get_submissions_data()
    
    # Apply same filters as dashboard
    if search:
        submissions = [s for s in submissions if 
                      search.lower() in s["patient_name"].lower() or 
                      search.lower() in s["provider_name"].lower() or
                      search.lower() in s["filename"].lower()]
    
    if date_from:
        submissions = [s for s in submissions if s["submitted_at"] >= date_from]
    
    if date_to:
        date_to_end = date_to + "T23:59:59Z" if "T" not in date_to else date_to
        submissions = [s for s in submissions if s["submitted_at"] <= date_to_end]
    
    if test_type:
        submissions = [s for s in submissions if s["test_type"] == test_type]
    
    # Create CSV
    output = StringIO()
    writer = csv.writer(output)
    
    # Header row
    headers = [
        "Filename", "Submitted At", "Patient Name", "Provider Name", 
        "Test Type", "Patient DOB", "Provider NPI", "Diagnosis Code", 
        "Clinical History", "Prior Testing"
    ]
    writer.writerow(headers)
    
    # Data rows
    for submission in submissions:
        payload = submission["payload"]
        row = [
            submission["filename"],
            submission["submitted_at"],
            submission["patient_name"],
            submission["provider_name"],
            submission["test_type"],
            payload.get("patient_dob", ""),
            payload.get("provider_npi", ""),
            payload.get("diagnosis_code", ""),
            payload.get("clinical_history", ""),
            payload.get("prior_testing", "")
        ]
        writer.writerow(row)
    
    # Create response
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = f"attachment; filename=submissions_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return response


@app.post("/admin/delete/<filename>")
def admin_delete_submission(filename):
    """Delete a single submission file."""
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin_login"))
    
    data_dir = Path(__file__).resolve().parent.parent / "data" / "submissions"
    file_path = data_dir / filename
    
    # Security check: ensure filename is safe and file exists
    if not file_path.exists() or not file_path.suffix == ".json":
        return jsonify({"success": False, "error": "File not found"}), 404
    
    # Additional security: ensure file is within the submissions directory
    try:
        file_path.resolve().relative_to(data_dir.resolve())
    except ValueError:
        return jsonify({"success": False, "error": "Invalid file path"}), 400
    
    try:
        # Delete the file
        file_path.unlink()
        return jsonify({"success": True, "message": f"Successfully deleted {filename}"})
    except OSError as e:
        return jsonify({"success": False, "error": f"Failed to delete file: {str(e)}"}), 500


@app.get("/admin/logout")
def admin_logout():
    """Logout admin user."""
    session.pop("admin_authenticated", None)
    return redirect(url_for("admin_login"))


@app.get("/ehr")
def ehr_search():
    """Render the EHR patient search page."""
    return render_template("ehr.html")


@app.get("/api/search-patients")
def api_search_patients():
    """Search patients in JSONL files based on query parameters."""
    query = request.args.get("q", "").strip().lower()
    if not query:
        return jsonify({"patients": []})

    # Search in both test patients and actual submissions
    results = []
    
    # Search test patients JSONL file
    test_file = Path(__file__).resolve().parent.parent / "test_patients_sample.jsonl"
    if test_file.exists():
        try:
            with open(test_file, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        patient = json.loads(line)
                        # Search in key patient fields
                        searchable_text = " ".join([
                            patient.get("patient_first_name", ""),
                            patient.get("patient_last_name", ""),
                            patient.get("member_id", ""),
                            patient.get("dob", ""),
                            patient.get("provider_name", "")
                        ]).lower()
                        
                        if query in searchable_text:
                            patient["_source"] = "test_patients"
                            patient["_line"] = line_num
                            results.append(patient)
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass
    
    # Search actual submissions
    submissions_dir = Path(__file__).resolve().parent.parent / "data" / "submissions"
    if submissions_dir.exists():
        for json_file in submissions_dir.glob("*.json"):
            try:
                with open(json_file, 'r') as f:
                    submission = json.load(f)
                    patient = submission.get("data", {})
                    
                    # Search in key patient fields
                    searchable_text = " ".join([
                        patient.get("patient_first_name", ""),
                        patient.get("patient_last_name", ""),
                        patient.get("member_id", ""),
                        patient.get("dob", ""),
                        patient.get("provider_name", "")
                    ]).lower()
                    
                    if query in searchable_text:
                        patient["_source"] = "submissions"
                        patient["_file"] = json_file.name
                        patient["_submitted_at"] = submission.get("submitted_at")
                        results.append(patient)
            except (json.JSONDecodeError, FileNotFoundError):
                continue
    
    # Sort results by relevance (exact matches first, then partial)
    def sort_key(patient):
        name = f"{patient.get('patient_first_name', '')} {patient.get('patient_last_name', '')}".lower()
        member_id = patient.get('member_id', '').lower()
        
        # Exact name match gets highest priority
        if query == name.strip():
            return 0
        # Exact member ID match gets second priority
        if query == member_id:
            return 1
        # Partial matches get lower priority
        return 2
    
    results.sort(key=sort_key)
    
    # Limit results to prevent overwhelming UI
    return jsonify({"patients": results[:20]})


@app.post("/api/validate-submission")
def api_validate_submission():
    """Validate a submission against test patients database."""
    if not session.get("admin_authenticated"):
        return jsonify({"error": "Admin authentication required"}), 401
    
    data = request.get_json()
    if not data or "filename" not in data:
        return jsonify({"error": "Filename required"}), 400
    
    filename = data["filename"]
    submissions_dir = Path(__file__).resolve().parent.parent / "data" / "submissions"
    filepath = submissions_dir / filename
    
    if not filepath.exists():
        return jsonify({"error": "Submission file not found"}), 404
    
    try:
        with open(filepath, 'r') as f:
            submission = json.load(f)
        
        submission_data = submission.get("data", {})
        validation_result = validate_submission_against_test_patients(submission_data)
        
        return jsonify({
            "success": True,
            "validation": validation_result,
            "filename": filename
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to validate submission: {str(e)}"}), 500


# For local debugging: `python -m flask --app app.main run --debug`
if __name__ == "__main__":
    app.run(debug=True)
