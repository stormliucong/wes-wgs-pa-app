# WES/WGS Pre-Authorization Project

Flask-based web form + data generation + browser automation + evaluation pipeline for WES/WGS prior authorization experiments.

## Project Structure
```
wes-wgs-pa-app/
├─ app/                                  # Web Application (routes, templates, models, validation)
│  ├─ main.py
│  ├─ models.py
│  ├─ templates/
│  └─ static/
├─ scripts/
│  ├─ data_generation/
│  │  ├─ groundtruth.py
│  │  ├─ generate_unstructured_profiles.py
│  │  └─ validate_clinical_note.py
│  ├─ browser_automation/
│  │  ├─ make_submissions.py
│  │  └─ agent_skill.py
│  └─ evaluation/
│     └─ analysis.py
├─ data/                                 # Local runtime data (not committed)
│  ├─ generated/                         # structured ground truth + labeled sample sets
│  ├─ unstructured/                      # generated clinical notes + validated notes
│  ├─ batch/                             # batch API input/output jsonl files
│  ├─ automation/submissions/            # downloaded submissions from browser automation
│  └─ results/                           # evaluation outputs (xlsx/json)
├─ requirements.txt
└─ Dockerfile
```

## Data Policy
- Keep all generated data local in `data/`.
- `data/**/*.json`, `data/**/*.jsonl`, and `data/**/*.xlsx` are ignored in git.

## Setup
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Web Application
```bash
python -m flask --app app.main run --debug
```

## Scripts (all use data-folder input/output)

### 1) Generate structured profiles
```bash
python scripts/data_generation/groundtruth.py \
   --groundtruth-output data/generated/groundtruth.json \
   --samples-output data/generated/all_samples.json
```

### 2) Generate unstructured notes
```bash
python scripts/data_generation/generate_unstructured_profiles.py \
   --input data/generated/all_samples.json \
   --output data/unstructured/unstructured_profiles.json \
   --batch-input data/batch/batch_input.jsonl
```

### 3) Validate generated notes
```bash
python scripts/data_generation/validate_clinical_note.py \
   --input data/unstructured/unstructured_profiles.json \
   --output data/unstructured/validated_profiles.json \
   --batch-input data/batch/validation_batch_input.jsonl \
   --raw-output data/batch/validation_raw_output.jsonl
```

### 4) Browser automation submissions
```bash
python scripts/browser_automation/make_submissions.py \
   --input data/generated/all_samples.json \
   --output-dir data/automation/submissions \
   --sample-type 4 \
   --workers 50
```

### 5) Evaluate submissions
```bash
python scripts/evaluation/analysis.py \
   --groundtruth data/generated/groundtruth.json \
   --submissions-dir data/automation/submissions \
   --results data/results/summary.xlsx \
   --start-et 2026-02-10T00:00:00 \
   --end-et 2026-02-18T15:00:00
```
