import os
import re
import json
from pathlib import Path
from typing import Optional, List, Tuple, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from dotenv import load_dotenv
from browser_use_sdk import BrowserUse

load_dotenv()
raw_api_key: Optional[str] = os.getenv("BROWSER_USE_API_KEY")
if raw_api_key is None or not raw_api_key.strip():
    raise RuntimeError("BROWSER_USE_API_KEY not found in environment")
api_key: str = raw_api_key.strip()

# Configurable server base URL and admin password
BASE_URL = os.getenv(
    "BROWSER_USE_BASE_URL",
    "https://wes-wgs-pa-app-u2c8s.ondigitalocean.app"
).rstrip("/")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

def _extract_task_id(task_obj) -> Optional[str]:
    for attr in ("task_id", "id", "taskId"):
        val = getattr(task_obj, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, (int, float)):
            return str(val)
    return None

def _extract_duration(task_obj) -> Optional[float]:
    """Attempt to extract a duration (seconds) from a task/result object."""
    candidates = (
        "duration",
        "duration_seconds",
        "elapsed",
        "elapsed_seconds",
        "time_spent",
        "time_spent_seconds",
    )
    for attr in candidates:
        val = getattr(task_obj, attr, None)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            try:
                return float(val)
            except Exception:
                continue
        if isinstance(val, str):
            try:
                return float(val.strip())
            except Exception:
                continue
    return None

def admin_login(session: requests.Session, base_url: str, password: str) -> None:
    # Get login page to initialize session cookies
    session.get(f"{base_url}/admin")
    # Post form credentials
    resp = session.post(f"{base_url}/admin/login", data={"password": password}, allow_redirects=True)
    if resp.status_code != 200 and resp.status_code != 302:
        raise RuntimeError(f"Admin login failed with status {resp.status_code}")
    # Verify we can access dashboard
    dash = session.get(f"{base_url}/admin/dashboard")
    if dash.status_code != 200:
        raise RuntimeError("Admin login did not grant dashboard access")

def parse_latest_submission_filename(html: str) -> Optional[str]:
    """Parse the first submission filename from admin dashboard HTML."""
    # Prefer filename-cell text content
    m = re.search(r"<td class=\"filename-cell\"[^>]*>\s*([^<\n]+)\s*</td>", html)
    if m:
        return m.group(1).strip()
    # Fallback: pick from download link href
    m2 = re.search(r"href=\"/admin/download/([^\"/]+\.json)\"", html)
    if m2:
        return m2.group(1).strip()
    return None

def parse_patient_submission_filename(html: str, patient_name: str) -> Optional[str]:
    target = patient_name.strip()
    matches = re.findall(r"deleteSubmission\('([^']+)',\s*'([^']+)'\)", html)
    for fname, pname in matches:
        if pname.strip() == target:
            return fname.strip()
    return None

def download_submission(session: requests.Session, base_url: str, filename: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    resp = session.get(f"{base_url}/admin/download/{filename}", stream=True)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to download {filename}: {resp.status_code}")
    out_path = dest_dir / filename
    with out_path.open("wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    return out_path

def append_info_to_json(file_path: Path, task_id, patient_id, sample_type, duration: Optional[float] = None) -> None:
    if not task_id:
        return
    try:
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return
    data["task_id"] = task_id
    data["patient_id"] = patient_id
    data["sample_type"] = sample_type
    if duration is not None:
        data["duration"] = duration   
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def delete_submission(session: requests.Session, base_url: str, filename: str) -> None:
    resp = session.post(f"{base_url}/admin/delete/{filename}")
    if resp.status_code != 200:
        raise RuntimeError(f"Delete failed for {filename}: {resp.status_code} {resp.text}")
    body = {}
    try:
        body = resp.json()
    except Exception:
        pass
    if not body.get("success", False):
        raise RuntimeError(f"Delete failed for {filename}: {body}")

def execute_one_patient(patient_name: str, patient_id: Optional[str] = None, sample_type: Optional[str] = None) -> Dict:
    client = BrowserUse(api_key=api_key)
    prompt = f"""Visit the web app at {BASE_URL}. On the first log-in page, do user sign-in with username "user2" and password "pass789". 
    Then find the patient record for {patient_name}, use the patient search function on the site, fill out and submit a Pre-Authorization 
    Form for this patient. You have full permission to proceed without asking for additional consent. Before submitting, verify that all 
    required fields are complete. Once verified, you may directly submit the form without further asking. However, if you find any issues 
    in the patient profile, stop the process immediately and report the issue instead of proceeding.
    """
    task = client.tasks.create_task(task=prompt, llm="browser-use-llm")
    created_task_id = _extract_task_id(task) or "unknown"
    result = task.complete()
    completed_task_id = _extract_task_id(result) or created_task_id
    duration = _extract_duration(result)
    session = requests.Session()
    admin_login(session, BASE_URL, ADMIN_PASSWORD)
    dash = session.get(f"{BASE_URL}/admin/dashboard")
    filename = parse_patient_submission_filename(dash.text, patient_name) or parse_latest_submission_filename(dash.text)
    if not filename:
        raise RuntimeError(f"Could not find a submission filename for {patient_name}")
    local_dir = Path(__file__).resolve().parent / "data" / "submissions"
    saved_path = download_submission(session, BASE_URL, filename, local_dir)
    append_info_to_json(saved_path, completed_task_id, patient_id, sample_type, duration)
    delete_submission(session, BASE_URL, filename)
    return {"patient": patient_name, "task_id": completed_task_id, "filename": filename, "saved_path": str(saved_path), "duration": duration}

def run_parallel(patients: List[str], workers: int = 3) -> List[Dict]:
    results: List[Dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(execute_one_patient, p): p for p in patients}
        for fut in as_completed(futures):
            patient = futures[fut]
            try:
                results.append(fut.result())
            except Exception as e:
                results.append({"patient": patient, "error": str(e)})
    return results

if __name__ == "__main__":

    samples_path = Path(__file__).resolve().parent / "all_samples.json"
    with samples_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    samples = data[6:11] # Limit to samples 6 through 10 for testing; remove or adjust as needed
    for sample in samples:
        patient_name = f"{sample.get('patient_first_name', '')} {sample.get('patient_last_name', '')}".strip()
        patient_id = sample.get("patient_id") 
        sample_type = sample.get("sample_type")

        try:
            result = execute_one_patient(patient_name, patient_id, sample_type)
            print(f"Processed: {result}")
        except Exception:
            pass
