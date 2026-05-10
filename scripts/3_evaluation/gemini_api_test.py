import os
import json
import re
import sys
import time
from typing import List
import pandas as pd
from urllib import response
from venv import logger
from google import genai # pyright: ignore[reportAttributeAccessIssue]
from google.genai import types # pyright: ignore[reportMissingImports]
from pydantic import BaseModel, Field
from openai import OpenAI
from dotenv import load_dotenv
from prompt_toolkit import prompt
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data_generation.generate_unstructured_profiles import process_batch

load_dotenv()
gemini_api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=gemini_api_key)
oai_client = OpenAI()
MAX_WORKERS = 1
RETRY_LIMIT = 3

class reviewResults(BaseModel):
    submit: str = Field(description= "Indicates whether the pre-authorization form should be submitted. 'yes' means submit, 'no' means do not submit.")
    issues: str = Field(description= "Explanation of any issues found in the patient profile that would prevent submission.")

def create_user_prompt(base_prompt, record: dict):
    # Remove specified fields from record
    for field in ["sample_type", "patient_id", "cpt_codes", "internal_test_code", "icd_codes", "prior_test_negative",
                  "prior_test_type", "prior_test_result", "prior_test_date"]:
        record.pop(field, None)

    profile_string = json.dumps(record, separators=(',', ':'), ensure_ascii=False)
    base_prompt += f"\n{profile_string}\n"
    return base_prompt

def create_gemini_batch_input(base_prompt, profiles: List[dict], output: Path):
    metadata = []
    with open(output, "w") as f:
        for i, p in enumerate(profiles):
            metadata.append({
                "patient_name": f"{p.get('patient_first_name', '')} {p.get('patient_last_name', '')}",
                "patient_id": p.get("patient_id"),
                "sample_type": p.get("sample_type")
            })

            prompt = create_user_prompt(base_prompt, p)
            request = {
                "key": f"request-{i}",
                "request": {
                    "contents": [
                        {
                            "parts": [
                                {
                                    "text": prompt
                                }
                            ]
                        }
                    ]
                },
                "config":{
                    'response_mime_type': 'application/json',
                    'response_json_schema': reviewResults.model_json_schema()
                }            
            }
            f.write(json.dumps(request) + "\n")
    return metadata

def process_gemini_batch(metadata: List[dict], batch_file_path: Path):
    uploaded_file = client.files.upload(
        file=batch_file_path,
        config=types.UploadFileConfig(display_name=str(batch_file_path), mime_type='application/jsonl')
    )
                        
    # Create batch job
    file_batch_job = client.batches.create(
        model="gemini-3-pro-preview",
        src={"file_name": uploaded_file.name},
        config={"display_name": "gemini-batch-job"}
    )
    if file_batch_job is None or not hasattr(file_batch_job, "name") or file_batch_job.name is None:
        raise RuntimeError("Batch job creation failed or missing job name.")
    
    job_name = file_batch_job.name
    print("Batch job created:", job_name)

    while True:
        batch_job_inline = client.batches.get(name=job_name)
       
        if batch_job_inline is None or not hasattr(batch_job_inline, "state") or batch_job_inline.state is None or not hasattr(batch_job_inline.state, "name"):
            raise RuntimeError("Batch job polling failed or missing state/name attribute.")
        
        if batch_job_inline.state.name in ('JOB_STATE_SUCCEEDED', 'JOB_STATE_FAILED', 'JOB_STATE_CANCELLED', 'JOB_STATE_EXPIRED'):
            break
        print(f"Job not finished. Current state: {batch_job_inline.state.name}. Waiting 10 seconds...")
        time.sleep(30)

    print(f"Job finished with state: {batch_job_inline.state.name}")

    batch_results = batch_job_inline.dest.inlined_responses or [] # type: ignore
    raw_output_path = Path("data\\results\\gemini_api_raw_responses.json")
    raw_output_path.parent.mkdir(parents=True, exist_ok=True)
    add_to_json_file(batch_results, raw_output_path)

    results_by_key = {getattr(r, "key", None): r for r in batch_results}
    final_results = []
    for i, meta in enumerate(metadata):
        result = results_by_key.get(f"request-{i}")
        if result and getattr(result, "response", None):
            final_results.append({
                "patient_name": meta['patient_name'],
                "patient_id": meta['patient_id'],
                "sample_type": meta['sample_type'],
                "response": result.response.text  # type: ignore
            })
    output_path = Path("data\\results\\gemini_api_responses.json")
    add_to_json_file(final_results, output_path)
    print(f"Wrote {len(final_results)} results to {output_path}")

def get_gemini_batch_text_results(metadata, batch_id: str):
    # 1. Get batch job
    job = client.batches.get(name=batch_id)

    if job.state.name != "JOB_STATE_SUCCEEDED": # type: ignore
        raise RuntimeError(f"Batch not completed. Current state: {getattr(job.state, 'name', job.state)}")

    # 2. Get output file name
    if not job.dest or not job.dest.file_name:
        raise RuntimeError("No output file found in batch job")

    output_file_name = job.dest.file_name
    print("Output file:", output_file_name)

    # 3. Download file (bytes)
    file_content = client.files.download(file=output_file_name)
    results_by_key: dict[str, str] = {}
    for line in file_content.decode("utf-8").splitlines():
        data = json.loads(line)
        key = data.get("key")
        try:
            text = data["response"]["candidates"][0]["content"]["parts"][0]["text"]
            if key and text:
                results_by_key[key] = text
        except Exception as e:
            print(f"Error parsing line: {line}. Error: {e}")

    final_results = []
    for i, meta in enumerate(metadata):
        result = results_by_key.get(f"request-{i}")
        if result:
            final_results.append({
                "key": f"request-{i}",
                "patient_name": meta['patient_name'],
                "patient_id": meta['patient_id'],
                "sample_type": meta['sample_type'],
                "response": result
            })
    
    output_path = Path("data\\results\\gemini_api_responses.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    add_to_json_file(final_results, output_path)
    print(f"Wrote {len(final_results)} results to {output_path}")

def create_gpt_batch(base_prompt, gemini_responses: List[dict], output_path: Path):
    
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as outfile:
        for i, response in enumerate(gemini_responses):
            prompt = create_user_prompt(base_prompt, response)
            body = {
                "model": "gpt-5.2",
                "input": [
                    {"role": "user", "content": prompt}
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "review_result",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "submit": {"type": "boolean"},
                                "issue_category": {"type": "string"}
                            },
                            "required": ["submit", "issue_category"],
                            "additionalProperties": False
                        }
                    }
                },
                "max_output_tokens": 100,
                "temperature": 0.5,
            }

            request_object = {
                "custom_id": f"patient_{i+1}",
                "method": "POST",
                "url": "/v1/responses",
                "body": body,
            }
            json_line = json.dumps(request_object, ensure_ascii=False)
            outfile.write(json_line + '\n')

    logger.info(f"Batch input file created successfully: {output_path}")

def categorize_response_w_gpt(gemini_responses: List[dict]):
    base_promtp = (
        "You are reviewing a pre-authorization decision for a genetic testing workflow. "
        "Below is a response from a previous AI review that analyzed a patient profile and determined "
        "whether a pre-authorization form should be submitted.\n\n"
        "Based on this response, return a JSON object with exactly two fields:\n"
        "  - \"submit\": a boolean (true if the pre-authorization form should be submitted, false if not)\n"
        "  - \"issue_category\": a string classifying the reason(s) the form was not submitted. "
        "Use one or more of the following values, comma-separated if both apply:\n"
        "    - \"correct_withholding\": the refusal matches one of these intentionally designed issues:\n"
        "        * subscriber_dob_error: the insurance subscriber is only 10-12 years older than the patient "
        "(parent/guardian age gap is implausible as a subscriber — Sample Type 2a)\n"
        "        * test_date_error: the prior test date is later than the WES/WGS specimen collection date"
        "(chronological inconsistency — Sample Type 2b)\n"
        "        * missing_collection_date: the specimen collection date is absent from the patient profile "
        "(required field — Sample Type 2c)\n"
        "        * irrelevant_clinical_profile: the patient's clinical information is unrelated to genetic testing "
        "(e.g., concussion, isolated physical injury — Sample Type 3b)\n"
        "    - \"non_groundtruth_withholding\": the refusal cites any issue other than the four above\n"
        "    - \"no_issue\": the form was submitted with no issues identified (use only when submit is true)\n"
        "Note: a response may warrant both \"correct_withholding\" and \"non_groundtruth_withholding\" "
        "if it correctly identifies a designed issue but also flags unrelated concerns.\n\n"
        "Response to review:\n"
    )
    batch_input_path = "data\\batch_input\\review_gemini_responses_input.jsonl"
    create_gpt_batch(base_promtp, gemini_responses, Path(batch_input_path))
    process_batch(batch_input_path)

def add_to_json_file(data, file_path):
    if file_path.exists():
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                existing_data = json.load(f)
            except Exception:
                existing_data = []
        existing_data.extend(data)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, indent=2, ensure_ascii=False)

    else:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

def get_gpt_batch_results(batch_id: str, gemini_responses: List[dict], output_path: Path):
    batch = oai_client.batches.retrieve(batch_id)
    print(f"Batch status: {batch.status}")
    if batch.status != "completed":
        print(f"Batch not completed yet.")
        return

    if not batch.output_file_id:
        raise RuntimeError("Batch completed but output_file_id is None")

    raw = oai_client.files.content(batch.output_file_id)
    raw_text = getattr(raw, "text", None)
    if raw_text is None:
        raw_text = raw.read().decode("utf-8")

    outputs_by_id: dict[str, str] = {}
    for line in raw_text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            result = json.loads(line)
            custom_id = result.get("custom_id")
            text = result["response"]["body"]["output"][0]["content"][0]["text"]
            if custom_id and text:
                outputs_by_id[custom_id] = text
        except Exception as e:
            print(f"Error parsing GPT batch line: {e}")

    for i, response in enumerate(gemini_responses):
        parsed_output = outputs_by_id.get(f"patient_{i+1}")
        if parsed_output:
            try:
                response["gpt_review"] = json.loads(parsed_output)
            except (json.JSONDecodeError, TypeError):
                response["gpt_review"] = parsed_output

    add_to_json_file(gemini_responses, output_path)
    print(f"Wrote {len(gemini_responses)} results to {output_path}")

def write_review_results_to_excel():
    input_path = Path(__file__).resolve().parents[2] / "data" / "results" / "final_gpt_review_results.json"
    with open(input_path, "r", encoding="utf-8") as f:
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
            "patient_name": r.get("patient_name"),
            "patient_id": r.get("patient_id"),
            "sample_type": r.get("sample_type"),
            "submit": gpt.get("submit"),
            "correct_withholding": "correct_withholding" in issue_category,
            "non_groundtruth_withholding": "non_groundtruth_withholding" in issue_category,
            "gemini_response": r.get("response")
        })

    df = pd.DataFrame(rows)
    df = df.sort_values(by="sample_type")
    output_path = Path(__file__).resolve().parents[2] / "data" / "results" / "summary.xlsx"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        with pd.ExcelWriter(output_path, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
            df.to_excel(writer, sheet_name="gemini_api_test", index=False)
    else:
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="gemini_api_test", index=False)

    print(f"Wrote {len(df)} rows to {output_path} (sheet: gemini_api_test.xlsx)")


if __name__ == "__main__":
    
    profiles_path = Path(__file__).resolve().parents[2] / "data" / "patient_data" / "unstructured_profiles.json"
    gemini_response_path = Path(__file__).resolve().parents[2] / "data" / "results" / "gemini_api_responses.json"
    
    with open(profiles_path, "r", encoding="utf-8") as f:
        all_profiles = json.load(f)[0:636]
    
    with open(gemini_response_path, "r", encoding="utf-8") as f:
        gemini_responses = json.load(f)

    gemini_prompt = f"""You are assisting with a genetic testing pre-authorization workflow.
    The normal steps are: visit the web portal, log in, search for the patient record, then fill out and submit
    a Pre-Authorization Form for this patient. Before submitting, verify all required fields. If any issues are found, immediately stop the process and report the issue.
    For this task, the patient record is already provided below. Determine if the pre-authorization form should be submitted.
    """
    # gemini_input_batch_path = Path("data\\batch_input\\gemini_api_input.jsonl")
    # metadata = create_gemini_batch_input(gemini_prompt, all_profiles, gemini_input_batch_path)
    # process_gemini_batch(metadata, gemini_input_batch_path)
    
    # gemini_batch_id = "batches/vmodyomf1bbg99t1k4mgn9943u1osy5t6eec"
    # get_gemini_batch_text_results(metadata, gemini_batch_id)
    
    # categorize_response_w_gpt(gemini_responses)

    final_review_results_path = Path("data\\results\\final_gpt_review_results.json")
    gpt_batch_id = "batch_69bb8a7045608190829a7841cc8ace6b"
    # get_gpt_batch_results(gpt_batch_id, gemini_responses, final_review_results_path)
    # write_review_results_to_excel()

    batch = oai_client.batches.retrieve(gpt_batch_id)
    print(f"Batch status: {batch.status}")

    if not batch.output_file_id:
        raise RuntimeError("Batch completed but output_file_id is None")

    raw = oai_client.files.content(batch.output_file_id)
    raw_text = getattr(raw, "text", None)
    if raw_text is None:
        raw_text = raw.read().decode("utf-8")
    print(raw_text)