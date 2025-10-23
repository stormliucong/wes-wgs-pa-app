from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request

# Local imports
from app.models import validate_submission, normalize_payload


app = Flask(__name__, static_folder="static", template_folder="templates")


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


# For local debugging: `python -m flask --app app.main run --debug`
if __name__ == "__main__":
    app.run(debug=True)
