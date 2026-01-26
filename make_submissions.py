import os
import re
import json
import uuid
from pathlib import Path
from typing import Optional, List, Tuple, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time
import requests
from dotenv import load_dotenv

load_dotenv()
raw_api_key: Optional[str] = os.getenv("BROWSER_USE_API_KEY")
if raw_api_key is None or not raw_api_key.strip():
    raise RuntimeError("BROWSER_USE_API_KEY not found in environment")
api_key: str = raw_api_key.strip()

# Configurable server base URL (public endpoints, no auth required)
BASE_URL = os.getenv(
    "BROWSER_USE_BASE_URL",
    "https://wes-wgs-pa-app-u2c8s.ondigitalocean.app"
).rstrip("/")

# Browser-Use Cloud API base (v2)
API_BASE = os.getenv("BROWSER_USE_API_BASE", "https://api.browser-use.com/api/v2").rstrip("/")

def _api_headers() -> Dict[str, str]:
    return {
        "X-Browser-Use-API-Key": api_key,
        "Content-Type": "application/json",
    }

def _extract_duration_from_task(task_json: Dict) -> Optional[float]:
    """Compute duration from task JSON timestamps if available."""
    try:
        started = task_json.get("startedAt")
        finished = task_json.get("finishedAt")
        if not started or not finished:
            return None
        s = datetime.fromisoformat(started.replace("Z", "+00:00"))
        f = datetime.fromisoformat(finished.replace("Z", "+00:00"))
        return max((f - s).total_seconds(), 0.0)
    except Exception:
        return None

def create_session(start_url: Optional[str] = None) -> str:
    """Create a new Browser-Use session and return session ID."""
    payload = {
        "startUrl": start_url or None,
        "persistMemory": False,
        "keepAlive": False,
    }
    resp = requests.post(f"{API_BASE}/sessions", headers=_api_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    return body["id"]

def create_task(task_text: str) -> str:
    """Create and start a task in the given session and return task ID."""
    payload = {
        "task": task_text,
        "llm": "browser-use-llm",
        "maxSteps": 50,
        "thinking": True,
        "vision": True, 
        "allowedDomains": [BASE_URL.split("//", 1)[-1]]
    }
    resp = requests.post(f"{API_BASE}/tasks", headers=_api_headers(), json=payload, timeout=30)
    # 202 Accepted on success
    if resp.status_code not in (200, 202):
        resp.raise_for_status()
    return resp.json()["id"]

def get_task(task_id: str) -> Dict:
    resp = requests.get(f"{API_BASE}/tasks/{task_id}", headers=_api_headers(), timeout=60)
    resp.raise_for_status()
    return resp.json()

def wait_for_task(task_id: str, poll_interval: float = 2.0, timeout_seconds: int = 600) -> Dict:
    """Poll the task until finished or timeout; return final task JSON."""
    deadline = time.time() + timeout_seconds
    last = {}
    while time.time() < deadline:
        try:
            last = get_task(task_id)
            status = (last.get("status") or "").lower()
            if status in {"finished", "stopped"}:
                return last
        except requests.RequestException:
            pass
        time.sleep(poll_interval)
    return last

def _split_name(full_name: str) -> Tuple[str, str]:
    parts = [p for p in (full_name or "").strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]

def _filename_from_disposition(disposition: Optional[str]) -> Optional[str]:
    if not disposition:
        return None
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', disposition)
    return m.group(1).strip() if m else None

def download_latest(session: requests.Session, base_url: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    resp = session.get(f"{base_url}/download/latest", stream=True)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to download latest: {resp.status_code}")
    filename = _filename_from_disposition(resp.headers.get('Content-Disposition')) or f"latest_{uuid.uuid4().hex}.json"
    out_path = dest_dir / filename
    with out_path.open("wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    return out_path

def download_by_patient(session: requests.Session, base_url: str, first_name: str, last_name: str, dest_dir: Path) -> Optional[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    resp = session.post(f"{base_url}/download/patient", json={
        "patient_first_name": first_name,
        "patient_last_name": last_name,
    }, stream=True)
    # If server returns JSON with file=None
    ct = resp.headers.get('Content-Type', '')
    if ct.startswith('application/json'):
        try:
            body = resp.json()
            if body.get('file') is None:
                return None
        except Exception:
            return None
    if resp.status_code != 200:
        return None
    filename = _filename_from_disposition(resp.headers.get('Content-Disposition')) or f"patient_{first_name}_{last_name}_{uuid.uuid4().hex}.json"
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
    resp = session.post(f"{base_url}/delete", json={"filename": filename})
    if resp.status_code != 200:
        raise RuntimeError(f"Delete failed for {filename}: {resp.status_code} {resp.text}")
    body = {}
    try:
        body = resp.json()
    except Exception:
        pass
    if not body.get("ok", False):
        raise RuntimeError(f"Delete failed for {filename}: {body}")

def execute_one_patient(patient_name: str, patient_id: Optional[str] = None, sample_type: Optional[str] = None) -> Dict:
    prompt = (
        f"Visit the web app at {BASE_URL}. On the first log-in page, do user sign-in with username \"user2\" and password \"pass789\". "
        f"Then find the patient record for {patient_name}, use the patient search function on the site, fill out and submit a Pre-Authorization "
        f"Form for this patient. Verify all required fields, then directly submit. If you find any issues in the patient profile, stop and report the issue."
    )
    # session_id = create_session(start_url=BASE_URL)
    task_id = create_task(task_text=prompt)
    final_task = wait_for_task(task_id)
    duration = _extract_duration_from_task(final_task)
    session = requests.Session()
    first, last = _split_name(patient_name)
    local_dir = Path(__file__).resolve().parent / "data" / "submissions"
    saved_path = download_by_patient(session, BASE_URL, first, last, local_dir)
    if saved_path is None:
        # Fallback: download latest
        saved_path = download_latest(session, BASE_URL, local_dir)
        filename = saved_path.name
    else:
        filename = saved_path.name
    append_info_to_json(saved_path, task_id, patient_id, sample_type, duration)
    # Optionally delete from server
    try:
        delete_submission(session, BASE_URL, filename)
    except Exception:
        pass
    return {"patient": patient_name, "task_id": task_id, "filename": filename, "saved_path": str(saved_path), "duration": duration}

def run_parallel(patients: List, workers: int = 3) -> List[Dict]:
    """Run submissions in parallel.

    Accepts either a list of patient name strings or a list of sample dicts
    containing keys like 'patient_first_name', 'patient_last_name',
    'patient_id', and 'sample_type'.
    """
    results: List[Dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for p in patients:    
            first = p.get("patient_first_name", "")
            last = p.get("patient_last_name", "")
            patient_name = f"{first} {last}".strip()
            patient_id = p.get("patient_id")
            sample_type = p.get("sample_type")
            futures[pool.submit(execute_one_patient, patient_name, patient_id, sample_type)] = patient_name

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
        samples = json.load(f)
    
    patients = samples[1:5]
    paralle_runner = run_parallel(patients)
    for res in paralle_runner:
        print(f"Processed: {res}")
  
    # results: List[Dict] = []
    # for sample in samples[35:39]:
    #     patient_name = f"{sample.get('patient_first_name', '')} {sample.get('patient_last_name', '')}".strip()
    #     patient_id = sample.get("patient_id")
    #     sample_type = sample.get("sample_type")
    #     try:
    #         res = execute_one_patient(patient_name, patient_id, sample_type)
    #         results.append(res)
    #         print(f"Processed: {res}")
    #     except Exception as e:
    #         err = {"patient": patient_name, "error": str(e)}
    #         results.append(err)
    #         print(f"Error: {err}")
