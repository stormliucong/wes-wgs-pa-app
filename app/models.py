from __future__ import annotations

from typing import Any, Dict, List, Tuple


# Minimal required fields for a pre-authorization submission.
# Adjust/extend to match the full payer form as needed.
REQUIRED_FIELDS = [
    # Patient/Insurance
    "patient_first_name",
    "patient_last_name",
    "patient_dob",  # YYYY-MM-DD
    "member_id",
    "primary_subscriber_is_patient",
    # Provider
    "provider_name",
    "provider_npi",
    "provider_phone",
    "provider_address",
    # Laboratory
    "lab_npi",
    # Test requested
    "test_type",  # WES or WGS
    "cpt_codes",
    "internal_test_code",
    # Diagnoses
    "icd_codes",  # list[str] or comma-separated string
    # Consent
    "consent_ack",  # boolean
    # Signature
    "provider_signature",
    "signature_date",
]


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize client payload to consistent types.
    - icd_codes: comma-separated -> list[str]
    - consent_ack: 'on'/'true'/'1' -> bool
    """
    norm: Dict[str, Any] = dict(payload)


    # Normalize icd_codes: accept list[str], list[dict], or comma-separated string
    icd = norm.get("icd_codes")
    if isinstance(icd, list):
        has_dicts = any(isinstance(c, dict) for c in icd)
        if has_dicts:
            icd_list = [
                str(c.get("code", "")).strip()
                for c in icd
                if isinstance(c, dict) and str(c.get("code", "")).strip()
            ]
        else:
            icd_list = [str(c).strip() for c in icd if str(c).strip()]
    elif isinstance(icd, str):
        icd_list = [c.strip() for c in icd.split(",") if c.strip()]
    else:
        icd_list = []
    norm["icd_codes"] = icd_list

    # Normalize cpt_codes: list of checked values
    cpt = norm.get("cpt_codes")
    norm["cpt_codes"] = [str(c).strip() for c in _as_list(cpt) if str(c).strip()]

    # Normalize prior testing rows
    # pt_type = _as_list(norm.get("prior_test"))
    # pt_result = _as_list(norm.get("prior_test_result"))
    # pt_date = _as_list(norm.get("prior_test_date"))
    # prior_tests = []
    # for i in range(max(len(pt_type), len(pt_result), len(pt_date))):
    #     prior_tests.append(
    #         {
    #             "type": pt_type[i] if i < len(pt_type) else "",
    #             "result": pt_result[i] if i < len(pt_result) else "",
    #             "date": pt_date[i] if i < len(pt_date) else "",
    #         }
    #     )
    # norm["prior_tests"] = [row for row in prior_tests if any(v for v in row.values())]

    # Normalize consent_ack
    consent_raw = str(norm.get("consent_ack", "")).strip().lower()
    norm["consent_ack"] = consent_raw in {"1", "true", "yes", "on"}

    return norm


def validate_submission(payload: Dict[str, Any]) -> Tuple[bool, Dict[str, str]]:
    """Validate required fields and simple value checks.
    Returns: (is_valid, errors_by_field)
    """
    errors: Dict[str, str] = {}

    def _first_nonempty(value: Any) -> str:
        if isinstance(value, list):
            for v in value:
                s = str(v).strip()
                if s:
                    return s
            return ""
        return str(value).strip() if value is not None else ""

    # Required presence
    for field in REQUIRED_FIELDS:
        if field not in payload or payload[field] in (None, "", []):
            errors[field] = "This field is required."

    # Value constraints
    test_type = payload.get("test_type")
    if test_type and test_type not in {"WES", "WGS"}:
        errors["test_type"] = "Must be 'WES' or 'WGS'."

    # NPI simple pattern check (10 digits)
    npi = str(payload.get("provider_npi", "")).strip()
    if npi and (not npi.isdigit() or len(npi) != 10):
        errors["provider_npi"] = "Provider NPI must be exactly 10 digits (numbers only, no spaces or dashes)."

    # Member ID: allow non-digit values (e.g., alphanumeric or with special characters)
    # Still required by REQUIRED_FIELDS, but no numeric-only constraint.

    # Lab NPI validation (optional field, but if provided must be valid)
    lab_npi = str(payload.get("lab_npi", "")).strip()
    if lab_npi and (not lab_npi.isdigit() or len(lab_npi) != 10):
        errors["lab_npi"] = "Lab NPI must be exactly 10 digits (numbers only, no spaces or dashes)."

    # Phone and fax validation (10 digits after removing formatting)
    for field in ["provider_phone", "provider_fax"]:
        phone_value = str(payload.get(field, "")).strip()
        if phone_value:
            # Remove all non-digit characters
            digits_only = ''.join(c for c in phone_value if c.isdigit())
            if len(digits_only) != 10:
                field_name = field.replace("_", " ").title()
                errors[field] = f"{field_name} must be a valid 10-digit phone number."

    # CPT required and must be valid if provided
    valid_cpt = {"81415", "81416", "81417", "81425", "81426", "81427"}
    cpt_codes = payload.get("cpt_codes", [])
    if isinstance(cpt_codes, list):
        invalid = [c for c in cpt_codes if c not in valid_cpt]
        if invalid:
            errors["cpt_codes"] = f"Invalid CPT code(s): {', '.join(invalid)}"

    # Must have at least one ICD code
    if not payload.get("icd_codes"):
        errors["icd_codes"] = "At least one ICD-10 code is required."

    # Consent must be True
    if "consent_ack" in payload and payload.get("consent_ack") is not True:
        errors["consent_ack"] = "Consent is required to submit."

    # If patient is NOT the primary subscriber, subscriber details become mandatory
    primary = str(payload.get("primary_subscriber_is_patient", "")).strip().lower()
    if primary == "no":
        if not payload.get("subscriber_name"):
            errors["subscriber_name"] = "Subscriber name is required when the patient is not the primary subscriber."
        if not payload.get("subscriber_dob"):
            errors["subscriber_dob"] = "Subscriber date of birth is required when the patient is not the primary subscriber."
        relation = payload.get("subscriber_relation")
        if not relation:
            errors["subscriber_relation"] = "Subscriber relationship is required when the patient is not the primary subscriber."
        elif relation == "Other" and not payload.get("subscriber_relation_other"):
            errors["subscriber_relation_other"] = "Please specify the subscriber relationship when 'Other' is selected."

    # If prior test negative is selected, require prior test details
    prior_negative_raw = payload.get("prior_test_negative")
    prior_negative = prior_negative_raw is True or str(prior_negative_raw).strip().lower() in {"1", "true", "yes", "on"}
    if prior_negative:
        pt_type = _first_nonempty(payload.get("prior_test_type"))
        pt_result = _first_nonempty(payload.get("prior_test_result"))
        pt_date = _first_nonempty(payload.get("prior_test_date"))
        if not pt_type:
            errors["prior_test_type"] = "Prior test type is required when prior testing is marked as negative."
        if not pt_result:
            errors["prior_test_result"] = "Prior test result is required when prior testing is marked as negative."
        if not pt_date:
            errors["prior_test_date"] = "Prior test date is required when prior testing is marked as negative."

    # Optional provider email format check
    email = str(payload.get("provider_email", "")).strip()
    if email:
        if "@" not in email or "." not in email.split("@")[-1]:
            errors["provider_email"] = "Provider email must be a valid email address."

    return (len(errors) == 0, errors)
