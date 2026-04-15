import os
import re
import json
import uuid
import argparse
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
MAX_ACTIVE_SESSIONS = int(os.getenv("BROWSER_USE_MAX_SESSIONS", "250"))
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


def create_task(task_text: str, llm: str, max_steps: int, metadata: Optional[Dict[str, object]] = None) -> str:
    """Create and start a task and return task ID.

    metadata, when provided, is sent to Browser-Use Cloud so it
    is echoed back on subsequent task API responses (e.g. patient_id).
    """
    payload = {
        "task": task_text,
        "llm": llm,
        "thinking": True,
        "vision": True, 
        "maxSteps": max_steps,
        "allowedDomains": [BASE_URL.split("//", 1)[-1]]
    }
    if metadata:
        payload["metadata"] = metadata
    resp = _request_with_retries("POST", f"{API_BASE}/tasks", headers=_api_headers(), json=payload, timeout=30)
    # 202 Accepted on success
    if resp.status_code not in (200, 202):
        print(f"[create_task] {resp.status_code} response body: {resp.text[:500]}")
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
    }, stream=True)

    if resp.status_code == 404:
        return None

    resp.raise_for_status()

    filename = _filename_from_disposition(resp.headers.get("Content-Disposition")) or f"submission_{uuid.uuid4().hex}.json"

    content_type = (resp.headers.get("Content-Type") or "").lower()
    if "application/json" in content_type and "attachment" not in (resp.headers.get("Content-Disposition") or "").lower():
        try:
            body_json = resp.json()
        except ValueError:
            return None
        if body_json.get("file") is None:
            return None
    try:
        body = json.loads(resp.content.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    payload = body.get("payload")
    if payload is None:
        return None

    body["task_id"] = task_id
    body["patient_id"] = patient_id
    body["sample_type"] = sample_type
    body["llm"] = llm

    out_path = dest_dir / filename
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=2)

    # Attempt to delete the server-side submission using the filename
    try:
        delete_submission(session, base_url, filename)
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

def execute_one_patient(patient_name, patient_id, sample_type, llm, max_steps: int, output_dir: Path) -> Dict:
    prompt = f"""Visit the web app at {BASE_URL}. On the first log-in page, do user sign-in with username "user2" and password "pass789". 
    Then find the patient record for {patient_name} using the patient search function on the site, then fill out and submit a Pre-Authorization Form for this patient. 
    Verify all required fields and then directly submit. If you find any issues, immediately stop the process and report the issue.
    """
    task_metadata: Dict[str, object] = {
        "patient_id": patient_id,
        "patient_name": patient_name,
        "sample_type": sample_type,
        "max_steps": str(max_steps)
    }
    with _session_limit():
        task_id = create_task(task_text=prompt, llm=llm, max_steps= max_steps, metadata=task_metadata)
        final_task = wait_for_task(task_id)
    session = requests.Session()
    first, last = _split_name(patient_name)
    local_dir = output_dir
    saved_path = None
    for attempt in range(5):
        saved_path = get_submission_by_patient(session, BASE_URL, first, last, llm,
                                               patient_id, task_id, sample_type, local_dir)
        if saved_path is not None:
            break
        if attempt < 4:
            time.sleep(5 * (attempt + 1))
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

def run_parallel_jobs(jobs: List[Dict], workers: int, max_steps: int, output_dir: Path) -> List[Dict]:
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
            futures[pool.submit(execute_one_patient, patient_name, patient_id, sample_type, llm, max_steps, output_dir)] = (patient_name, llm)

        for fut in as_completed(futures):
            patient, llm = futures[fut]
            try:
                results.append(fut.result())
            except Exception as e:
                results.append({"patient": patient, "llm": llm, "error": str(e)})
    return results

def ablation_study_subset():
    summaries_path = Path(__file__).resolve().parents[2] / "data" / "results" / "non_submitted_summaries.json"
    with open(summaries_path, "r", encoding="utf-8") as f:
        summaries = json.load(f)
    return [d for d in summaries if "technical error" in d.get("issue_class", "").lower() and d.get("llm") == "gemini-flash-latest"]

if __name__ == "__main__":
    root_dir = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Run browser-automation submissions for selected patient samples")
    parser.add_argument("--input", default=str(root_dir / "data" / "initial" / "all_samples.json"), help="Input samples JSON path")
    parser.add_argument("--output-dir", default=str(root_dir / "data" / "gemini_flash_ablation"), help="Output directory for downloaded submissions")
    parser.add_argument("--sample-type", help="Sample type to process")
    parser.add_argument("--workers", type=int, default=50, help="Max concurrent workers")
    parser.add_argument("--llm", default="gemini-flash-latest", help="LLM model to run")
    parser.add_argument("--dedupe-by-name", action="store_true", default=True, help="Deduplicate jobs by patient full name")
    parser.add_argument("--max-steps", type=int, default=70, help="Maximum steps per browser task")
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # samples_path = Path(args.input)
    # with samples_path.open("r", encoding="utf-8") as f:
    #     samples = json.load(f)
    # sample_2a_indexes = [34, 36, 40, 41, 42, 44, 49, 50, 51, 52, 55, 236, 247, 259, 263, 266, 269, 275, 279, 282, 286, 296, 299, 309, 315]
    # sample_2a = [samples[i] for i in sample_2a_indexes]
    # sample_2b = samples[330:355]
    # sample_2c = samples[440:465]
    # sample_3b = samples[600:625]
    # sample_4 = samples[650:700]
    
    ablation_subset = ablation_study_subset()
    # unique_samples_by_name: Dict[str, Dict] = {}
    # for sample in ablation_subset:
    #     first = sample.get("patient_first_name", "")
    #     last = sample.get("patient_last_name", "")
    #     patient_name = f"{first} {last}".strip()
    #     if not patient_name:
    #         continue
    #     if patient_name not in unique_samples_by_name:
    #         unique_samples_by_name[patient_name] = sample
    # selected_samples = list(unique_samples_by_name.values())

    # print(
    #     f"Total sample_type={args.sample_type} profiles: {len(selected_samples)} | "
    #     f"unique patient names to process: {len(selected_samples)}"
    # )

    jobs: List[Dict] = []
    for s in ablation_subset[5:]:
        # first = s.get("patient_first_name", "")
        # last = s.get("patient_last_name", "")
        # patient_name = f"{first} {last}".strip()
        patient_name = s.get("patient_name")
        jobs.append({
            "patient_name": patient_name,
            "patient_id": s.get("patient_id"),
            "sample_type": s.get("sample_type"),
            "llm": args.llm,
        })

    results = run_parallel_jobs(jobs, workers=args.workers, max_steps=args.max_steps, output_dir=output_dir)
    for res in results:
        print(f"Processed: {res}")