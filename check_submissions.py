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
    for key in payload:
        if key not in groundtruth:
            continue
        payload_value = payload.get(key)
        groundtruth_value = groundtruth.get(key)
        if payload_value != groundtruth_value:
            check_result[key] = {"Expected": groundtruth_value, "Got": payload_value}
        else:
            check_result[key] = "Correct"

    report = {
        "patient_id": submission.get("patient_id", ""),
        "sample_type": submission.get("sample_type", ""),
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