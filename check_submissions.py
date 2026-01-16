"""Check the submission files against the groundtruth files
- Directly compare the submission payload with the groundtruth payload for each sample type 
(1, 2a, 2b, 2c, 3a, 3c)
"""

from ast import List
from typing import Dict


def find_groundtruth(submission, groundtruths) -> Dict:
    """Find the groundtruth profile for a given submission"""
    sample_type = submission.get("sample_type")
    return groundtruths.get(sample_type, {})

def check_submission(submission: Dict, groundtruth: Dict):
    """Check if the submission matches the groundtruth"""
    payload = submission.get("payload", {})
    check_result = {key: "Correct" for key in payload}
    for key in payload:
        if payload[key] != groundtruth[key]:
            check_result[key] = f"Expected {groundtruth[key]}, but got {payload[key]}"
    return check_result

