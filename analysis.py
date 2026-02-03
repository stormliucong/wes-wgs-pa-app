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
import pytz
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

API_BASE = "https://api.browser-use.com/api/v2/tasks"

def _api_headers() -> Dict[str, str]:
    return {
        "X-Browser-Use-API-Key": api_key,
    }

def get_task(task_id: str) -> Dict:
    resp = requests.get(f"{API_BASE}/tasks/{task_id}", headers=_api_headers(), timeout=60)
    resp.raise_for_status()
    return resp.json()

def get_tasks(start_et: str, end_et: str):
    """
    Fetches all tasks from Browser Use Cloud within a given Eastern Time range.

    Args:
        start_et: start time in ET as ISO string e.g. "2026-01-01T08:00:00"
        end_et:   end time in ET as ISO string e.g. "2026-01-01T12:00:00"

    Returns:
        List of dicts with keys: id, llm, startedAt, finishedAt, isSuccess, cost
    """

    # Convert ET to UTC
    et_zone = pytz.timezone("US/Eastern")
    utc_zone = pytz.utc

    start_dt = et_zone.localize(datetime.fromisoformat(start_et)).astimezone(utc_zone)
    end_dt   = et_zone.localize(datetime.fromisoformat(end_et)).astimezone(utc_zone)

    # ISO 8601 strings required by API (ending with "Z" for UTC)
    after_utc  = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    before_utc = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    tasks_out = []
    page = 1
    page_size = 100  # maximum allowed

    while True:
        params = {
            "after": after_utc,
            "before": before_utc,
            "pageSize": page_size,
            "pageNumber": page
        }

        resp = requests.get(API_BASE, headers=_api_headers(), params=params)
        resp.raise_for_status()
        data = resp.json()

        items = data.get("items", [])
        if not items:
            break

        # Extract & shape required attributes
        for task in items:
            tasks_out.append({
                "id": task.get("id"),
                "llm": task.get("llm"),
                "startedAt": task.get("startedAt"),
                "finishedAt": task.get("finishedAt"),
                "isSuccess": task.get("isSuccess"),
                "output": task.get("output"),
                "judgement": task.get("judgement"),
                # cost may be in metadata or through SDK extension
                # if present in response, include; else None
                "cost": task.get("cost")
            })

        # break if we've reached total pages
        if len(items) < page_size:
            break
        page += 1
        
        results_dir = Path("data/results")
        results_dir.mkdir(parents=True, exist_ok=True)

    return tasks_out

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
    
    summary = {
        "task_id": submission.get("task_id", ""),
        "llm": submission.get("llm", ""),
        "sample_type": submission.get("sample_type", ""),
        "submitted": True,
        "confusion_label": "",
        "num_incorrect": 0,
        "num_missing": 0,
        "incorrect_fields": {},
        "missing_fields":[],
        "accurate": False
    }

    if submission.get("sample_type") in {"2d", "2e", "3b"}:  
        summary["confusion_label"] = "FP" 
        return summary

    for key in payload:
        if key not in groundtruth:
            continue
        payload_value = payload.get(key)
        groundtruth_value = groundtruth.get(key)
        if not _equal(key, payload_value, groundtruth_value) and payload_value not in (None, "", [], {}):
            check_result[key] = {"Expected": groundtruth_value, "Got": payload_value}
        else:
            check_result[key] = "Correct"

    summary["incorrect_fields"] = {k: v for k, v in check_result.items() if v != "Correct"}
    summary["num_incorrect"] = len(summary["incorrect_fields"])
    summary["missing_fields"] = [k for k, v in payload.items() if v in (None, "", [], {})]
    summary["num_missing"] = len(summary["missing_fields"])
    summary["accurate"] = len(summary["incorrect_fields"]) == 0
    summary["confusion_label"] = "TP"
    return summary

def check_non_submitted(task_list: List[Dict]) -> List[Dict]:
    
    non_submitted_tasks = [t for t in task_list if t.get("isSuccess") is False]
    summary = {
        "task_id": "",
        "llm": "",
        "sample_type": "",
        "submitted": False,
        "confusion_label": "",
        "num_incorrect": 0,
        "num_missing": 0,
        "incorrect_fields": {},
        "missing_fields":[],
        "accurate": False
    }
    return non_submitted_tasks

def summarize_table(submitted, non_submitted) -> pd.DataFrame:
    """Convert a list of summary dicts into a pandas DataFrame, sorted by LLM then sample type."""
    rows = []
    for r in submitted + non_submitted:
        row = dict(r or {})
        rows.append(row)
    df = pd.DataFrame(rows)
    if not df.empty:
        sort_cols = [c for c in ["llm", "sample_type"] if c in df.columns]
        if sort_cols:
            df = df.sort_values(by=sort_cols, kind="stable", na_position="last", ignore_index=True)
    return df

if __name__ == "__main__":   
    # gt_path = Path("groundtruth.json")
    # with gt_path.open("r", encoding="utf-8") as f:
    #     groundtruths = json.load(f)
    # indexed_groundtruths = indexed_gt(groundtruths)
    # summaries = []

    # submission_path = Path("data/submissions")
    # for submission_file in submission_path.glob("*.json"):
    #     with submission_file.open("r", encoding="utf-8") as f:
    #         submission = json.load(f)
        
    #     patient_id = submission.get("patient_id")
    #     if not patient_id:
    #         print(f"Submission {submission_file} missing patient_id")
    #         continue
        
    #     groundtruth = indexed_groundtruths.get(patient_id)
    #     if not groundtruth:
    #         print(f"No groundtruth found for patient_id {patient_id} in submission {submission_file}")
    #         continue
        
    #     summary = check_submission(submission, groundtruth)
    #     summaries.append(summary)
        
    # summary_table = summarize_table(summaries)
    # results_dir = Path("data/results")
    # results_dir.mkdir(parents=True, exist_ok=True)
    # output_path: Path = results_dir / "summary.xlsx"
    # summary_table.to_excel(output_path, index=False)

    start_et = "2026-01-28T00:00:00"
    end_et = "2026-01-29T16:00:00"
    tasks = get_tasks_between_et(start_et, end_et)
    with (Path("data/results") / "all_tasks.json").open("w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)

    print(f"Fetched {len(tasks)} tasks between {start_et} ET and {end_et} ET")