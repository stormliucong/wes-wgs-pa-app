import os
import re
import json
import uuid
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

# Configurable server base URL (public endpoints, no auth required)
BASE_URL = os.getenv(
    "BROWSER_USE_BASE_URL",
    "https://wes-wgs-pa-app-u2c8s.ondigitalocean.app"
).rstrip("/")
client = BrowserUse(api_key=api_key)

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
    first, last = _split_name(patient_name)
    local_dir = Path(__file__).resolve().parent / "data" / "submissions"
    saved_path = download_by_patient(session, BASE_URL, first, last, local_dir)
    if saved_path is None:
        # Fallback: download latest
        saved_path = download_latest(session, BASE_URL, local_dir)
        filename = saved_path.name
    else:
        filename = saved_path.name
    append_info_to_json(saved_path, completed_task_id, patient_id, sample_type, duration)
    # Optionally delete from server
    try:
        delete_submission(session, BASE_URL, filename)
    except Exception:
        pass
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
        samples = json.load(f)

    patients = [f"{s.get('patient_first_name', '')} {s.get('patient_last_name', '')}".strip() 
                for s in samples[6:15]]

    paralle_runner = run_parallel(patients)
    for res in paralle_runner:
        print(f"Processed: {res}")
    
    # # Take the first 5 patients and process sequentially
    # results: List[Dict] = []
    # for sample in samples[:5]:
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
