from __future__ import annotations

import csv
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from io import StringIO
import logging

logger = logging.getLogger(__name__)

def _safe_str(value):
    """Safely convert a value to a string, handling None."""
    return str(value) if value is not None else ""

from flask import Flask, jsonify, render_template, request, send_file, session, redirect, url_for, make_response

# Local imports
from app.models import validate_submission, normalize_payload


app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("SECRET_KEY", "dev-key-change-in-production")

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)

# Simple admin password - in production, use environment variable
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")


# Writable data root (App Platform: /tmp; local: project /data if APP_DATA_DIR unset)
def data_root() -> Path:
    p = os.environ.get("APP_DATA_DIR")
    if p:
        return Path(p)
    # Fallback to /tmp in production
    if os.environ.get("FLASK_ENV") == "production" or os.environ.get("GUNICORN_CMD_ARGS"):
        return Path("/tmp/wes-wgs-pa-app-data")
    # Local dev default
    return Path(__file__).resolve().parents[1] / "data"

DATA_DIR = data_root()
SUBMISSIONS_DIR = DATA_DIR / "submissions"
DRAFTS_DIR = DATA_DIR / "drafts"
USERS_FILE = DATA_DIR / "users.json"

# Ensure writable store at import time (per process)
try:
    SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    if not USERS_FILE.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        USERS_FILE.write_text("{}", encoding="utf-8")
except Exception:
    logger.exception("Failed to initialize data store at startup: %s", DATA_DIR)

def ensure_data_store():
    try:
        SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        if not USERS_FILE.exists():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            USERS_FILE.write_text("{}", encoding="utf-8")
    except Exception as e:
        logger.exception("Failed to initialize data store at %s", DATA_DIR)
        raise

def load_users() -> dict:
    ensure_data_store()
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to read users file")
        return {}

def save_users(users: dict):
    ensure_data_store()
    USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")

@app.before_request
def _init_store():
    ensure_data_store()

@app.get("/")
def index():
    """Render the main multi-step form page."""
    # Require user login before showing form
    if not session.get("user_authenticated"):
        return redirect(url_for("login"))
    return render_template("index.html")

@app.get("/login")
def login():
    """Render user login page."""
    if session.get("user_authenticated"):
        return redirect(url_for("index"))
    return render_template("user_login.html")

@app.post("/login")
def do_login():
    """Simple username/password login with file-backed storage."""
    # Accept form-encoded or JSON
    data = {}
    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form.to_dict() if request.form else {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    logger.info("Login attempt for username=%s (json=%s)", username or "<empty>", request.is_json)
    if not username:
        return render_template("user_login.html", error="Username is required"), 400

    users_dir = data_root()
    users_dir.mkdir(parents=True, exist_ok=True)
    users_file = users_dir / "users.json"

    users = {}
    if users_file.exists():
        try:
            with users_file.open("r", encoding="utf-8") as f:
                users = json.load(f) or {}
        except json.JSONDecodeError:
            users = {}

    # If user exists, check password; else create user entry
    if username in users:
        saved_pw = users.get(username, {}).get("password", "")
        if saved_pw and password != saved_pw:
            logger.warning("Login failed for username=%s: bad password", username)
            return render_template("user_login.html", error="Invalid credentials"), 401
    else:
        users[username] = {"password": password}
        with users_file.open("w", encoding="utf-8") as f:
            json.dump(users, f, indent=2, ensure_ascii=False)
        logger.info("Created new user account for username=%s", username)

    session["user_authenticated"] = True
    session["username"] = username
    logger.info("Login success for username=%s", username)
    return redirect(url_for("index"))

@app.get("/logout")
def logout():
    session.pop("user_authenticated", None)
    session.pop("username", None)
    return redirect(url_for("login"))


@app.post("/submit")
def submit():
    """Accept form submission and store as a JSON file after validation."""
    # Prefer JSON payload; fall back to form-encoded
    payload = request.get_json(silent=True) or request.form.to_dict()

    # Normalize types (lists, booleans, etc.)
    payload = normalize_payload(payload)

    valid, errors = validate_submission(payload)
    if not valid:
        return jsonify({"ok": False, "errors": errors}), 400

    # Ensure data directory exists
    data_dir = data_root() / "submissions"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Persist to file with timestamp + uuid
    filename = f"{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex}.json"
    filepath = data_dir / filename

    # Capture timing metadata
    submitted_at = datetime.utcnow().isoformat() + "Z"
    record = {
        "submitted_at": submitted_at,
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
    data_dir = data_root() / "submissions"
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
                "patient_id": data.get("patient_id", ""),
                "submitted_at": data.get("submitted_at", ""),
                "completion_seconds": data.get("completion_seconds"),
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
    
    # Sort by submission date (newest first) with safe fallback
    submissions.sort(key=lambda x: x.get("submitted_at") or "", reverse=True)
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
    
    data_dir = data_root() / "submissions"
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
        "Filename", "Started At", "Submitted At", "Completion Seconds", "Patient Name", "Provider Name", 
        "Test Type", "Patient DOB", "Provider NPI", "Diagnosis Code", 
        "Clinical History", "Prior Testing"
    ]
    writer.writerow(headers)
    
    # Data rows
    for submission in submissions:
        payload = submission["payload"]
        row = [
            submission["filename"],
            submission.get("started_at", ""),
            submission["submitted_at"],
            submission.get("completion_seconds", ""),
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
    
    # Use the same submissions directory as other admin routes
    data_dir = data_root() / "submissions"
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
    return redirect(url_for("login"))


@app.get("/ehr")
def ehr_search():
    """Render the EHR patient search page."""
    return render_template("ehr.html")

# ---------------- Draft management (multi-draft, autosave) ----------------

def _drafts_dir() -> Path:
    return data_root() / "drafts"

def _ensure_drafts_dir():
    d = _drafts_dir()
    d.mkdir(parents=True, exist_ok=True)

def get_drafts_data():
    """Load all draft files and return metadata for admin panel."""
    ddir = _drafts_dir()
    drafts = []
    if not ddir.exists():
        return drafts
    for file_path in ddir.glob("*.json"):
        try:
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            drafts.append({
                "filename": file_path.name,
                "form_id": data.get("form_id"),
                "username": data.get("username"),
                "started_at": data.get("started_at"),
                "last_saved_at": data.get("last_saved_at"),
                "payload": data.get("payload", {}),
            })
        except Exception:
            continue
    # Sort drafts by last_saved_at safely, coalescing None to empty string
    drafts.sort(key=lambda x: x.get("last_saved_at") or "", reverse=True)
    return drafts

@app.post("/draft/save")
def save_draft():
    """Save current form as a server-side draft for the authenticated user.
    Supports multiple drafts via form_id.
    """
    if not session.get("user_authenticated"):
        return jsonify({"ok": False, "error": "Not authenticated"}), 401
    data = request.get_json(silent=True) or request.form.to_dict()
    payload = normalize_payload(data or {})

    form_id = (data or {}).get("form_id") or str(uuid.uuid4())
    username = session.get("username", "anonymous")
    started_at = (data or {}).get("started_at") or datetime.utcnow().isoformat() + "Z"
    current_step = (data or {}).get("current_step")

    _ensure_drafts_dir()
    draft_path = _drafts_dir() / f"{form_id}.json"

    record = {
        "status": "in_progress",
        "form_id": form_id,
        "username": username,
        "started_at": started_at,
        "last_saved_at": datetime.utcnow().isoformat() + "Z",
        "current_step": current_step,
        "payload": payload,
    }
    with draft_path.open("w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True, "form_id": form_id, "started_at": started_at})

@app.get("/draft/load")
def load_draft():
    if not session.get("user_authenticated"):
        return jsonify({"ok": False, "error": "Not authenticated"}), 401
    form_id = request.args.get("form_id")
    if not form_id:
        return jsonify({"ok": True, "payload": {}})
    draft_path = _drafts_dir() / f"{form_id}.json"
    if not draft_path.exists():
        return jsonify({"ok": True, "payload": {}})
    try:
        with draft_path.open("r", encoding="utf-8") as f:
            record = json.load(f)
        return jsonify({
            "ok": True,
            "payload": record.get("payload", {}),
            "form_id": record.get("form_id"),
            "started_at": record.get("started_at"),
            "current_step": record.get("current_step"),
        })
    except json.JSONDecodeError:
        return jsonify({"ok": True, "payload": {}})

@app.post("/draft/start_new")
def start_new_form():
    if not session.get("user_authenticated"):
        return jsonify({"ok": False, "error": "Not authenticated"}), 401
    # Optionally save current draft if provided
    current = request.get_json(silent=True) or {}
    if current:
        try:
            save_draft()  # save existing state
        except Exception:
            pass
    # Create new blank form
    form_id = str(uuid.uuid4())
    started_at = datetime.utcnow().isoformat() + "Z"
    # Initialize an empty draft file for tracking
    _ensure_drafts_dir()
    draft_path = _drafts_dir() / f"{form_id}.json"
    with draft_path.open("w", encoding="utf-8") as f:
        json.dump({
            "status": "in_progress",
            "form_id": form_id,
            "username": session.get("username", "anonymous"),
            "started_at": started_at,
            "last_saved_at": started_at,
            "current_step": 0,
            "payload": {},
        }, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True, "form_id": form_id, "started_at": started_at})

@app.post("/draft/delete")
def delete_draft():
    if not session.get("user_authenticated"):
        return jsonify({"ok": False, "error": "Not authenticated"}), 401
    data = request.get_json(silent=True) or request.form.to_dict()
    form_id = (data or {}).get("form_id")
    if not form_id:
        return jsonify({"ok": False, "error": "Missing form_id"}), 400
    draft_path = _drafts_dir() / f"{form_id}.json"
    try:
        if draft_path.exists():
            draft_path.unlink()
        return jsonify({"ok": True})
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/api/search-patients")
def api_search_patients():
    """Search patients in JSONL files based on query parameters."""
    query = request.args.get("q", "").strip().lower()
    if not query:
        return jsonify({"patients": []})

    # Search in both test patients and actual submissions
    results = []
    
    # Search actual submissions
    submissions_dir = data_root() / "submissions"
    if submissions_dir.exists():
        for json_file in submissions_dir.glob("*.json"):
            try:
                with open(json_file, 'r') as f:
                    submission = json.load(f)
                    # Stored structure uses key 'payload'
                    patient = submission.get("payload", {}) or submission.get("data", {})
                    
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
    
    # Search unstructured profiles JSON (generated synthetic EHR-like data)
    unstructured_file = Path(__file__).resolve().parent.parent / "unstructured_profiles.json"
    if unstructured_file.exists():
        try:
            with open(unstructured_file, 'r', encoding='utf-8') as f:
                unstructured = json.load(f)
                if isinstance(unstructured, list):
                    for patient in unstructured:
                        if not isinstance(patient, dict):
                            continue
                        searchable_text = " ".join([
                            _safe_str(patient.get("patient_first_name", "")),
                            _safe_str(patient.get("patient_last_name", "")),
                            _safe_str(patient.get("member_id", "")),
                            _safe_str(patient.get("dob", "")),
                            _safe_str(patient.get("provider_name", ""))
                        ]).lower()
                        if query in searchable_text:
                            p = dict(patient)
                            p["_source"] = "unstructured"
                            results.append(p)
        except (json.JSONDecodeError, OSError):
            pass
    
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


# For local debugging: `python -m flask --app app.main run --debug`
if __name__ == "__main__":
    app.run(debug=True)
