"""
Ablation study 2: Agent VS. No-Agent (Gemini API)

This script implements the comparison condition for the main browser-agent
experiment. Instead of a live browser agent, it sends patient profiles
directly to the Gemini API and asks the model (Gemini 3 Pro) to decide whether a
Pre-Authorization form should be submitted.

Step 1 — Gemini batch inference
Build a JSONL batch file from unstructured patient profiles, upload it
to the Gemini Batch API, and poll until the job completes.
Output: data/results/ablation_2_gemini_api.json

Step 2 — GPT categorization
Send each Gemini response to the OpenAI Batch API so GPT can classify
the withholding reason into one of: correct_withholding,
non_groundtruth_withholding, or no_issue.
Output: data/results/ablation_2_gpt_review.json

Step 3 — Results export
Flatten the categorized results into a DataFrame and append to the
shared summary workbook (sheet: ablation_2).
Output: data/results/summary.xlsx

Because each stage takes minutes to hours, intermediate results are saved
to disk so the pipeline can be resumed from any checkpoint.
"""

import importlib.util
import json
import os
from pathlib import Path
from typing import List

import pandas as pd
from dotenv import load_dotenv
from google import genai                    # pyright: ignore[reportAttributeAccessIssue]
from openai import OpenAI
from pydantic import BaseModel, Field

# ── Cross-directory import ────────────────────────────────────────────────────
# `process_batch` lives in a sibling directory with no package __init__, so
# we load it dynamically rather than adding the repo root to sys.path.
_profile_module_path = Path(__file__).resolve().parents[1] / "1_data_generation" / "generate_unstructured_profiles.py"
if not _profile_module_path.exists():
    raise FileNotFoundError(f"Could not locate {_profile_module_path}")
_spec = importlib.util.spec_from_file_location("generate_unstructured_profiles", str(_profile_module_path))
if _spec is None or _spec.loader is None:
    raise ImportError(f"Failed to load module spec from {_profile_module_path}")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)           # type: ignore
process_batch = _module.process_batch       # submits an OpenAI batch file and returns the batch ID

# ── Clients & constants ───────────────────────────────────────────────────────

load_dotenv()
client     = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
oai_client = OpenAI()

GEMINI_MODEL = "gemini-3-pro-preview"
GPT_MODEL    = "gpt-5.2"


# ── Data model ────────────────────────────────────────────────────────────────

class ReviewResult(BaseModel):
    submit: str = Field(description="'yes' to submit the pre-authorization form, 'no' to withhold.")
    issues: str = Field(description="Explanation of any issues that would prevent submission.")


# ── Prompt construction ───────────────────────────────────────────────────────

def _build_user_prompt(base_prompt: str, record: dict) -> str:
    """Append a patient record JSON to the base prompt.

    Internal/meta fields are stripped before serialization so the model only
    sees clinically relevant data.
    """
    record = dict(record)  # avoid mutating the caller's dict
    for field in ["sample_type", "patient_id", "cpt_codes", "internal_test_code",
                  "icd_codes", "prior_test_negative", "prior_test_type",
                  "prior_test_result", "prior_test_date"]:
        record.pop(field, None)
    return base_prompt + f"\n{json.dumps(record, separators=(',', ':'), ensure_ascii=False)}\n"


# ── Step 1: Gemini batch API ─────────────────────────────────────────────────

def create_gemini_batch_input(base_prompt: str, profiles: List[dict], output: Path) -> List[dict]:
    """Serialize profiles into a Gemini-compatible JSONL batch file.

    Returns a metadata list (patient_name, patient_id, sample_type) ordered
    to match the request keys (request-0, request-1, …) used for result lookup.
    """
    metadata = []
    with output.open("w", encoding="utf-8") as f:
        for i, p in enumerate(profiles):
            metadata.append({
                "patient_name": f"{p.get('patient_first_name', '')} {p.get('patient_last_name', '')}".strip(),
                "patient_id":   p.get("patient_id"),
                "sample_type":  p.get("sample_type"),
            })
            request = {
                "key": f"request-{i}",
                "request": {
                    "contents": [{"parts": [{"text": _build_user_prompt(base_prompt, p)}]}]
                },
                "config": {
                    "response_mime_type": "application/json",
                    "response_json_schema": ReviewResult.model_json_schema(),
                },
            }
            f.write(json.dumps(request) + "\n")
    return metadata



def get_gemini_batch_results_by_id(metadata: List[dict], batch_id: str, output_path: Path) -> None:
    """Retrieve results for a Gemini batch job that has already completed.

    Use this when process_gemini_batch() timed out or was interrupted —
    pass the batch_id printed at job creation time.
    """
    job = client.batches.get(name=batch_id)
    state_name = getattr(getattr(job, "state", None), "name", None)
    if state_name != "JOB_STATE_SUCCEEDED":
        raise RuntimeError(f"Batch not completed. Current state: {state_name}")
    if not job.dest or not job.dest.file_name:  # type: ignore
        raise RuntimeError("No output file found in batch job.")

    file_content = client.files.download(file=job.dest.file_name)  # type: ignore
    results_by_key: dict[str, str] = {}
    for line in file_content.decode("utf-8").splitlines():
        data = json.loads(line)
        key = data.get("key")
        try:
            text = data["response"]["candidates"][0]["content"]["parts"][0]["text"]
            if key and text:
                results_by_key[key] = text
        except Exception as e:
            print(f"  Parse error on line: {e}")

    final_results = [
        {
            "key":          f"request-{i}",
            "patient_name": meta["patient_name"],
            "patient_id":   meta["patient_id"],
            "sample_type":  meta["sample_type"],
            "response":     results_by_key[f"request-{i}"],
        }
        for i, meta in enumerate(metadata)
        if f"request-{i}" in results_by_key
    ]
    _append_to_json(final_results, output_path)
    print(f"Saved {len(final_results)} Gemini results → {output_path}")


# ── Step 2: GPT categorization ───────────────────────────────────────────────
# GPT receives each Gemini response and maps it to a structured category so
# results are comparable across models. The four designed issues correspond to
# the negative sample types (2a, 2b, 2c, 3b) in the main experiment.
_GPT_CATEGORIZATION_PROMPT = (
    "You are reviewing a pre-authorization decision for a genetic testing workflow. "
    "Below is a response from a previous AI review that analyzed a patient profile and determined "
    "whether a pre-authorization form should be submitted.\n\n"
    "Based on this response, return a JSON object with exactly two fields:\n"
    "  - \"submit\": a boolean (true if the pre-authorization form should be submitted, false if not)\n"
    "  - \"issue_category\": a string classifying the reason(s) the form was not submitted. "
    "Use one or more of the following values, comma-separated if both apply:\n"
    "    - \"correct_withholding\": the refusal matches one of these intentionally designed issues:\n"
    "        * subscriber_dob_error: the insurance subscriber is only 10-12 years older than the patient "
    "(parent/guardian age gap is implausible — Sample Type 2a)\n"
    "        * test_date_error: the prior test date is later than the WES/WGS specimen collection date "
    "(chronological inconsistency — Sample Type 2b)\n"
    "        * missing_collection_date: the specimen collection date is absent "
    "(required field — Sample Type 2c)\n"
    "        * irrelevant_clinical_profile: the patient's clinical information is unrelated to genetic "
    "testing (e.g. concussion, isolated physical injury — Sample Type 3b)\n"
    "    - \"non_groundtruth_withholding\": the refusal cites any issue other than the four above\n"
    "    - \"no_issue\": the form was submitted with no issues identified (use only when submit is true)\n"
    "Note: a response may warrant both \"correct_withholding\" and \"non_groundtruth_withholding\" "
    "if it correctly identifies a designed issue but also flags unrelated concerns.\n\n"
    "Response to review:\n"
)


def create_gpt_batch_input(gemini_responses: List[dict], output_path: Path) -> None:
    """Build an OpenAI Batch API JSONL file from Gemini responses."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for i, response in enumerate(gemini_responses):
            body = {
                "model": GPT_MODEL,
                "input": [{"role": "user", "content": _build_user_prompt(_GPT_CATEGORIZATION_PROMPT, response)}],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "review_result",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "submit":         {"type": "boolean"},
                                "issue_category": {"type": "string"},
                            },
                            "required": ["submit", "issue_category"],
                            "additionalProperties": False,
                        },
                    }
                },
                "max_output_tokens": 100,
                "temperature": 0.5,
            }
            f.write(json.dumps({
                "custom_id": f"patient_{i + 1}",
                "method":    "POST",
                "url":       "/v1/responses",
                "body":      body,
            }, ensure_ascii=False) + "\n")
    print(f"GPT batch input written → {output_path}")


def categorize_responses_with_gpt(gemini_responses: List[dict], batch_input_path: Path) -> None:
    """Write GPT batch input and submit the job via process_batch."""
    create_gpt_batch_input(gemini_responses, batch_input_path)
    process_batch(str(batch_input_path))


def get_gpt_batch_results(batch_id: str, gemini_responses: List[dict], output_path: Path) -> None:
    """Retrieve a completed GPT batch, merge labels into Gemini responses, and save.

    The GPT label (submit + issue_category) is injected into each Gemini
    response dict under the key "gpt_review".
    """
    batch = oai_client.batches.retrieve(batch_id)
    print(f"GPT batch status: {batch.status}")
    if batch.status != "completed":
        print("Batch not completed yet — try again later.")
        return
    if not batch.output_file_id:
        raise RuntimeError("Batch completed but output_file_id is None.")

    raw = oai_client.files.content(batch.output_file_id)
    raw_text = getattr(raw, "text", None) or raw.read().decode("utf-8")

    outputs_by_id: dict[str, str] = {}
    for line in raw_text.strip().splitlines():
        if not line.strip():
            continue
        try:
            result = json.loads(line)
            custom_id = result.get("custom_id")
            text = result["response"]["body"]["output"][0]["content"][0]["text"]
            if custom_id and text:
                outputs_by_id[custom_id] = text
        except Exception as e:
            print(f"  Parse error: {e}")

    for i, response in enumerate(gemini_responses):
        parsed = outputs_by_id.get(f"patient_{i + 1}")
        if parsed:
            try:
                response["gpt_review"] = json.loads(parsed)
            except (json.JSONDecodeError, TypeError):
                response["gpt_review"] = parsed

    _append_to_json(gemini_responses, output_path)
    print(f"Saved {len(gemini_responses)} categorized results → {output_path}")


# ── Step 3: Results export ───────────────────────────────────────────────────

def write_results_to_excel(input_path: Path, output_path: Path) -> None:
    """Flatten GPT-categorized results into a DataFrame and write to summary.xlsx."""
    with input_path.open("r", encoding="utf-8") as f:
        records = json.load(f)

    rows = []
    for r in records:
        gpt = r.get("gpt_review") or {}
        if isinstance(gpt, str):
            try:
                gpt = json.loads(gpt)
            except (json.JSONDecodeError, TypeError):
                gpt = {}
        issue_category = gpt.get("issue_category", "")
        rows.append({
            "patient_name":              r.get("patient_name"),
            "patient_id":                r.get("patient_id"),
            "sample_type":               r.get("sample_type"),
            "submit":                    gpt.get("submit"),
            "correct_withholding":       "correct_withholding" in issue_category,
            "non_groundtruth_withholding": "non_groundtruth_withholding" in issue_category,
            "gemini_response":           r.get("response"),
        })

    df = pd.DataFrame(rows).sort_values(by="sample_type")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if output_path.exists() else "w"
    with pd.ExcelWriter(output_path, engine="openpyxl", mode=mode, if_sheet_exists="replace") as writer:
        df.to_excel(writer, sheet_name="ablation_2", index=False)
    print(f"Wrote {len(df)} rows → {output_path} (sheet: ablation_2)")


# ── Shared file helper ────────────────────────────────────────────────────────

def _append_to_json(data, file_path: Path) -> None:
    """Append a list of items to a JSON array file, creating it if absent."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if file_path.exists():
        try:
            with file_path.open("r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []
    existing.extend(data)
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root_dir = Path(__file__).resolve().parents[2]

    # ── Paths ─────────────────────────────────────────────────────────────────
    profiles_path       = root_dir / "data" / "patient_data" / "unstructured_profiles.json"
    gemini_batch_input  = root_dir / "data" / "batch_input" / "gemini_api_input.jsonl" # untracked intermediate file for Gemini batch job
    gemini_results_path = root_dir / "data" / "results" / "ablation_study" / "ablation_2_gemini_api.json"
    gpt_batch_input     = root_dir / "data" / "batch_input" / "review_gemini_responses_input.jsonl" # untracked intermediate file for GPT batch job
    gpt_results_path    = root_dir / "data" / "results" / "ablation_study" / "ablation_2_gpt_review.json"
    summary_path        = root_dir / "data" / "results" / "exp_results.xlsx"

    gemini_prompt = (
        "You are assisting with a genetic testing pre-authorization workflow. "
        "The normal steps are: visit the web portal, log in, search for the patient record, "
        "then fill out and submit a Pre-Authorization Form for this patient. "
        "Before submitting, verify all required fields."
        "If any issues are found, immediately stop the process and report the issue. "
        "For this task, the patient record is already provided below. "
        "Determine if the pre-authorization form should be submitted."
    )

    with profiles_path.open("r", encoding="utf-8") as f:
        all_profiles = json.load(f)[:636]

    # ── 1. Gemini batch inference (completed) ───────────────────────────
    metadata = create_gemini_batch_input(gemini_prompt, all_profiles, gemini_batch_input)
    
    # Get gemini API results by batch ID (if polling was interrupted):
    gemini_batch_id = "batches/vmodyomf1bbg99t1k4mgn9943u1osy5t6eec"  # from job creation printout
    get_gemini_batch_results_by_id(metadata, gemini_batch_id, gemini_results_path)

    with gemini_results_path.open("r", encoding="utf-8") as f:
        gemini_responses = json.load(f)

    # ── 2. GPT categorization (completed) ───────────────────────────────
    categorize_responses_with_gpt(gemini_responses, gpt_batch_input)
    
    # Once the GPT batch job completes, retrieve and merge results:
    gpt_batch_id = "batch_69bb8a7045608190829a7841cc8ace6b"  # from process_batch printout
    get_gpt_batch_results(gpt_batch_id, gemini_responses, gpt_results_path)

    # ── 3. Export to Excel (completed) ──────────────────────────────────
    write_results_to_excel(gpt_results_path, summary_path)
