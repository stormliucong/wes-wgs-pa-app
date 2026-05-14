"""
Automated PA form submission via Browser-Use Cloud API.

For each patient job, the script:
  1. Launches a Browser-Use Cloud task (an LLM-driven browser agent).
  2. The agent logs into the web app, searches for the patient, fills out and
     submits the Pre-Authorization form.
  3. After the task finishes, polls the web app's /download/patient endpoint
     to retrieve the saved submission JSON.
  4. Injects task metadata (task_id, patient_id, sample_type, llm) into the
     file and saves it locally, then deletes the server-side copy.

Multiple patients are processed concurrently via a ThreadPoolExecutor.
A semaphore bounds the number of simultaneous Browser-Use sessions.

Usage:
    python scripts/2_browser_automation/make_submissions.py [options]
"""

import json
import os
import random
import re
import time
import threading
import uuid
import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

# ── API credentials ───────────────────────────────────────────────────────────
load_dotenv()
_raw_api_key: Optional[str] = os.getenv("BROWSER_USE_API_KEY")
if not _raw_api_key or not _raw_api_key.strip():
    raise RuntimeError("BROWSER_USE_API_KEY not found in environment")
api_key: str = _raw_api_key.strip()

# ── Configuration ─────────────────────────────────────────────────────────────
BASE_URL = "https://wes-wgs-pa-app-u2c8s.ondigitalocean.app"
API_BASE = os.getenv("BROWSER_USE_API_BASE", "https://api.browser-use.com/api/v2").rstrip("/")

# Semaphore caps concurrent Browser-Use sessions to avoid hitting account limits
MAX_ACTIVE_SESSIONS = int(os.getenv("BROWSER_USE_MAX_SESSIONS", "250"))
_SESSION_SEMAPHORE = threading.Semaphore(MAX_ACTIVE_SESSIONS)

# ── HTTP utilities ────────────────────────────────────────────────────────────
def _api_headers() -> Dict[str, str]:
    return {
        "X-Browser-Use-API-Key": api_key,
        "Content-Type": "application/json",
    }

def _request_with_retries(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    json: Optional[Dict] = None,
    timeout: int = 30,
    max_retries: int = 5,
) -> requests.Response:
    """HTTP request with exponential back-off on 429 (rate-limit) and 5xx errors."""
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
            # Honour Retry-After if present, otherwise use back-off
            wait = backoff
            try:
                wait = float(resp.headers.get("Retry-After", backoff))
            except ValueError:
                pass
            time.sleep(wait + random.uniform(0.0, 0.5))
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
    """Acquire the session semaphore for the duration of a Browser-Use task."""
    _SESSION_SEMAPHORE.acquire()
    try:
        yield
    finally:
        _SESSION_SEMAPHORE.release()

# ── Browser-Use Cloud API ─────────────────────────────────────────────────────
def create_session(start_url: Optional[str] = None) -> str:
    """Create a Browser-Use session and return its ID."""
    payload = {"startUrl": start_url, "persistMemory": False, "keepAlive": False}
    resp = _request_with_retries("POST", f"{API_BASE}/sessions", headers=_api_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()["id"]

def create_task(task_text: str, llm: str, max_steps: int, metadata: Optional[Dict] = None) -> str:
    """Submit a task to Browser-Use Cloud and return its task ID.
    metadata is forwarded to the API and echoed back on subsequent GET /tasks
    responses — useful for correlating results with the originating patient record.
    """
    payload = {
        "task": task_text,
        "llm": llm,
        "thinking": True,
        "vision": True,
        "maxSteps": max_steps,
        # Restrict the agent to the target app domain
        "allowedDomains": [BASE_URL.split("//", 1)[-1]],
    }
    if metadata:
        payload["metadata"] = metadata

    resp = _request_with_retries("POST", f"{API_BASE}/tasks", headers=_api_headers(), json=payload)
    if resp.status_code not in (200, 202):
        print(f"[create_task] unexpected {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
    return resp.json()["id"]

def get_task(task_id: str) -> Dict:
    """Fetch the current state of a task."""
    resp = _request_with_retries("GET", f"{API_BASE}/tasks/{task_id}", headers=_api_headers(),
                                 timeout=60, max_retries=3)
    resp.raise_for_status()
    return resp.json()

def wait_for_task(task_id: str, poll_interval: float = 2.0, timeout_seconds: int = 600) -> Dict:
    """Poll until the task reaches a terminal state or the timeout expires."""
    deadline = time.time() + timeout_seconds
    last: Dict = {}
    while time.time() < deadline:
        try:
            last = get_task(task_id)
            if (last.get("status") or "").lower() in {"finished", "stopped"}:
                return last
        except requests.RequestException:
            pass
        time.sleep(poll_interval)
    return last

# ── App submission download helpers ───────────────────────────────────────────
def _split_name(full_name: str) -> Tuple[str, str]:
    parts = [p for p in (full_name or "").strip().split() if p]
    if not parts:
        return "", ""
    return (parts[0], "") if len(parts) == 1 else (parts[0], parts[-1])

def _filename_from_disposition(disposition: Optional[str]) -> Optional[str]:
    """Extract filename from a Content-Disposition header, if present."""
    if not disposition:
        return None
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', disposition)
    return m.group(1).strip() if m else None

def get_submission_by_patient(
    session: requests.Session,
    base_url: str,
    first_name: str,
    last_name: str,
    llm: str,
    patient_id: str,
    task_id: str,
    sample_type: str,
    dest_dir: Path,
) -> Optional[Path]:
    """Download the PA submission for a patient from the web app.

    Returns the local path where the file was saved, or None if the
    submission is not yet available (404) or the response has no payload.
    After saving, the server-side copy is deleted to prevent stale results
    from being picked up by future runs.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    resp = session.post(
        f"{base_url}/download/patient",
        json={"patient_first_name": first_name, "patient_last_name": last_name},
        stream=True,
    )

    if resp.status_code == 404:
        return None
    resp.raise_for_status()

    filename = (
        _filename_from_disposition(resp.headers.get("Content-Disposition"))
        or f"submission_{uuid.uuid4().hex}.json"
    )

    # A JSON response without an attachment header means no file is ready
    content_type = (resp.headers.get("Content-Type") or "").lower()
    if "application/json" in content_type and "attachment" not in (resp.headers.get("Content-Disposition") or "").lower():
        try:
            if resp.json().get("file") is None:
                return None
        except ValueError:
            return None

    try:
        body = json.loads(resp.content.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    if body.get("payload") is None:
        return None

    # Inject task metadata so the saved file is self-contained for analysis
    body["task_id"] = task_id
    body["patient_id"] = patient_id
    body["sample_type"] = sample_type
    body["llm"] = llm

    out_path = dest_dir / filename
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=2)

    try:
        delete_submission(session, base_url, filename)
    except Exception:
        pass

    return out_path

def delete_submission(session: requests.Session, base_url: str, filename: str) -> None:
    """Remove a submission file from the web app server."""
    resp = session.post(f"{base_url}/delete", json={"filename": filename})
    if resp.status_code != 200:
        raise RuntimeError(f"Delete failed for {filename}: {resp.status_code} {resp.text}")
    try:
        body = resp.json()
    except Exception:
        body = {}
    if not body.get("ok", False):
        raise RuntimeError(f"Delete failed for {filename}: {body}")


# ── Job orchestration ─────────────────────────────────────────────────────────
def execute_one_patient(
    patient_name: str,
    patient_id: str,
    sample_type: str,
    llm: str,
    max_steps: int,
    output_dir: Path,
) -> Dict:
    """Run the full submission pipeline for a single patient.

    Launches a Browser-Use task, waits for completion, then polls the web app
    for the saved submission. Polling retries with increasing delays because the
    server may take several seconds to persist the file after the agent finishes.
    """
    prompt = (
        f'Visit the web app at {BASE_URL}. On the first log-in page, sign in with '
        f'username "user2" and password "pass789". '
        f"Find the patient record for {patient_name} using the patient search function, "
        f"then fill out and submit a Pre-Authorization Form for this patient. "
        f"Verify all required fields before submitting. "
        f"If you find any issues, immediately stop and report them."
    )
    task_metadata: Dict[str, object] = {
        "patient_id": patient_id,
        "patient_name": patient_name,
        "sample_type": sample_type,
        "max_steps": str(max_steps),
    }

    with _session_limit():
        task_id = create_task(task_text=prompt, llm=llm, max_steps=max_steps, metadata=task_metadata)
        final_task = wait_for_task(task_id)

    task_status = (final_task.get("status") or "").lower()
    if task_status == "stopped":
        print(f"[{patient_name}] task {task_id} stopped early — skipping download")
        return {"patient": patient_name, "task_id": task_id, "filename": None, "saved_path": None, "llm": llm}

    # Give the server time to persist the submission before polling begins
    time.sleep(10)

    http_session = requests.Session()
    first, last = _split_name(patient_name)
    saved_path = None
    for attempt in range(8):
        saved_path = get_submission_by_patient(
            http_session, BASE_URL, first, last, llm,
            patient_id, task_id, sample_type, output_dir,
        )
        if saved_path is not None:
            break
        if attempt < 7:
            time.sleep(10 * (attempt + 1))

    return {
        "patient": patient_name,
        "task_id": task_id,
        "filename": saved_path.name if saved_path else None,
        "saved_path": str(saved_path) if saved_path else None,
        "llm": llm,
    }


def run_parallel_jobs(jobs: List[Dict], workers: int, max_steps: int, output_dir: Path) -> List[Dict]:
    """Process a list of patient jobs concurrently.

    Each job dict must contain: patient_name, patient_id, sample_type, llm.
    Worker count is capped at MAX_ACTIVE_SESSIONS to avoid semaphore deadlock.
    """
    results: List[Dict] = []
    if MAX_ACTIVE_SESSIONS > 0:
        workers = max(1, min(workers, MAX_ACTIVE_SESSIONS))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                execute_one_patient,
                job["patient_name"], job["patient_id"],
                job["sample_type"], job["llm"],
                max_steps, output_dir,
            ): (job["patient_name"], job["llm"])
            for job in jobs
        }
        for fut in as_completed(futures):
            patient, llm = futures[fut]
            try:
                results.append(fut.result())
            except Exception as e:
                results.append({"patient": patient, "llm": llm, "error": str(e)})

    return results

# ── Data loading ──────────────────────────────────────────────────────────────

def load_ablation_subset() -> List[Dict]:
    """Return gemini-flash-latest records that failed with a technical error.

    These are sourced from non_submitted_summaries.json and form the retry
    cohort for the ablation study.
    """
    path = Path(__file__).resolve().parents[2] / "data" / "results" / "non_submitted_summaries.json"
    with path.open("r", encoding="utf-8") as f:
        summaries = json.load(f)
    return [
        d for d in summaries
        if "technical error" in d.get("issue_class", "").lower()
        and d.get("llm") == "gemini-flash-latest"
    ]

 
# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root_dir = Path(__file__).resolve().parents[2]

    parser = argparse.ArgumentParser(
        description="Run browser-automation PA submissions for selected patient samples.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
modes:
  primary   Run all samples from --input, optionally filtered by --sample-type.
            Each LLM has its own output directory (e.g. data/gemini_flash).

  ablation  Retry the gemini-flash-latest technical-error cases from the primary
            experiment with a different --max-steps value. Used to study how step
            budget affects task completion.

examples:
  # Primary run with Gemini Flash
  python make_submissions.py --mode primary --llm gemini-flash-latest --output-dir data/gemini_flash

  # Primary run filtered to one sample type
  python make_submissions.py --mode primary --llm gemini-3-pro-preview --sample-type 2a --output-dir data/gemini_pro

  # Ablation run at max_steps=55
  python make_submissions.py --mode ablation --max-steps 55 --output-dir data/ablation_55
        """,
    )
    parser.add_argument("--mode", choices=["primary", "ablation_1", "ablation_3"], default="primary",
                        help="Experiment mode (default: primary)")
    parser.add_argument("--llm", default="gemini-flash-latest",
                        help="LLM model identifier: gemini-flash-latest | gemini-3-pro-preview | claude-opus-4-5-20251101")
    parser.add_argument("--input", default=str(root_dir / "data" / "patient_data" / "all_samples.json"),
                        help="[primary] Path to all_samples.json")
    parser.add_argument("--sample-type", default=None,
                        help="[primary] Filter to a specific sample type (e.g. 1, 2a, 3b)")
    parser.add_argument("--output-dir", default=str(root_dir / "data" / "gemini_flash"),
                        help="Directory where downloaded submission files are saved")
    parser.add_argument("--workers", type=int, default=50,
                        help="Max concurrent worker threads")
    parser.add_argument("--max-steps", type=int, default=40,
                        help="Maximum browser steps allowed per task")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "primary":
        with Path(args.input).open("r", encoding="utf-8") as f:
            patient_data: List[Dict] = json.load(f)
        if args.sample_type:
            patient_data = [s for s in patient_data if s.get("sample_type") == args.sample_type]
        jobs: List[Dict] = [
            {
                "patient_name": s["patient_name"],
                "patient_id":   s["patient_id"],
                "sample_type":  s.get("sample_type"),
                "llm":          args.llm,
            }
            for s in patient_data
        ]

    else:  # ablation
        subset = load_ablation_subset()
        jobs = [
            {
                "patient_name": s["patient_name"],
                "patient_id":   s.get("patient_id"),
                "sample_type":  s.get("sample_type"),
                "llm":          args.llm,
            }
            for s in subset
        ]

    print(f"Mode: {args.mode} | Jobs: {len(jobs)} | Model: {args.llm} | max_steps: {args.max_steps}")
    results = run_parallel_jobs(jobs, workers=args.workers, max_steps=args.max_steps, output_dir=output_dir)
    for res in results:
        print(f"  {res}")
