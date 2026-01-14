import argparse
import json
import logging
import os
import sys
import time
from typing import Dict, List, Tuple, Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

client = OpenAI()
def create_prompt(clinical_note: str, rationale: int) -> str:
    if rationale == 1:
        checkboxes = "1a), 1b), 1c), and 2."
    else:
        checkboxes = "1d), 1e), and 3."
    prompt = f"""
        You are a careful clinical reviewer. Read the clinical note and decide if it justifies for option {checkboxes}.
        for WES/WGS testing. Respond with a single word only: "yes" or "no".

        Rationales:
        1. Presentation strongly suggests a genetic disorder (any of):
            1a) Multiple congenital anomalies
            1b) Global developmental delay or intellectual disabilities
            1c) Dysmorphic/syndromic physical features
            1d) Unexplained neurological symptoms (e.g., epilepsy, movement disorder, dystonia, ataxia)
            1e) Unexplained metabolic phenotype (e.g., lactic acidosis, hypoglycemia, metabolic decompensation)
            1f) Autism spectrum disorder with additional red-flag features (e.g., seizures, dysmorphism, regression)
            1g) Early-onset, progressive, or multisystem disease
        2. Prior testing (CMA, gene-panel, or single gene) is negative or inconclusive, and WES/WGS is the reasonable next step
        3. Family history suggests a heritable genetic disorder

        Clinical note: {clinical_note}
        """
    return prompt

def create_batch_input(profiles: List[dict], output: str):
    """Create JSONL batch input file for validating clinical notes via OpenAI Batch API."""
    with open(output, 'w', encoding='utf-8') as outfile:
        for i, profile in enumerate(profiles):
            note = profile.get("clinical_note", "")
            rationale = 1 if profile.get("mca") else 2
            prompt = create_prompt(note, rationale)
            request_object = {
                "custom_id": f"validate_note_{i+1}",
                "method": "POST",
                "url": "/v1/responses",
                "body": {
                    "model": "gpt-5.1",
                    "input": prompt,
                    "max_output_tokens": 20,
                    "temperature": 0,
                },
            }
            json_line = json.dumps(request_object, ensure_ascii=False)
            outfile.write(json_line + '\n')
    logger.info(f"Batch input file created: {output}")

def process_batch(batch_input: str) -> Optional[List[str]]:
    """Submit a JSONL batch to OpenAI and wait for completion, returning raw output lines."""
    try:
        upload_batch = client.files.create(file=open(batch_input, "rb"), purpose="batch")
        logger.info(f"Upload ID: {upload_batch.id}")

        batch_job = client.batches.create(
            input_file_id=upload_batch.id,
            endpoint="/v1/responses",
            completion_window="24h",
        )
        logger.info(f"Batch ID: {batch_job.id}")

        while True:
            batch = client.batches.retrieve(batch_job.id)
            logger.info(f"Current batch status: {batch.status}")
            if batch.status in ["completed", "failed", "cancelled", "expired"]:
                logger.info(f"Batch job finished with status: {batch.status}")
                break
            time.sleep(30)

        if batch.status == "completed":
            output_file_id = getattr(batch, "output_file_id", None)
            error_file_id = getattr(batch, "error_file_id", None)
            file_id = output_file_id or error_file_id
            
            if file_id is None:
                logger.error("Batch completed but no output_file_id or error_file_id found")
                return None
            if output_file_id is None and error_file_id is not None:
                logger.error("Batch completed with no successful outputs; returning error file")
            
            raw = client.files.content(file_id)
            raw_text = getattr(raw, "text", None)

            if raw_text:
                output_path = "validation_raw_output.jsonl"
                try:
                    with open(output_path, "w", encoding="utf-8") as out_f:
                        out_f.write(raw_text)
                    logger.info(f"Wrote batch output to {output_path}")
                except Exception as write_err:
                    logger.warning(f"Failed to write batch output to file: {write_err}")
            
            if raw_text is None:
                try:
                    raw_text = raw.read().decode("utf-8")
                except Exception:
                    logger.error("Unable to read batch output content")
                    return None     
            return raw_text.strip().split('\n')    
        return None
    except Exception as e:
        logger.error(f"Error processing the batch: {e}")
        return None

def extract_decisions(raw_responses: List[str]) -> List[str]:
    """Parse batch outputs and extract 'yes'/'no' decisions per line."""
    decisions: List[str] = []
    for line in raw_responses or []:
        line = line.strip()
        if not line:
            decisions.append("no")
            continue
        try:
            result = json.loads(line)
            output = result.get("response", {}).get("body", {}).get("output")
            content = output[0].get("content") if output else []
            text = content[0].get("text", "").strip().lower() if content else ""
            if "yes" in text:
                decisions.append("yes")
            elif "no" in text:
                decisions.append("no")
            else:
                decisions.append("no")
        except json.JSONDecodeError:
            decisions.append("no")
    return decisions

def filter_profiles_by_decision(profiles: List[dict], decisions: List[str]) -> List[dict]:
    """Return only profiles that received a 'yes' decision in the same order."""
    filtered: List[dict] = []
    for profile, decision in zip(profiles, decisions):
        if decision == "yes":
            filtered.append(profile)
    return filtered

def main():

    try:
        with open("unstructured_profiles.json", "r", encoding="utf-8") as f:
            profiles = json.load(f)
        if not isinstance(profiles, list):
            logger.error("Input JSON must be a list of profiles.")
            sys.exit(1)
    except FileNotFoundError:
        logger.error("File not found: unstructured_profiles.json")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON: {e}")
        sys.exit(1)

    # Create batch input JSONL
    batch_input_file = "validation_batch_input.jsonl"
    create_batch_input(profiles, batch_input_file)

    # Submit batch and wait for results
    raw = process_batch(batch_input_file)
    if not raw:
        logger.error("Batch returned no output.")
        sys.exit(1)
    print(raw)

    # Extract 'yes'/'no' decisions
    decisions = extract_decisions(raw)
    if len(decisions) != len(profiles):
        logger.warning("Decision count does not match profile count; results will be truncated to the shorter length.")

    # Filter profiles by decision
    filtered = filter_profiles_by_decision(profiles, decisions)
    with open("validated_profiles.json", "w", encoding="utf-8") as f:
        json.dump(filtered, f, indent=2, ensure_ascii=False)
    logger.info(f"Wrote {len(filtered)} validated profiles to validated_profiles.json")

if __name__ == "__main__":
    main()
    