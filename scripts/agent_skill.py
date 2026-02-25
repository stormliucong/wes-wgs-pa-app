import asyncio
import os
import re
import json
import uuid
from pathlib import Path
import requests
from dotenv import load_dotenv

from browser_use import Browser, sandbox, ChatBrowserUse
from browser_use.agent.service import Agent

load_dotenv()

BASE_URL = os.getenv(
    "BROWSER_USE_BASE_URL",
    "https://wes-wgs-pa-app-u2c8s.ondigitalocean.app"
).rstrip("/")

# --- Helper functions for file download & annotation ---

def _split_name(full_name: str):
    parts = [p for p in (full_name or "").strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]

def _filename_from_disposition(disposition: str | None):
    if not disposition:
        return None
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', disposition)
    return m.group(1).strip() if m else None

def download_submission_for_patient(session, first, last, dest_dir: Path):
    dest_dir.mkdir(parents=True, exist_ok=True)
    resp = session.post(f"{BASE_URL}/download/patient", json={
        "patient_first_name": first,
        "patient_last_name": last,
    }, stream=True)
    ct = resp.headers.get("Content-Type", "")
    if ct.startswith("application/json"):
        try:
            body = resp.json()
            if body.get("file") is None:
                return None
        except Exception:
            return None
    if resp.status_code != 200:
        return None
    filename = _filename_from_disposition(resp.headers.get("Content-Disposition")) \
               or f"{first}_{last}_{uuid.uuid4().hex}.json"
    out_path = dest_dir / filename
    with out_path.open("wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    return out_path

def append_info_to_json(file_path: Path, patient_id, sample_type):
    try:
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return
    data["patient_id"] = patient_id
    data["sample_type"] = sample_type
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def delete_submission_file(filename: str):
    """Delete a submission on the server by filename; ignore errors if unavailable."""
    try:
        resp = requests.post(f"{BASE_URL}/delete", json={"filename": filename}, timeout=30)
        # Do not raise on non-200; just best-effort
    except Exception:
        pass

# --- Sandbox task (runs in cloud) ---

@sandbox(
    BROWSER_USE_API_KEY=os.getenv("BROWSER_USE_API_KEY"),
    cloud_timeout=30  # minutes
)
async def submit_patient_form(
    browser: Browser,
    patient_name: str,
    patient_id: str,
    sample_type: str
) -> dict:
    """
    Runs the automation agent for a single patient inside a sandboxed browser session.
    This function will be executed in parallel up to the concurrency limit.
    """
    # Build your prompt
    prompt = (
        f"Visit the web app at {BASE_URL}. On the log-in page, sign in with username "
        f"\"user2\" and password \"pass789\". Then find the patient record for {patient_name}, "
        f"search for that patient, fill and submit the Pre-Authorization Form. "
        "If you encounter issues, stop and report them."
    )
    llm = ChatBrowserUse()
    agent = Agent(task=prompt, browser=browser, llm=llm)
    await agent.run()  # runs the automation

    # After automation, download the submission
    first, last = _split_name(patient_name)
    local_dir = Path(__file__).resolve().parent.parent / "data" / "submissions"
    saved_path = download_submission_for_patient(requests.Session(), first, last, local_dir)
    if saved_path is None:
        # Fallback: download latest if patient-specific fails
        resp = requests.Session().get(f"{BASE_URL}/download/latest", stream=True)
        filename = _filename_from_disposition(resp.headers.get("Content-Disposition")) \
                   or f"latest_{uuid.uuid4().hex}.json"
        saved_path = local_dir / filename
        with saved_path.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        # After downloading latest, delete it from server
        if filename and filename.endswith('.json'):
            delete_submission_file(filename)

    append_info_to_json(saved_path, patient_id, sample_type)
    

    return {"patient": patient_name, "saved_path": str(saved_path)}

# --- Parallel runner with concurrency limit ---

async def run_all_parallel(patients: list[dict], max_concurrency: int = 3):
    semaphore = asyncio.Semaphore(max_concurrency)

    async def worker(p):
        async with semaphore:
            try:
                return await submit_patient_form(
                    patient_name=p["patient_name"],
                    patient_id=p["patient_id"],
                    sample_type=p["sample_type"]
                )
            except Exception as e:
                return {"patient": p["patient_name"], "error": str(e)}

    tasks = [worker(p) for p in patients]
    # Run all tasks and collect results
    return await asyncio.gather(*tasks)

# --- Entry point ---

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description='Submit pre-authorization forms via Browser-Use sandbox automation'
    )
    parser.add_argument('-i', '--input', type=str, default='data/groundtruth/all_samples.json',
                        help='Input JSON file with patient sample profiles (default: data/groundtruth/all_samples.json)')
    parser.add_argument('--dest-dir', type=str, default='data/submissions',
                        help='Directory to save downloaded submissions (default: data/submissions)')
    args = parser.parse_args()

    samples_file = Path(__file__).resolve().parent.parent / args.input
    with open(samples_file, "r", encoding="utf-8") as f:
        samples_data = json.load(f)

    patients_list = [
        {
            "patient_name": f'{s.get("patient_first_name","")} {s.get("patient_last_name","")}'.strip(),
            "patient_id": s.get("patient_id"),
            "sample_type": s.get("sample_type"),
        }
        for s in samples_data[12:18]
    ]

    results = asyncio.run(run_all_parallel(patients_list, max_concurrency=3))

    # Print or save results
    for r in results:
        print(r)
