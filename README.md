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
├─ app/
│  ├─ __init__.py
│  ├─ main.py
│  ├─ models.py
│  ├─ static/
│  │  ├─ styles.css
│  │  └─ app.js
│  └─ templates/
│     └─ index.html
├─ data/
│  └─ submissions/
├─ .vscode/
│  └─ tasks.json
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
2) The app will write JSON files there; they’ll survive restarts and deployments.

Alternatively, use a managed store instead of filesystem:
- DigitalOcean Spaces (S3-compatible) and upload JSON objects
- A Managed Database (e.g., PostgreSQL) to store submissions as rows

## Extending the form
The fields included are a minimal subset. Update `app/templates/index.html` to add fields, and ensure validation rules in `app/models.py` are kept in sync.
