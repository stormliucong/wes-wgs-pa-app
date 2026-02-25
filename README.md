# WES/WGS Pre-Authorization Web App

A minimal Flask application to collect pre-authorization requests for Whole Exome/Genome Sequencing (WES/WGS). The UI is a multi-step form with client-side and server-side validation. Submissions are stored as individual JSON files on the server.

## Features
- Multi-step form (Next/Back) with dropdowns and required fields
- Client-side validation and inline error messages
- Server-side validation and normalized payload
- Each submission saved under `data/submissions/<timestamp>_<uuid>.json`
- Dockerized for easy deployment (port 8080)

## Project Structure
```
wes-wgs-pa-app/
├─ app/                                      # Web Application
│  ├─ __init__.py
│  ├─ main.py                                # Flask routes
│  ├─ models.py                              # Validation logic & data models
│  ├─ static/
│  │  ├─ styles.css
│  │  └─ app.js
│  └─ templates/
│     └─ index.html
├─ scripts/                                  # Utility scripts
│  ├─ groundtruth.py                         # Data Generation: synthetic patient profiles
│  ├─ generate_unstructured_profiles.py      # Data Generation: clinical notes via OpenAI
│  ├─ validate_clinical_note.py              # Data Generation: validate generated notes
│  ├─ make_submissions.py                    # Browser Automation: form submission via Browser-Use Cloud
│  ├─ agent_skill.py                         # Browser Automation: sandbox-based form submission
│  └─ analysis.py                            # Evaluation: compare submissions vs ground truth
├─ data/                                     # Local data (not committed)
│  ├─ groundtruth/                           # Ground-truth profiles & all-sample lists
│  ├─ unstructured/                          # Generated & validated unstructured profiles
│  ├─ automation/                            # Batch input/output files for OpenAI
│  ├─ submissions/                           # Submissions downloaded from the server
│  └─ results/                               # Analysis output (Excel reports)
├─ .gitignore
├─ requirements.txt
├─ Dockerfile
└─ README.md
```

## Run locally (Python 3.11)

```bash
# create and activate venv
python3 -m venv .venv
source .venv/bin/activate

# install dependencies
pip install -r requirements.txt

# run dev server (auto-reload)
python -m flask --app app.main run --debug
```

Open http://127.0.0.1:5000 in your browser.

## Docker

```bash
# build
docker build -t wes-wgs-pa-app:latest .
# run
docker run -p 8080:8080 wes-wgs-pa-app:latest
```

Then visit http://localhost:8080.

## Scripts

All scripts live in `scripts/` and accept `--help` for full option details.
Input and output paths default to subdirectories of `data/` and can be overridden with CLI flags.

### 1. Generate ground-truth profiles

```bash
python scripts/groundtruth.py \
  --groundtruth-output data/groundtruth/groundtruth.json \
  --samples-output     data/groundtruth/all_samples.json
```

### 2. Generate unstructured clinical-note profiles

Requires `OPENAI_API_KEY` in `.env` or environment.

```bash
python scripts/generate_unstructured_profiles.py \
  --input       data/groundtruth/all_samples.json \
  --output      data/unstructured/unstructured_profiles.json \
  --batch-input data/automation/batch_input.jsonl
```

### 3. Validate clinical notes

```bash
python scripts/validate_clinical_note.py \
  --input        data/unstructured/unstructured_profiles.json \
  --output       data/unstructured/validated_profiles.json \
  --batch-input  data/automation/validation_batch_input.jsonl \
  --batch-output data/automation/validation_raw_output.jsonl
```

### 4. Submit forms via Browser-Use Cloud automation

Requires `BROWSER_USE_API_KEY` in `.env` or environment.

```bash
python scripts/make_submissions.py \
  --input    data/groundtruth/all_samples.json \
  --dest-dir data/submissions
```

### 5. Submit forms via Browser-Use sandbox automation

```bash
python scripts/agent_skill.py \
  --input    data/groundtruth/all_samples.json \
  --dest-dir data/submissions
```

### 6. Evaluate submissions against ground truth

```bash
python scripts/analysis.py \
  --groundtruth     data/groundtruth/groundtruth.json \
  --submissions-dir data/submissions \
  --output          data/results/summary.xlsx \
  --start-et        2026-01-01T08:00:00 \
  --end-et          2026-01-01T12:00:00
```

`--start-et` / `--end-et` are optional; if omitted, only submitted-form accuracy is computed (no Browser-Use task step counts or non-submission analysis).

## Deploy to DigitalOcean App Platform
1. Push this repo to GitHub.
2. In DigitalOcean control panel, create a new App.
3. Connect the GitHub repo and select the root of this project.
4. Set the environment:
   - Runtime: Dockerfile
   - HTTP Port: 8080 (the container binds to $PORT with default 8080)
   - Build & Run command: from Dockerfile defaults
5. Deploy.

For persistent submissions, add persistent storage:
1) In App Platform, add a Volume (Persistent Storage) to the service and mount it at `/app/data/submissions`.
2) The app will write JSON files there; they'll survive restarts and deployments.

Alternatively, use a managed store instead of filesystem:
- DigitalOcean Spaces (S3-compatible) and upload JSON objects
- A Managed Database (e.g., PostgreSQL) to store submissions as rows

## Extending the form
The fields included are a minimal subset. Update `app/templates/index.html` to add fields, and ensure validation rules in `app/models.py` are kept in sync.
