"""
Evaluation pipeline for the main experiment.

Compares submitted forms against ground truth field-by-field and classifies
tasks that did not result in a submission. Outputs a multi-sheet Excel workbook.

Pipeline (run via __main__):
  1. Fetch completed tasks from the Browser-Use Cloud API within a time window.
  2. Evaluate submitted forms against per-patient ground truth records.
  3. Classify non-submitted tasks (technical error / correct withholding /
     over-refusal / inference failure) using a GPT batch job.
  4. Compute field-level accuracy tables.
  5. Write all results to summary.xlsx.
"""

import argparse
import importlib.util
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pytz
import requests
from dotenv import load_dotenv

# ── Setup ─────────────────────────────────────────────────────────────────────

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# `process_batch` and `extract_output` live in a sibling directory whose name
# starts with a digit (not a valid Python identifier), so importlib is required.
def _load_module_from_path(module_name: str, rel_path: str):
    path = Path(__file__).resolve().parent.parent / rel_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None, f"Cannot load module from {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod

_profile_gen   = _load_module_from_path("generate_unstructured_profiles",
                                         "1_data_generation/generate_unstructured_profiles.py")
process_batch  = _profile_gen.process_batch   # uploads a JSONL file and submits an OpenAI batch job
extract_output = _profile_gen.extract_output  # parses batch output lines into a list of strings


# ── Browser-Use Cloud API ─────────────────────────────────────────────────────

API_BASE = "https://api.browser-use.com/api/v2/tasks"

# Cost per browser step, used to back-calculate step count from task cost
MODEL_COST_PER_STEP: Dict[str, float] = {
    "claude-opus-4-5-20251101": 0.1,
    "claude-sonnet-4-6":        0.05,
    "gemini-3-pro-preview":     0.03,
    "o3":                       0.03,
    "gemini-flash-latest":      0.006,
}

def _api_headers() -> Dict[str, str]:
    key = os.getenv("BROWSER_USE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("BROWSER_USE_API_KEY not found in environment")
    return {"X-Browser-Use-API-Key": key}


def get_task(task_id: str) -> Dict:
    resp = requests.get(f"{API_BASE}/{task_id}", headers=_api_headers(), timeout=60)
    resp.raise_for_status()
    return resp.json()


def get_tasks(start_et: str, end_et: str, output_path: Optional[Path] = None) -> List[Dict]:
    """Fetch all tasks within an Eastern Time window from the Browser-Use Cloud API.

    Results are merged (by task ID) with any existing tasks already saved to
    output_path so the local cache stays up to date across runs.

    Args:
        start_et: Start time in ET, e.g. "2026-01-01T08:00:00"
        end_et:   End time in ET, e.g.   "2026-01-01T12:00:00"
    """
    et_zone = pytz.timezone("US/Eastern")
    utc_zone = pytz.utc
    start_utc = et_zone.localize(datetime.fromisoformat(start_et)).astimezone(utc_zone)
    end_utc   = et_zone.localize(datetime.fromisoformat(end_et)).astimezone(utc_zone)

    after_utc  = start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    before_utc = end_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    tasks_out = []
    page, page_size = 1, 100
    while True:
        resp = requests.get(API_BASE, headers=_api_headers(),
                            params={"after": after_utc, "before": before_utc,
                                    "pageSize": page_size, "pageNumber": page})
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            break
        for task in items:
            tasks_out.append({
                "id":          task.get("id"),
                "llm":         task.get("llm"),
                "startedAt":   task.get("startedAt"),
                "finishedAt":  task.get("finishedAt"),
                "isSuccess":   task.get("isSuccess"),
                "output":      task.get("output"),
                "judgement":   task.get("judgement"),
                "cost":        task.get("cost"),
                "metadata":    task.get("metadata", {}),
            })
        if len(items) < page_size:
            break
        page += 1

    # Merge fetched tasks with the cached file (newer fetch wins on conflict)
    try:
        results_dir = Path(__file__).resolve().parents[2] / "data" / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        cache_path = output_path or results_dir / "all_tasks.json"
        existing: List[Dict] = []
        if cache_path.exists():
            with cache_path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                existing = loaded
        merged = {str(t.get("id", "")).strip(): t for t in existing}
        merged.update({str(t.get("id", "")).strip(): t for t in tasks_out if t.get("id")})
        with cache_path.open("w", encoding="utf-8") as f:
            json.dump(list(merged.values()), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Failed to write tasks cache: %s", e)

    return tasks_out


def get_tasks_steps(tasks: List[Dict]) -> Dict[str, Optional[int]]:
    """Return task_id → estimated step count for a list of tasks.

    Step count is back-calculated from task cost divided by the known
    per-step cost for the model, since the API does not expose it directly in the previous step.
    """
    def _to_float(v) -> Optional[float]:
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    result: Dict[str, Optional[int]] = {}
    for task in tasks:
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id:
            continue
        cost = _to_float(task.get("cost"))
        cost_per_step = MODEL_COST_PER_STEP.get(task.get("llm", ""))
        if cost is not None and cost_per_step:
            result[task_id] = max(0, int(round(cost / cost_per_step)))
        else:
            result[task_id] = None
    return result


# ── Submission evaluation ─────────────────────────────────────────────────────

def _index_by_patient_id(records: List[Dict]) -> Dict[str, Dict]:
    return {str(r["patient_id"]): r for r in records if r.get("patient_id") is not None}


def check_submitted(submission: Dict, groundtruth: Dict) -> Dict:
    """Compare a submitted form payload against the ground truth record.

    Returns a summary dict with per-field correctness (1 = correct,
    dict with Expected/Got = incorrect) plus aggregate counts.
    """
    payload = submission.get("payload", {})

    # ── Field normalizers ──────────────────────────────────────────────────────
    def _digits_only(value) -> str:
        s = value[0] if isinstance(value, list) and value else value
        return "".join(ch for ch in str(s) if ch.isdigit())

    def _alphanumeric_only(value) -> str:
        s = value[0] if isinstance(value, list) and value else value
        return "".join(ch for ch in str(s) if ch.isalnum())

    def _norm_str(value) -> str:
        return str(value).strip().lower()

    def _to_list(value) -> List:
        if value is None:
            return []
        return value if isinstance(value, list) else [value]

    def _cpt_counter(value) -> Dict[str, int]:
        """Count occurrences of CPT codes 81415/81416, respecting multipliers like 81416x2."""
        counter: Dict[str, int] = {"81415": 0, "81416": 0}
        for item in _to_list(value):
            for part in re.split(r"[,;]", str(item)):
                token = re.sub(r"\s+", "", part.strip().lower())
                token = token.replace("×", "x").replace("✕", "x").replace("✖", "x")
                for code in ("81415", "81416"):
                    if code not in token:
                        continue
                    multiplier = 1
                    trailing = re.search(rf"{code}(?:\((?:x)?(\d+)\)|[x\*](\d+))", token)
                    if trailing:
                        multiplier = int(trailing.group(1) or trailing.group(2) or 1)
                    else:
                        leading = re.search(rf"(\d+)[x\*]{code}", token)
                        if leading:
                            multiplier = int(leading.group(1))
                    counter[code] += max(1, multiplier)
        return counter

    def _cpt_correctness(a, b) -> Tuple[bool, bool]:
        return a == b, _cpt_counter(a) == _cpt_counter(b)

    def _equal(key: str, a, b) -> bool:
        """Flexible, type-aware equality for form fields."""
        if key in {"member_id", "provider_phone", "provider_fax"}:
            return _digits_only(a) == _digits_only(b)
        if key in {"patient_address", "provider_address", "lab_address"}:
            return _alphanumeric_only(a) == _alphanumeric_only(b)
        if key == "icd_codes":
            return {_norm_str(x) for x in a} == {_norm_str(x) for x in b}
        if key == "cpt_codes":
            _, semantic = _cpt_correctness(a, b)
            return semantic
        # Handle single-item list vs scalar
        if isinstance(a, list) and not isinstance(b, list) and len(a) == 1:
            return _norm_str(a[0]) == _norm_str(b)
        if isinstance(b, list) and not isinstance(a, list) and len(b) == 1:
            return _norm_str(b[0]) == _norm_str(a)
        if isinstance(a, str) and isinstance(b, str):
            return _norm_str(a) == _norm_str(b)
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and [_norm_str(x) for x in a] == [_norm_str(x) for x in b]
        return a == b

    # ── Build per-field summary ────────────────────────────────────────────────
    summary: Dict = {
        "task_id":        submission.get("task_id", ""),
        "llm":            submission.get("llm", ""),
        "sample_type":    submission.get("sample_type", ""),
        "patient_name":   f"{payload.get('patient_first_name', '')} {payload.get('patient_last_name', '')}".strip(),
        "submitted":      True,
        "num_incorrect":  0,
        "num_missing":    0,
        "incorrect_fields": {},
        "missing_fields": [],
    }

    for key in payload:
        if key not in groundtruth:
            continue
        payload_val = payload[key]
        gt_val      = groundtruth[key]

        if key == "cpt_codes":
            exact, semantic = _cpt_correctness(payload_val, gt_val)
            summary["cpt_codes_exact"]    = 1 if exact    else {"Expected": gt_val, "Got": payload_val}
            summary["cpt_codes_semantic"] = 1 if semantic else {"Expected": gt_val, "Got": payload_val}

        if not _equal(key, payload_val, gt_val) and payload_val not in (None, "", [], {}):
            summary[key] = {"Expected": gt_val, "Got": payload_val}
        else:
            summary[key] = 1

    summary["incorrect_fields"]  = {k: v for k, v in summary.items() if v != 1 and k in payload}
    summary["num_incorrect"]     = len(summary["incorrect_fields"])
    summary["missing_fields"]    = [k for k, v in payload.items() if v in (None, "", [], {})]
    summary["num_missing"]       = len(summary["missing_fields"])
    summary["confusion_label"]   = "TP" if submission.get("sample_type") in {"1", "3a"} else "FP"
    return summary


def get_submitted_summaries(groundtruth_path: Path, submissions_dir: Path,
                            output_path: Optional[Path] = None) -> List[Dict]:
    """Evaluate all submission JSON files in submissions_dir against ground truth.

    Writes results to output_path (appended/deduplicated by task_id) if provided.
    """
    with groundtruth_path.open("r", encoding="utf-8") as f:
        groundtruths = _index_by_patient_id(json.load(f))

    summaries = []
    for submission_file in submissions_dir.glob("*.json"):
        with submission_file.open("r", encoding="utf-8") as f:
            submission = json.load(f)
        patient_id = submission.get("patient_id")
        if not patient_id:
            logger.warning("Submission %s missing patient_id — skipped", submission_file.name)
            continue
        groundtruth = groundtruths.get(patient_id)
        if not groundtruth:
            logger.warning("No ground truth for patient_id %s — skipped", patient_id)
            continue
        summaries.append(check_submitted(submission, groundtruth))

    if output_path:
        _upsert_json(output_path, summaries, key="task_id")
    return summaries


# ── Non-submitted task classification ─────────────────────────────────────────

# GPT classifies each failed task into one of four categories.
_NON_SUBMITTED_CLASSIFICATION_PROMPT = """\
You will be given an AI agent's final output message after it failed to submit a \
pre-authorization webform for Whole Exome Sequencing (WES) or Whole Genome Sequencing (WGS). \
Your task is to classify the reason for non-submission into exactly one of the categories below.

1) Technical Error: the submission process terminated prematurely due to system-level or platform \
constraints. Examples: maximum step limit reached, browser refresh or session timeout, page \
navigation failure, API or network error.

2) Correct Withholding Decision: the agent appropriately refused to submit because it identified \
an intentionally designed issue:
    a) Subscriber DOB Error (Type 2a): subscriber is only 10–12 years older than the patient.
    b) Test Date Error (Type 2b): prior test date is later than the WES/WGS collection date.
    c) Missing Collection Date (Type 2c): specimen collection date is absent from the profile.
    d) Irrelevant Clinical Profile (Type 3b): clinical information unrelated to genetic testing.
    e) Colliding Patient Names (Type 4): two profiles share identical names.

3) Over-Refusal Error: the agent incorrectly stopped submission due to a hallucinated, \
misinterpreted, or non-existent issue.

4) Inference Failure: the agent requested information that should have been inferred from the \
patient's clinical data (ICD codes, rationale, prior tests), leading to non-submission.

Please return ONLY the selected category name. Below is the sample type and output message:
"""


def check_non_submitted(task_list: List[Dict], submitted_summaries: List[Dict]) -> List[Dict]:
    """Return summary dicts for tasks that completed unsuccessfully and were not submitted."""
    submitted_task_ids = {
        str(s.get("task_id")).strip()
        for s in submitted_summaries
        if isinstance(s, dict) and s.get("task_id")
    }
    summaries = []
    for task in task_list:
        if task.get("isSuccess") is not False:
            continue
        if str(task.get("id", "")).strip() in submitted_task_ids:
            continue
        sample_type = task.get("metadata", {}).get("sample_type", "")
        summaries.append({
            "task_id":       task.get("id", ""),
            "llm":           task.get("llm", ""),
            "sample_type":   sample_type,
            "patient_name":  task.get("metadata", {}).get("patient_name", ""),
            "submitted":     False,
            "confusion_label": "TN" if sample_type in {"2a", "2b", "2c", "3b"} else "FN",
            "num_incorrect": None,
            "num_missing":   None,
            "incorrect_fields": None,
            "missing_fields":   None,
            "output_msg":    task.get("output", ""),
        })
    return summaries


def create_batch_input(summaries: List[Dict], output_path: Path) -> None:
    """Write a GPT Batch API JSONL file to classify non-submitted task reasons."""
    with output_path.open("w", encoding="utf-8") as f:
        for i, summary in enumerate(summaries):
            # Truncate long output messages to stay within token limits
            output_msg = str(summary.get("output_msg") or "")
            if len(output_msg) > 6000:
                output_msg = output_msg[:6000] + "\n...[truncated]"
            content = _NON_SUBMITTED_CLASSIFICATION_PROMPT + json.dumps(
                {"sample_type": summary.get("sample_type", ""), "output_msg": output_msg}, indent=2
            )
            f.write(json.dumps({
                "custom_id": f"summary_{i + 1}",
                "method":    "POST",
                "url":       "/v1/responses",
                "body": {
                    "model": "gpt-5.2",
                    "input": [{"role": "user", "content": content}],
                    "max_output_tokens": 20,
                    "temperature": 0,
                },
            }, ensure_ascii=False) + "\n")
    logger.info("Batch input written: %s", output_path)


def process_non_submitted_summaries(summaries: List[Dict], batch_input_path: Path,
                                    output_path: Optional[Path] = None) -> List[Dict]:
    """Submit the GPT batch job, extract classifications, and merge back into summaries."""
    try:
        batch_output = process_batch(str(batch_input_path))
        if not batch_output:
            logger.warning("No batch output returned — classification_result will be empty.")
            updated = [{**dict(s or {}), "classification_result": ""} for s in summaries]
        else:
            classifications = extract_output(batch_output)
            if len(classifications) != len(summaries):
                logger.warning("Classification count (%s) ≠ summaries count (%s).",
                               len(classifications), len(summaries))
            updated = [
                {**dict(s or {}), "classification_result": classifications[i] if i < len(classifications) else ""}
                for i, s in enumerate(summaries)
            ]
        if output_path:
            _upsert_json(output_path, updated, key="task_id")
        return updated
    except Exception as e:
        logger.error("Error processing non-submitted summaries: %s", e)
        return summaries


# ── Reporting tables ──────────────────────────────────────────────────────────

def raw_summary(submitted_json_path: Path, non_submitted_json_path: Path,
                tasks_steps: Optional[Dict[str, Optional[int]]] = None) -> pd.DataFrame:
    """Combine submitted and non-submitted summaries into a single DataFrame.

    Inserts a number_of_steps column derived from tasks_steps, and drops
    duplicate rows where a task appears in both files.
    """
    rows: List[Dict] = []

    if submitted_json_path.exists():
        try:
            with submitted_json_path.open("r", encoding="utf-8") as f:
                rows.extend(dict(r) for r in json.load(f) if r)
        except Exception as e:
            logger.warning("Could not read submitted summaries: %s", e)

    if non_submitted_json_path.exists():
        try:
            with non_submitted_json_path.open("r", encoding="utf-8") as f:
                for r in json.load(f):
                    row = dict(r or {})
                    row.pop("output_msg", None)
                    row.pop("classification_result", None)
                    rows.append(row)
        except Exception as e:
            logger.warning("Could not read non-submitted summaries: %s", e)

    df = pd.DataFrame(rows)

    if "task_id" in df.columns:
        df["number_of_steps"] = df["task_id"].map(tasks_steps or {}).astype("Int64")
        # Move number_of_steps immediately after task_id
        cols = list(df.columns)
        cols.remove("number_of_steps")
        cols.insert(cols.index("task_id") + 1, "number_of_steps")
        df = df[cols]

    # Remove non-submitted duplicates when a submitted record exists for the same task
    if {"submitted", "task_id"}.issubset(df.columns):
        submitted_ids = set(df.loc[df["submitted"] == True, "task_id"])
        df = df[~(df["task_id"].isin(submitted_ids) & (df["submitted"] != True))].copy()

    sort_cols = [c for c in ["llm", "sample_type"] if c in df.columns]
    return df.sort_values(by=sort_cols, kind="stable", na_position="last",
                          ignore_index=True) if sort_cols else df


def compute_metrics(summary: pd.DataFrame) -> pd.DataFrame:
    """Compute per-LLM sensitivity and specificity from confusion labels."""
    def _sensitivity(tp, fn): return tp / (tp + fn) if (tp + fn) > 0 else None
    def _specificity(tn, fp): return tn / (tn + fp) if (tn + fp) > 0 else None

    rows = []
    for llm, group in summary.groupby("llm", dropna=False):
        tp = int((group["confusion_label"] == "TP").sum())
        tn = int((group["confusion_label"] == "TN").sum())
        fp = int((group["confusion_label"] == "FP").sum())
        fn = int((group["confusion_label"] == "FN").sum())
        rows.append({"llm": llm, "TP": tp, "TN": tn, "FP": fp, "FN": fn,
                     "sensitivity": _sensitivity(tp, fn), "specificity": _specificity(tn, fp)})
    return pd.DataFrame(rows).sort_values("llm", kind="stable", ignore_index=True)


def accuracy_table(raw_summary_df: pd.DataFrame, start_col: str, end_col: str) -> pd.DataFrame:
    """Compute per-field bootstrap accuracy for submitted positive-type samples (1, 3a).

    Pivots to one row per field_type, one column per LLM.
    """
    required = {"submitted", "sample_type", "llm"}
    if raw_summary_df.empty or not required.issubset(raw_summary_df.columns):
        return pd.DataFrame(columns=["field_type"])

    filtered = raw_summary_df[
        (raw_summary_df["submitted"] == True)
        & (raw_summary_df["sample_type"].astype(str).isin(["1", "3a"]))
    ].copy()

    cols = list(filtered.columns)
    field_cols: List[str] = []
    if start_col in cols and end_col in cols:
        s, e = cols.index(start_col), cols.index(end_col)
        if s <= e:
            field_cols = cols[s:e + 1]
    if not field_cols:
        return pd.DataFrame(columns=["field_type"])

    long_df = filtered[["llm", *field_cols]].melt(id_vars=["llm"], value_vars=field_cols,
                                                    var_name="field_type", value_name="value")
    long_df = long_df[long_df["llm"].notna()].copy()
    if long_df.empty:
        return pd.DataFrame(columns=["field_type"])

    long_df["correct"] = (long_df["value"] == 1).astype(float)
    pivot = long_df.pivot_table(index="field_type", columns="llm", values="correct", aggfunc="mean")
    pivot = pivot.reindex(field_cols)
    pivot = pivot.rename(columns={
        col: f"{str(col).strip().lower().replace(' ', '_')}_accuracy" for col in pivot.columns
    }).reset_index()
    return pivot

def non_submitted_table(non_submitted_json_path: Path) -> pd.DataFrame:
    """Load non-submitted summaries and return a cleaned, sorted DataFrame."""
    cols = ["task_id", "llm", "sample_type", "patient_name",
            "confusion_label", "classification_result", "output_msg"]
    summaries: List[Dict] = []
    if non_submitted_json_path.exists():
        try:
            with non_submitted_json_path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                summaries = loaded
        except Exception as e:
            logger.warning("Could not read non-submitted summaries: %s", e)

    df = pd.DataFrame(summaries).reindex(columns=cols)
    if "classification_result" in df.columns:
        df["classification_result"] = (
            df["classification_result"].fillna("").astype(str)
            .apply(lambda v: re.sub(r"[^A-Za-z\s]+", "", v))
            .str.replace(r"\s+", " ", regex=True).str.strip()
        )
    sort_cols = [c for c in ["llm", "sample_type"] if c in df.columns]
    return df.sort_values(by=sort_cols, kind="stable", na_position="last",
                          ignore_index=True) if sort_cols else df


# ── Shared file helper ────────────────────────────────────────────────────────

def _upsert_json(path: Path, new_records: List[Dict], key: str) -> None:
    """Append records to a JSON array file, skipping any whose key already exists."""
    if not new_records:
        return
    existing: List[Dict] = []
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                existing = loaded
        except Exception as e:
            logger.warning("Could not read %s: %s", path, e)

    by_key: Dict[str, Dict] = {str(r.get(key, "")).strip(): r
                                for r in existing if r.get(key) is not None}
    no_key = [r for r in existing if r.get(key) is None]

    for r in new_records:
        k = r.get(key)
        if k is not None:
            k_str = str(k).strip()
            if k_str not in by_key:
                by_key[k_str] = r
        else:
            no_key.append(r)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(list(by_key.values()) + no_key, f, ensure_ascii=False, indent=2)
    logger.info("Saved %d records to %s", len(new_records), path)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root_dir = Path(__file__).resolve().parents[2]

    parser = argparse.ArgumentParser(description="Evaluate PA form submissions against ground truth.")
    parser.add_argument("--groundtruth",           default=str(root_dir / "data" / "patient_data" / "all_samples.json"))
    parser.add_argument("--submissions-dir-flash", default=str(root_dir / "data" / "gemini_flash"))  # untracked
    parser.add_argument("--submissions-dir-3-pro", default=str(root_dir / "data" / "gemini_3_pro")) # untracked
    parser.add_argument("--submissions-dir-claude", default=str(root_dir / "data" / "claude_opus"))  # untracked
    parser.add_argument("--results",               default=str(root_dir / "data" / "results" / "exp_results.xlsx"))
    parser.add_argument("--batch-input",           default=str(root_dir / "data" / "batch_input" / "non_submitted_batch_input.jsonl"))
    parser.add_argument("--submitted-json",        default=str(root_dir / "data" / "results" / "submitted_summaries.json"))
    parser.add_argument("--non-submitted-json",    default=str(root_dir / "data" / "results" / "non_submitted_summaries.json"))
    parser.add_argument("--start-et",             default="2026-03-02T00:00:00") # Adjust as needed to cover the relevant time window for task fetching
    parser.add_argument("--end-et",               default="2026-03-02T23:00:00")
    args = parser.parse_args()

    groundtruth_path       = Path(args.groundtruth)
    submissions_dir_flash  = Path(args.submissions_dir_flash)
    submissions_dir_3_pro  = Path(args.submissions_dir_3_pro)
    results_path           = Path(args.results)
    batch_input_path       = Path(args.batch_input)
    submitted_json_path    = Path(args.submitted_json)
    non_submitted_json_path = Path(args.non_submitted_json)
    results_path.parent.mkdir(parents=True, exist_ok=True)

    # 1) Fetch tasks from Browser-Use Cloud and estimate step counts from cost
    new_tasks   = get_tasks(args.start_et, args.end_et)
    tasks_steps = get_tasks_steps(new_tasks)

    # 2) Evaluate submitted forms from both model directories against ground truth
    submitted_flash = get_submitted_summaries(groundtruth_path, submissions_dir_flash, submitted_json_path)
    submitted_3_pro = get_submitted_summaries(groundtruth_path, submissions_dir_3_pro, submitted_json_path)
    submitted_claude = get_submitted_summaries(groundtruth_path, submissions_dir_flash, submitted_json_path)  # Assuming Claude models are in the same dir as flash; adjust if needed

    # 3) Classify non-submitted tasks via GPT batch
    non_submitted = check_non_submitted(new_tasks, submitted_flash)
    create_batch_input(non_submitted, batch_input_path)
    process_non_submitted_summaries(non_submitted, batch_input_path, non_submitted_json_path)

    # 4) Combine all results into a single DataFrame
    complete_summary = raw_summary(submitted_json_path, non_submitted_json_path, tasks_steps)

    # 5) Compute metrics and tables, write to Excel (one sheet each)
    with pd.ExcelWriter(results_path, engine="openpyxl") as writer:
        complete_summary.to_excel(writer, sheet_name="Raw summary", index=False)
        compute_metrics(complete_summary).to_excel(writer, sheet_name="Overall metrics", index=False)
        accuracy_table(complete_summary, "patient_first_name", "internal_test_code").to_excel(writer, sheet_name="Determinstic fields", index=False)
        accuracy_table(complete_summary, "mca", "prior_test_date").to_excel(writer, sheet_name="Interpretive fields", index=False)
        non_submitted_table(non_submitted_json_path).to_excel(writer, sheet_name="Non-submitted", index=False)

    """
    Both ablation study 1 and 3 went through step 1) as above to fetch the results from browser use API. 
    For Ablation study 1, the resulting directory is data/results/ablation_1.json, which already has the task outcomes categories directly embedded in this file.
    The evaluation for ablation study 1 submitted files is storied in data/results/ablation_1_submitted.json. 
    For Ablation study 3, the resulting directory is lost, please refer to ablation_3 sheet of exp_results.xlsx. Since the sample size is small for this ablation,
    all the examination described in the manuscript was done manually.

    Review browser_use_execution.py for the directories where the submissions for ablation studies are stored, and adjust the paths in the argparse section above 
    to point to those directories/files when running the evaluation for ablation study.
    """