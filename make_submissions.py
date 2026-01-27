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
import random

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

# Concurrency and stagger settings to reduce 429 rate limit errors
def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default

MAX_CONCURRENCY = _env_int("BROWSER_USE_MAX_CONCURRENCY", 3)
START_STAGGER_SECS = _env_float("BROWSER_USE_START_STAGGER_SECS", 0.7)

def _api_headers() -> Dict[str, str]:
    return {
        "X-Browser-Use-API-Key": api_key,
        "Content-Type": "application/json",
    }

def _request_with_backoff(method: str, url: str, *, headers=None, json=None, timeout=30, max_retries=5, base_delay=0.5):
    """HTTP request wrapper with exponential backoff on 429 and 5xx.
    Respects 'Retry-After' header when present.
    """
    attempt = 0
    while attempt < max_retries:
        try:
            resp = requests.request(method, url, headers=headers, json=json, timeout=timeout)
        except requests.RequestException:
            resp = None

        if resp is not None and resp.status_code not in (429,) and not (500 <= resp.status_code < 600):
            return resp

        # Compute delay
        retry_after = 0.0
        if resp is not None:
            ra = resp.headers.get("Retry-After")
            if ra:
                try:
                    retry_after = float(ra)
                except ValueError:
                    retry_after = 0.0
        delay = max(retry_after, base_delay * (2 ** attempt)) + random.uniform(0.0, 0.25)
        time.sleep(delay)
        attempt += 1

    # Final attempt without further backoff
    return requests.request(method, url, headers=headers, json=json, timeout=timeout)

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
    resp = _request_with_backoff("POST", f"{API_BASE}/sessions", headers=_api_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    return body["id"]

def create_task(task_text: str, llm: str) -> str:
    """Create and start a task in the given session and return task ID."""
    payload = {
        "task": task_text,
        "llm": llm,
        "thinking": True,
        "vision": True, 
        "allowedDomains": [BASE_URL.split("//", 1)[-1]]
    }
    resp = _request_with_backoff("POST", f"{API_BASE}/tasks", headers=_api_headers(), json=payload, timeout=30)
    # 202 Accepted on success
    if resp.status_code not in (200, 202):
        resp.raise_for_status()
    return resp.json()["id"]

def get_task(task_id: str) -> Dict:
    resp = _request_with_backoff("GET", f"{API_BASE}/tasks/{task_id}", headers=_api_headers(), timeout=60)
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

def append_info_to_json(file_path: Path, task_id, patient_id, sample_type, duration: Optional[float] = None, llm: Optional[str] = None) -> None:
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
    if llm is not None:
        data["llm"] = llm
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

def execute_one_patient(patient_name: str, patient_id: Optional[str] = None, sample_type: Optional[str] = None, llm: str = "gemini-3-pro-preview", stagger_index: int = 0) -> Dict:
    prompt = (
        f"Visit the web app at {BASE_URL}. On the first log-in page, do user sign-in with username \"user2\" and password \"pass789\". "
        f"Then find the patient record for {patient_name}, use the patient search function on the site, fill out and submit a Pre-Authorization "
        f"Form for this patient. Verify all required fields, then directly submit. If you find any issues in the patient profile, stop and report the issue."
    )
    # Optional stagger to avoid synchronized spikes at session/task creation
    initial_delay = max(0.0, START_STAGGER_SECS * float(stagger_index)) + random.uniform(0.0, 0.3)
    time.sleep(initial_delay)
    # session_id = create_session(start_url=BASE_URL)
    task_id = create_task(task_text=prompt, llm=llm)
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
    append_info_to_json(saved_path, task_id, patient_id, sample_type, duration, llm)
    # Optionally delete from server
    try:
        delete_submission(session, BASE_URL, filename)
    except Exception:
        pass
    return {"patient": patient_name, "task_id": task_id, "filename": filename, "saved_path": str(saved_path), "duration": duration, "llm": llm}

def run_parallel_jobs(jobs: List[Dict], workers: int = MAX_CONCURRENCY) -> List[Dict]:
    """Run a list of jobs in parallel. Each job: {patient_name, patient_id, sample_type, llm}."""
    results: List[Dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for idx, job in enumerate(jobs):
            patient_name = job.get("patient_name", "")
            patient_id = job.get("patient_id")
            sample_type = job.get("sample_type")
            llm = job.get("llm", "gemini-3-pro-preview")
            stagger_index = idx % max(1, workers)
            futures[pool.submit(execute_one_patient, patient_name, patient_id, sample_type, llm, stagger_index)] = (patient_name, llm)

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

    target_types = {"1", "3a", "3c"}
    target_samples = [s for s in samples if str(s.get("sample_type")) in target_types]

    # Define LLMs to test
    llms = [
        "claude-opus-4-5-20251101",   # Claude Opus
        "gemini-3-pro-preview",       # Gemini 3 Preview Pro
    ]

    # Build jobs: each sample × each llm
    jobs: List[Dict] = []
    for s in target_samples:
        first = s.get("patient_first_name", "")
        last = s.get("patient_last_name", "")
        patient_name = f"{first} {last}".strip()
        for model in llms:
            jobs.append({
                "patient_name": patient_name,
                "patient_id": s.get("patient_id"),
                "sample_type": s.get("sample_type"),
                "llm": model,
            })

    results = run_parallel_jobs(jobs, workers=3)
    for res in results:
        print(f"Processed: {res}")
