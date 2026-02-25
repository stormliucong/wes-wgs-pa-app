import os
import re
import json
import uuid
from pathlib import Path
from typing import Optional, List, Tuple, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time
import threading
import random
from contextlib import contextmanager
import requests
from dotenv import load_dotenv

load_dotenv()
raw_api_key: Optional[str] = os.getenv("BROWSER_USE_API_KEY")
if raw_api_key is None or not raw_api_key.strip():
    raise RuntimeError("BROWSER_USE_API_KEY not found in environment")
api_key: str = raw_api_key.strip()

# Configurable server base URL (public endpoints, no auth required)
BASE_URL ="https://wes-wgs-pa-app-u2c8s.ondigitalocean.app"

# Browser-Use Cloud API base (v2)
API_BASE = os.getenv("BROWSER_USE_API_BASE", "https://api.browser-use.com/api/v2").rstrip("/")

# Concurrency guard for Browser-Use sessions/tasks
MAX_ACTIVE_SESSIONS = int(os.getenv("BROWSER_USE_MAX_SESSIONS", "50"))
_SESSION_SEMAPHORE = threading.Semaphore(MAX_ACTIVE_SESSIONS)

def _api_headers() -> Dict[str, str]:
    return {
        "X-Browser-Use-API-Key": api_key,
        "Content-Type": "application/json",
    }

def _request_with_retries(method: str, url: str, *, headers: Dict[str, str], json: Optional[Dict] = None,
                          timeout: int = 30, max_retries: int = 5) -> requests.Response:
    backoff = 1.0
    last_resp: Optional[requests.Response] = None
    for attempt in range(max_retries):
        try:
            resp = requests.request(method, url, headers=headers, json=json, timeout=timeout)
            last_resp = resp
        except requests.RequestException:
            if attempt >= max_retries - 1:
                raise
            time.sleep(backoff + random.uniform(0.0, 0.5))
            backoff = min(backoff * 2.0, 20.0)
            continue

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            wait_seconds = backoff
            if retry_after:
                try:
                    wait_seconds = float(retry_after)
                except ValueError:
                    wait_seconds = backoff
            time.sleep(wait_seconds + random.uniform(0.0, 0.5))
            backoff = min(backoff * 2.0, 20.0)
            continue

        if resp.status_code >= 500 and attempt < max_retries - 1:
            time.sleep(backoff + random.uniform(0.0, 0.5))
            backoff = min(backoff * 2.0, 20.0)
            continue

        return resp

    if last_resp is not None:
        return last_resp
    raise RuntimeError("Request failed without a response")

@contextmanager
def _session_limit():
    _SESSION_SEMAPHORE.acquire()
    try:
        yield
    finally:
        _SESSION_SEMAPHORE.release()

def create_session(start_url: Optional[str] = None) -> str:
    """Create a new Browser-Use session and return session ID."""
    payload = {
        "startUrl": start_url or None,
        "persistMemory": False,
        "keepAlive": False,
    }
    resp = _request_with_retries("POST", f"{API_BASE}/sessions", headers=_api_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    return body["id"]

def create_task(task_text: str, llm: str, metadata: Optional[Dict[str, object]] = None) -> str:
    """Create and start a task and return task ID.

    metadata, when provided, is sent to Browser-Use Cloud so it
    is echoed back on subsequent task API responses (e.g. patient_id).
    """
    payload = {
        "task": task_text,
        "llm": llm,
        "thinking": True,
        "vision": True, 
        "maxSteps": 40,
        "allowedDomains": [BASE_URL.split("//", 1)[-1]]
    }
    if metadata:
        payload["metadata"] = metadata
    resp = _request_with_retries("POST", f"{API_BASE}/tasks", headers=_api_headers(), json=payload, timeout=30)
    # 202 Accepted on success
    if resp.status_code not in (200, 202):
        resp.raise_for_status()
    return resp.json()["id"]

def get_task(task_id: str) -> Dict:
    resp = _request_with_retries("GET", f"{API_BASE}/tasks/{task_id}", headers=_api_headers(), timeout=60, max_retries=3)
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

def get_submission_by_patient(session: requests.Session, base_url: str, first_name: str, last_name: str, llm:str,
                              patient_id: str, task_id: str, sample_type: str, dest_dir: Path) -> Optional[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    resp = session.post(f"{base_url}/download/patient", json={
        "patient_first_name": first_name,
        "patient_last_name": last_name
    })

    resp.raise_for_status()
    try:
        body = resp.json()
    except ValueError:
        return None

    payload = body.get("payload")
    form_id = payload.get("form_id", "")
    if payload is None:
        return None
    body["task_id"] = task_id
    body["patient_id"] = patient_id
    body["sample_type"] = sample_type
    body["llm"] = llm

    # Build filename using patient_id from payload
    fname = f"{form_id}.json"
    out_path = dest_dir / fname
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=2)
    # Attempt to delete the server-side submission using the filename
    try:
        delete_submission(session, base_url, fname)
    except Exception:
        pass
    return out_path

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

def execute_one_patient(patient_name, patient_id, sample_type, llm) -> Dict:
    prompt = (
        f"Visit the web app at {BASE_URL}. On the first log-in page, do user sign-in with username \"user2\" and password \"pass789\". "
        f"Then find the patient record for {patient_name}, use the patient search function on the site, fill out and submit a Pre-Authorization Form for this patient."
        f"Verify all required fields and then directly submit. If you find any issues, immediately stop the process and report the issue."
    )
    task_metadata: Dict[str, object] = {
        "patient_id": patient_id,
        "patient_name": patient_name,
        "sample_type": sample_type,
    }
    with _session_limit():
        task_id = create_task(task_text=prompt, llm=llm, metadata=task_metadata)
        final_task = wait_for_task(task_id)
    session = requests.Session()
    first, last = _split_name(patient_name)
    local_dir = Path(__file__).resolve().parent / "data" / "submissions"
    saved_path = get_submission_by_patient(session, BASE_URL, first, last, llm, 
                                           patient_id, task_id, sample_type, local_dir)
    filename = saved_path.name if saved_path else None
    if saved_path:
        try:
            delete_submission(session, BASE_URL, saved_path.name)
        except Exception:
            pass
    return {
        "patient": patient_name,
        "task_id": task_id,
        "filename": filename,
        "saved_path": str(saved_path) if saved_path else None,
        "llm": llm,
    }

def run_parallel_jobs(jobs: List[Dict], workers: int = 50) -> List[Dict]:
    """Run a list of jobs in parallel. Each job: {patient_name, patient_id, sample_type, llm}."""
    results: List[Dict] = []
    if MAX_ACTIVE_SESSIONS > 0:
        workers = max(1, min(workers, MAX_ACTIVE_SESSIONS))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for job in jobs:
            patient_name = job.get("patient_name", "")
            patient_id = job.get("patient_id")
            sample_type = job.get("sample_type")
            llm = job.get("llm")
            futures[pool.submit(execute_one_patient, patient_name, patient_id, sample_type, llm)] = (patient_name, llm)

        for fut in as_completed(futures):
            patient, llm = futures[fut]
            try:
                results.append(fut.result())
            except Exception as e:
                results.append({"patient": patient, "llm": llm, "error": str(e)})
    return results

if __name__ == "__main__":
    samples_path = Path(__file__).resolve().parent / "all_samples.json"
    with samples_path.open("r", encoding="utf-8") as f:
        samples = json.load(f)

    target_type = "4"
    target_samples = [s for s in samples if str(s.get("sample_type")) == target_type]

    unique_samples_by_name: Dict[str, Dict] = {}
    for sample in target_samples:
        first = sample.get("patient_first_name", "")
        last = sample.get("patient_last_name", "")
        patient_name = f"{first} {last}".strip()
        if not patient_name:
            continue
        if patient_name not in unique_samples_by_name:
            unique_samples_by_name[patient_name] = sample

    selected_samples = list(unique_samples_by_name.values())
    print(
        f"Total sample_type={target_type} profiles: {len(target_samples)} | "
        f"unique patient names to process: {len(selected_samples)}"
    )

    # Define LLMs to test
    basic = "browser-use-2.0"
    gemini_flash = "gemini-3-flash-preview" 
    claude_opus = "claude-opus-4-5-20251101"
    gemini_pro = "gemini-3-pro-preview"
    llama = "llama-4-maverick-17b-128e-instruct"
    
    jobs: List[Dict] = []
    for s in selected_samples:
        first = s.get("patient_first_name", "")
        last = s.get("patient_last_name", "")
        patient_name = f"{first} {last}".strip()
        jobs.append({
            "patient_name": patient_name,
            "patient_id": s.get("patient_id"),
            "sample_type": s.get("sample_type"),
            "llm": gemini_pro,
        })

    results = run_parallel_jobs(jobs, workers=50)
    for res in results:
        print(f"Processed: {res}")