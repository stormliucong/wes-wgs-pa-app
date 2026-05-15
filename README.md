# WES/WGS Pre-Authorization Project

Flask-based web form + data generation + browser automation + evaluation pipeline for WES/WGS prior authorization experiments.

## Project Structure

- **`app/`** — Flask web application
  - `main.py` — All routes: login, form submission, admin, download/delete endpoints
  - `models.py` — Pydantic models and field-level validation logic for PA form payloads
  - **`static/`**
    - `app.js` — Front-end form logic (field dependencies, validation feedback)
    - `styles.css` — Application stylesheet
  - **`templates/`**
    - `index.html` — Main PA form UI
    - `ehr.html` — Read-only EHR patient record view shown to the agent
    - `user_login.html` — Login page for browser agent users
    - `admin.html` — Admin dashboard (view/download all submissions)
    - `admin_login.html` — Login page for the admin dashboard


- **`scripts/`**
  - **`1_data_generation/`**
    - `groundtruth.py` — Generate synthetic patient profiles and ground-truth PA form answers across label types (1=perfect, 2a/b/c=errors, 3a/b=irrelevant, 4=name collision)
    - `generate_unstructured_profiles.py` — Convert structured profiles into free-text clinical notes via OpenAI batch API

  - **`2_run_agent_experiment/`**
    - `browser_use_execution.py` — Main experiment runner: launches Browser-Use Cloud tasks for each patient, polls for completion, downloads and saves submission JSON. Both main experiment and ablation study 1 & 3 can be run with this script, click for details
    - `ablation_2.py` — Ablation 2 (agent vs. no-agent): sends profiles directly to Gemini API, then GPT-classifies responses

  - **`3_evaluation/`**
    - `main_exp_eval.py` — Evaluation pipeline: fetches completed tasks from Browser-Use API, compares submissions field-by-field against ground truth, classifies non-submissions via GPT batch, writes data/results/exp_results.xlsx
    - `visualization.ipynb` — Notebook for generating plots as shown in the manuscript from evaluation outputs


- **`data/`** — Local runtime data (mostly not committed — see Data Policy)
  - `patient_data/` — Structured ground-truth profiles and sample sets *(committed)*
  - `batch_input/` — JSONL files for OpenAI/Gemini batch API jobs *untrakced*
  - `ablation_3/` — Submission JSONs from ablation 3 (Gemini 3 Pro with prompt specificity) *untrakced*
  - `claude_opus/` — Submission JSONs from main experiment — Claude Opus *untrakced*
  - `gemini_3_pro/` — Submission JSONs from main experiment — Gemini 3 Pro *untracked*
  - `gemini_flash/` — Submission JSONs from main experiment — Gemini Flash *untracked*
  - `gemini_flash_ablation_55/` — Submission JSONs from ablation 1 at max_steps=55 *untracked*
  - `gemini_flash_ablation_70/` — Submission JSONs from ablation 1 at max_steps=70 *untracked*
  - `ablation_1_85/` — Submission JSONs from ablation 1 at max_steps=85 *untrakced*
  - `gemini_flash_ablation_100/` — Submission JSONs from ablation 1 at max_steps=100 *untracked*

  - **`results/`** *(partially committed — see Data Policy)*
    - `exp_results.xlsx` — Main experiment evaluation output (multiple sheets, open in Excel for details)
    - `submitted_summaries.json` — Flattened summary records from main experiment tasks with a submission
    - `non_submitted_summaries.json` — Flattened summary records for from main experiment tasks that did not produce a submission, with issue classification
    - **`ablation_study/`**
      - `ablation_1.json` — Raw results from Browser Use API for ablation 1 (task outcome categories directly embedded)
      - `ablation_1_submitted.json` — Submitted froms examination for ablation study 1
      - `ablation_2_gemini_api.json` — Raw Gemini API responses for ablation 2
      - `ablation_2_gpt_review.json` — GPT classifications of ablation 2 Gemini responses

- `Dockerfile` — Container definition for DigitalOcean App Platform deployment
- `run.ps1` — PowerShell helper to start the Flask dev server locally
- `requirements.txt` — Python dependencies

## Data Policy
- `data/patient_data/` is committed; everything else under `data/` is gitignored by default.
- Exceptions (force-added): `data/results/exp_results.xlsx`, `data/results/submitted_summaries.json`, `data/results/non_submitted_summaries.json`, and all files under `data/results/ablation_study/`.

## Setup
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Web Application
```bash
python -m flask --app app.main run --debug (dev mode)
```

## Scripts

### 1) Generate structured ground-truth profiles
```bash
python scripts/1_data_generation/groundtruth.py
```

### 2) Generate unstructured clinical notes
```bash
python scripts/1_data_generation/generate_unstructured_profiles.py
```

### 3) Run browser-agent experiment
```bash
python scripts/2_run_agent_experiment/browser_use_execution.py \
  E.g., --mode primary --llm gemini-flash-latest --output-dir data/gemini_flash
  The configuration can be adjusted, see the script for details
```

### 4) Run ablation studies

**Ablation 1** - increasing max steps (Gemini 3 Flash)
```bash
python scripts/2_run_agent_experiment/browser_use_execution.py \
  E.g., --mode ablation_1 --llm gemini-flash-latest --max-steps 55 --output-dir data/gemini_flash_ablation_55 
```

**Ablation 2** — agent vs. no-agent (Gemini API direct inference + GPT classification):
```bash
python scripts/2_run_agent_experiment/ablation_2.py
```

**Ablation 3** — prompt specificity (Gemini 3 Pro on a subsample of submitted cases for profile 2a, 2b, 2c, 3a, 3b, 4):
```bash
python scripts/2_run_agent_experiment/browser_use_execution.py \
  --mode ablation_3 --llm gemini-3-pro-preview --output-dir data/ablation_3
```

### 5) Evaluate tasks
```bash
python scripts/3_evaluation/exp_eval.py
```
