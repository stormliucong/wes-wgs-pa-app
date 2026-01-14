"""Check the submission files against the groundtruth files
- Directly compare the submission payload with the groundtruth payload for each sample type 
(1, 2a, 2b, 2c, 3a, 3c)
"""

from typing import Dict


def check_submission(submission_payload: Dict, groundtruth: Dict) -> bool: #
    """Check if the submission matches the groundtruth"""
    for key in groundtruth:
        if key not in submission_payload:

            return False
        if submission_payload[key] != groundtruth[key]:
            return False
    return True