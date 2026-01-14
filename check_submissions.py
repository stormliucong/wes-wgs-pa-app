"""Check the submission files against the groundtruth files
- Directly compare the submission payload with the groundtruth payload for each sample type 
(1, 2a, 2b, 2c, 3a, 3c)
"""

from typing import Dict


def check_submission(submission: Dict, groundtruth: Dict) -> bool: #
    """Check if the submission matches the groundtruth"""
    payload = submission.get("payload", {})
    check_result = {key: True for key in payload}
    for key in payload:
        if payload[key] != groundtruth[key]:
            check_result[key] = False
            return False
    return True