import argparse
import json
import logging
import time
from typing import Dict, List, Optional
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

client = OpenAI()

def create_prompt_dict(profile: Dict) -> dict:
    # Create a copy of the input profile with only the required fields
    key_fields = ['sample_type', 'patient_first_name', 'patient_last_name', 'dob', 'sex', 
                  'mca', 'dd_id', 'dysmorphic', 'neurological', 'metabolic', 'autism', 'early_onset', 'previous_test_negative',
                  'family_history', 'icd_codes','prior_test_type', 'prior_test_result']
    input_dict = {}
    for key in key_fields:
        value = profile.get(key)
        if value is not None:
            input_dict[key] = value
    return input_dict

def create_patient_prompt(input_dict: Dict) -> str:
    prompt = """ The input dictionary at the end represents a patient's clinical profile. Generate a realistic clinical note based on this profile 
        at the end and follow the instructions below carefully: 
        1) Refer to the conditions indicated by the ICD codes for descriptive details, but do not explicitly cite the ICD codes themselves.
        2) Weave the clinical indications into a narrative. Describe the patient's phenotypes and symptoms naturally using varied language. 
        Avoid introductory lists or phrases like "The patient is evaluated for X, Y, and Z." Instead, integrate details using phrases such as 
        "Since infancy...", "History is notable for...", or "Clinical concerns include..."
        3) If family_history is marked true, generate records for affected relatives and/or consanguinity with details.Provide details 
        such as the relative's relationship and condition.
        4) If any of the mca, dd_id, dysmorphic, neurological, metabolic, autism, early_onset flags are False, completely ignore them
        and do not refer to them in any way. Do NOT state their absence.
        5) If sample_type is "3c", write family history details that are medically plausible but unrelated to the patient's phenotypes.
        If family_history is also set to true, mix both relevant and irrelevant family history details. Integrate these details naturally, without 
        labeling them as relevant / irrelevant or explaining their relation to the presentation.
        6) If prior_test_type and prior_test_result are provided, include a brief summary of prior genetic testing and its outcome.
        7) Return a single paragraph of no more than 180 words, ensure the clinical note is coherent and reads like a real clinical document.  
        Input Dictionary:
    """
    profile_string = json.dumps(input_dict, separators=(',', ':'), ensure_ascii=False)
    prompt += f"\n{profile_string}\n"
    return prompt

def create_batch_input(structured_profiles: List[dict], output: str):
    with open(output, 'w', encoding='utf-8') as outfile:
        for i, profile in enumerate(structured_profiles):
            # Restrict prompt to key fields for consistency
            prompt_dict = create_prompt_dict(profile)
            request_object = {
                "custom_id": f"patient_{i+1}",
                "method": "POST",
                "url": "/v1/responses",
                "body": {
                    "model": "gpt-5.1",
                    "input": create_patient_prompt(prompt_dict),
                    "max_output_tokens": 300,
                    "temperature": 0.7,
                },
            }

            json_line = json.dumps(request_object, ensure_ascii=False)
            outfile.write(json_line + '\n')

    logger.info(f"Batch input file created successfully: {output}")

def process_batch(batch_input: str) -> Optional[List[str]]:
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
            time.sleep(30)  # Wait for 30 seconds before checking again

        if batch.status == "completed":
            output_file_id = getattr(batch, "output_file_id", None)
            if output_file_id is None:
                logger.error("Batch completed but output_file_id is None")
                return None
            raw = client.files.content(output_file_id)
            raw_text = getattr(raw, "text", None)
            if raw_text is None:
                try:
                    raw_text = raw.read().decode("utf-8")
                except Exception:
                    logger.error("Unable to read batch output content")
                    return None
            return raw_text.strip().split('\n')
           
    except Exception as e:
        logger.error(f"Error processing the batch: {e}")

def extract_clinical_notes(raw_responses):
    clinical_notes = []
    for line in raw_responses:
        line = line.strip()
        if not line:
            continue
        try:
            result = json.loads(line)
        except json.JSONDecodeError:
            clinical_notes.append("")
            continue

        output = result.get("response").get("body").get("output")
        content = output[0].get("content")
        clinical_note = content[0].get("text")
        clinical_notes.append(clinical_note)

    return clinical_notes
    
def create_unstructured_profiles(groundtruth_profiles: List[dict], clinical_notes: List[str], output_path: str = 'unstructured_profiles.json'):
    unstructured_profiles = []
    for groundtruth_profile, note in zip(groundtruth_profiles, clinical_notes):
        unstructured_profile = {key: value for key, value in groundtruth_profile.items() 
                                if key not in 
                                ['mca', 'dd_id', 'dysmorphic', 'neurological', 'metabolic', 
                                 'autism', 'early_onset', 'previous_test_negative', 'family_history']}
        unstructured_profile["clinical_note"] = note
        unstructured_profiles.append(unstructured_profile)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(unstructured_profiles, f, indent=2, ensure_ascii=False)
    logger.info(f"Wrote {len(unstructured_profiles)} profiles to {output_path}")

def main():
    try:
        with open("test_patients_groundtruth.json", "r", encoding="utf-8") as f:
            groundtruth_profiles = json.load(f)
        if not isinstance(groundtruth_profiles, list):
            logger.error("Input JSON must be a list of patient profiles.")
            return
    except FileNotFoundError:
        logging.error(f"File not found: test_patients_groundtruth.json")
        return
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON: {e}")
        return
    
    batch_input_file = "batch_input.jsonl"
    create_batch_input(groundtruth_profiles, batch_input_file)
    batch_output = process_batch(batch_input_file)
    clinical_notes = extract_clinical_notes(batch_output)
    if clinical_notes is None:
        logger.error("No clinical notes returned from batch processing.")
        return
    create_unstructured_profiles(groundtruth_profiles, clinical_notes, output_path='unstructured_profiles.json')

main()