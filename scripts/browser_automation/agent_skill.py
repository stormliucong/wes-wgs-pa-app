"""Browser automation skill helpers.

This module is intentionally lightweight; project-specific automation
is implemented in make_submissions.py.
"""

from typing import Dict


def build_login_payload(username: str, password: str) -> Dict[str, str]:
    return {"username": username, "password": password}
