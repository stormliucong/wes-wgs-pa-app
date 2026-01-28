"""Check the submission files against the groundtruth files
- Directly compare the submission payload with the groundtruth payload for each sample type 
(1, 2a, 2b, 2c, 3a, 3c)
"""

from typing import List, Dict
import json
from pathlib import Path

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
        "check_result": check_result}
    
    return report

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