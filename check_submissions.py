"""Check the submission files against the groundtruth files
- Directly compare the submission payload with the groundtruth payload for each sample type 
(1, 2a, 2b, 2c, 3a, 3c)
"""

from typing import List, Dict, Optional, Tuple
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd
import os
import requests
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None
from dotenv import load_dotenv



# ---------------- Browser-Use Cloud helpers ----------------
load_dotenv()
raw_api_key: Optional[str] = os.getenv("BROWSER_USE_API_KEY")
if raw_api_key is None or not raw_api_key.strip():
    raise RuntimeError("BROWSER_USE_API_KEY not found in environment")
api_key: str = raw_api_key.strip()

API_BASE = os.getenv("BROWSER_USE_API_BASE", "https://api.browser-use.com/api/v2").rstrip("/")

def _api_headers() -> Dict[str, str]:
    return {
        "X-Browser-Use-API-Key": api_key,
        "Content-Type": "application/json",
    }

def get_task(task_id: str) -> Dict:
    resp = requests.get(f"{API_BASE}/tasks/{task_id}", headers=_api_headers(), timeout=60)
    resp.raise_for_status()
    return resp.json()

def _parse_iso_dt(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO8601 datetime string into an aware datetime.
    Supports trailing 'Z' for UTC and fills naive datetimes as UTC.
    """
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def calc_duration_seconds(started_at: Optional[str], finished_at: Optional[str]) -> Optional[int]:
    """Return duration in seconds between started_at and finished_at ISO timestamps.
    Returns None if either timestamp is missing or unparsable.
    """
    st = _parse_iso_dt(started_at)
    fn = _parse_iso_dt(finished_at)
    if not st or not fn:
        return None
    try:
        return max(int((fn.astimezone(timezone.utc) - st.astimezone(timezone.utc)).total_seconds()), 0)
    except Exception:
        return None

def _eastern_window_utc(date_str: str, start_hour: int = 12, end_hour: int = 15) -> Tuple[datetime, datetime]:
    eastern = ZoneInfo("America/New_York") if ZoneInfo else timezone(timedelta(hours=-5))
    base_date = datetime.strptime(date_str, "%Y-%m-%d")
    start_et = base_date.replace(hour=start_hour, minute=0, second=0, microsecond=0, tzinfo=eastern)
    end_et = base_date.replace(hour=end_hour, minute=0, second=0, microsecond=0, tzinfo=eastern)
    return start_et.astimezone(timezone.utc), end_et.astimezone(timezone.utc)

 
    
def _to_utc_iso(dt_or_str: Optional[object]) -> Optional[str]:
    """Convert a datetime or string to UTC ISO8601 with Z. Strings without tz are assumed ET."""
    if dt_or_str is None:
        return None
    eastern = ZoneInfo("America/New_York") if ZoneInfo else timezone(timedelta(hours=-5))
    try:
        if isinstance(dt_or_str, datetime):
            dt = dt_or_str
        else:
            dt = datetime.fromisoformat(str(dt_or_str))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=eastern)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None

def list_tasks(
    after: Optional[object] = None,
    before: Optional[object] = None,
    status: Optional[str] = None,
    session_id: Optional[str] = None,
    page_size: int = 100,
    page_number: int = 1,
) -> List[Dict]:
    """List tasks from Browser-Use Cloud.
    - after/before: datetime or ISO string in Eastern (if naive) or with tz; converted to UTC per API
    - status: one of created|started|finished|stopped (maps to filterBy)
    Returns a normalized list of dicts with keys: task_id, llm, duration, cost, isSuccess, startedAt, finishedAt, status.
    """
    params: Dict[str, str] = {
        "pageSize": str(max(1, min(int(page_size), 100))),
        "pageNumber": str(max(1, int(page_number))),
    }
    if status:
        params["filterBy"] = str(status).lower()
    if session_id:
        params["sessionId"] = session_id
    after_iso = _to_utc_iso(after)
    before_iso = _to_utc_iso(before)
    if after_iso:
        params["after"] = after_iso
    if before_iso:
        params["before"] = before_iso

    resp = requests.get(f"{API_BASE}/tasks", headers=_api_headers(), params=params, timeout=60)
    resp.raise_for_status()
    body = resp.json() or {}
    items = []
    if isinstance(body, dict):
        items = body.get("items") or []
    elif isinstance(body, list):
        items = body

    results: List[Dict] = []
    for t in items:
        started = t.get("startedAt")
        finished = t.get("finishedAt")
        results.append({
            "task_id": t.get("id") or t.get("taskId"),
            "llm": t.get("llm"),
            "duration": calc_duration_seconds(started, finished),
            "cost": t.get("cost"),
            "isSuccess": t.get("isSuccess"),
            "status": t.get("status"),
            "startedAt": started,
            "finishedAt": finished,
        })
    return results

def summarize_tasks(date_str: str, start_hour, end_hour):
    """Summarize tasks started between 12pm–3pm Eastern on date_str (YYYY-MM-DD).
    Returns a pandas DataFrame with columns: task_id, llm, duration, cost, steps, isSuccess
    """
    rows: List[Dict] = []
    tasks = list_tasks(date_str, start_hour, end_hour)
    for t in tasks:
        tid = t.get("id") or t.get("taskId")
        started = t.get("startedAt") or t.get("createdAt")
        finished = t.get("finishedAt")
        llm = t.get("llm")
        cost = t.get("cost")
        steps_list = t.get("steps") or t.get("actions") or []
        steps = len(steps_list) if isinstance(steps_list, list) else t.get("totalSteps")
        is_success = t.get("isSuccess")
        duration = calc_duration_seconds(started, finished)
        rows.append({
            "task_id": tid,
            "llm": llm,
            "duration": duration,
            "cost": cost,
            "steps": steps,
            "isSuccess": is_success,
        })

# summarize_tasks no longer required; list_tasks returns normalized fields directly

def indexed_gt(groundtruths: List[Dict]) -> Dict:
    indexed = {}
    for profile in groundtruths:
        patient_id = profile.get("patient_id")
        indexed[patient_id] = profile
    return indexed

def check_submission(submission: Dict, groundtruth: Dict):
    """Check if the submission matches the groundtruth"""
    payload = submission.get("payload", {})
    check_result = {}

    def _digits_only(value) -> str:
        s = value
        if isinstance(value, list):
            s = value[0] if value else ""
        return "".join(ch for ch in str(s) if ch.isdigit())

    def _norm_str(value) -> str:
        return str(value).strip().lower()

    def _equal(key: str, a, b) -> bool:
        """Flexible, case-insensitive equality.
        - For member_id: compare digits-only, ignoring any prefixes
        - If one side is a single-item list and the other is a string, compare the string values
        - Lists of strings: element-wise case-insensitive comparison
        - Fallback: direct equality
        """
        if key == "member_id":
            return _digits_only(a) == _digits_only(b)

        # Handle single-item list vs string
        if isinstance(a, list) and not isinstance(b, list):
            if len(a) == 1 and isinstance(a[0], (str, int, float)) and isinstance(b, (str, int, float)):
                return _norm_str(a[0]) == _norm_str(b)
        if isinstance(b, list) and not isinstance(a, list):
            if len(b) == 1 and isinstance(b[0], (str, int, float)) and isinstance(a, (str, int, float)):
                return _norm_str(b[0]) == _norm_str(a)

        # Strings
        if isinstance(a, str) and isinstance(b, str):
            return _norm_str(a) == _norm_str(b)

        # Lists of strings
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                return False
            na = [_norm_str(x) for x in a]
            nb = [_norm_str(x) for x in b]
            return na == nb

        # Fallback
        return a == b
    for key in payload:
        if key not in groundtruth:
            continue
        payload_value = payload.get(key)
        groundtruth_value = groundtruth.get(key)
        if not _equal(key, payload_value, groundtruth_value):
            check_result[key] = {"Expected": groundtruth_value, "Got": payload_value}
        else:
            check_result[key] = "Correct"

    report = {
        "patient_id": submission.get("patient_id", ""),
        "sample_type": submission.get("sample_type", ""),
        "llm": submission.get("llm", ""),
        "duration": submission.get("duration", 0),
        "check_result": check_result}
    
    return report

def summarize_reports(reports: List[Dict]):
    """Convert a list of report dictionaries into a pandas DataFrame.
    - If items contain a 'check_result' dict, compute num_correct/num_incorrect and return
      columns: llm, sample_type, duration, num_correct, num_incorrect.
    - Otherwise, assume items are already summary dictionaries and return DataFrame directly.
    """
    if not reports:
        return pd.DataFrame()

    first = reports[0] or {}
    if isinstance(first.get("check_result"), dict):
        rows = []
        for r in reports:
            res = (r or {}).get("check_result", {}) or {}
            num_correct = sum(1 for v in res.values() if v == "Correct")
            num_incorrect = sum(1 for v in res.values() if v != "Correct")
            rows.append({
                "llm": r.get("llm", ""),
                "sample_type": r.get("sample_type", ""),
                "duration": r.get("duration"),
                "num_correct": num_correct,
                "num_incorrect": num_incorrect,
            })
        return pd.DataFrame(rows)

    # Already summarized dictionaries; return as-is
    return pd.DataFrame(reports)

if __name__ == "__main__":   
    gt_path = Path("groundtruth.json")
    with gt_path.open("r", encoding="utf-8") as f:
        groundtruths = json.load(f)
    indexed_groundtruths = indexed_gt(groundtruths)
    check_reports = []

    submission_path = Path("data/submissions")
    for submission_file in submission_path.glob("*.json"):
        with submission_file.open("r", encoding="utf-8") as f:
            submission = json.load(f)
        
        patient_id = submission.get("patient_id")
        if not patient_id:
            print(f"Submission {submission_file} missing patient_id")
            continue
        
        groundtruth = indexed_groundtruths.get(patient_id)
        if not groundtruth:
            print(f"No groundtruth found for patient_id {patient_id} in submission {submission_file}")
            continue
        
        report = check_submission(submission, groundtruth)
        print(f"Report for {submission_file}: {report}")
        check_reports.append(report)
        
    # Write compact JSON so inner objects (e.g., check_result entries) appear on one line
    with open("check_reports.json", "w", encoding="utf-8") as f:
        json.dump(check_reports, f, indent=2)