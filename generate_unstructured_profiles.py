import argparse
import json
import logging
import random
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
                  'mca', 'dd_id', 'dysmorphic', 'neurological', 'metabolic', 'autism', 'early_onset',
                  'family_history', 'icd_codes','prior_test_type', 'prior_test_result', 'prior_test_date']
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
        5) If sample_type is "3c", ALWAYS write family history details that are medically plausible but unrelated to the patient's phenotypes,
        regardless of whether family_history is true or false. If family_history is also set to true, mix both relevant and irrelevant family history details. 
        Integrate these details naturally, without labeling them as relevant / irrelevant or explaining their relation to the presentation.
        6) If prior_test_type, prior_test_result, and prior_test_date values are provided, generate a brief summary of the prior genetic testing including both 
        date and outcome. If they are not provided, do not mention anything about prior test at all.
        7) Make sure to calculate the patient's age correctly (i.e., from the date of birth (dob) and the current date). If dob is not provided, do not mention age.
        8) Return a single paragraph of no more than 180 words, ensure the clinical note is coherent and reads like a real-world clinical document.  
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

        def _pick_output_file_id(b) -> Optional[str]:
            for key in ("output_file_id", "response_file_id", "result_file_id"):
                fid = getattr(b, key, None)
                if fid:
                    return fid
            for key in ("output_file_ids", "response_file_ids", "result_file_ids"):
                fids = getattr(b, key, None)
                if fids and isinstance(fids, (list, tuple)) and fids[0]:
                    return fids[0]
            return None

        if batch.status == "completed":
            output_file_id = _pick_output_file_id(batch)
            if output_file_id is None:
                err_id = getattr(batch, "error_file_id", None)
                if err_id:
                    try:
                        err_raw = client.files.content(err_id)
                        err_text = getattr(err_raw, "text", None)
                        if err_text is None:
                            err_text = err_raw.read().decode("utf-8")
                        logger.error("Batch completed but no output file id. Error file content: %s", err_text[:2000])
                    except Exception as ex:
                        logger.error("Batch completed without outputs and failed to read error file: %s", ex)
                else:
                    logger.error("Batch completed but could not locate any output file id field (API shape change?)")
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
    
def _2a_assign_invalid_icd(profile: Dict):
        """Insert an invalid ICD code to the list"""
        invalid_icd_codes = {
            "neurological": {
                "G40.419": "G40.410",
                "R25.2": "R25.20",
                "R27.0": "R270",
                "P94.2": "P94.20",
                "R56.9": "R56.90"
            },
            "dd_id": {
                "R62.50": "R62.500",
                "F71": "F7.1",
                "F72": "F7.2",
                "R41.840": "R418.40"
            },
            "mca": {
                "Q21.1": "Q2.11",
                "Q22.2": "Q222",
                "Q61.4": "Q61.40",
                "Q66.89": "Q66.890",
                "Q04.0": "Q4.00",
                "Q39.1": "Q39.10"
            },
            "dysmorphic": {
                "Q87.0": "Q8.70",
                "Q67.4": "Q6.74",
                "Q10.3": "Q10.30",
                "Q17.0": "Q17.00"
            },
            "metabolic": {
                "E70.20": "E7.02",
                "E73.0": "E73.00",
                "E88.40": "E88.400",
                "E87.2": "E87.02"
            },
        }
    
        original_icd_codes = profile.get('icd_codes', [])
        if not original_icd_codes:
            logging.warning("No ICD codes present to corrupt for 2a")
            return

        # Try to replace one of the existing codes with its invalid counterpart
        replaced = False

        # First, attempt on a random chosen code
        candidate = random.choice(original_icd_codes)
        for category_map in invalid_icd_codes.values():
            if candidate in category_map:
                invalid_code = category_map[candidate]
                # Replace in-place to preserve order
                idx = profile['icd_codes'].index(candidate)
                profile['icd_codes'][idx] = invalid_code
                replaced = True
                break

        if not replaced:
            logging.warning("No invalid replacement found for any ICD code in profile")
                
def create_unstructured_profiles(all_samples: List[dict], clinical_notes: List[str], output_path: str = 'unstructured_profiles.json'):
    unstructured_profiles = []
    for groundtruth_profile, note in zip(all_samples, clinical_notes):
        unstructured_profile = {key: value for key, value in groundtruth_profile.items() 
                                if key not in 
                                ['mca', 'dd_id', 'dysmorphic', 'neurological', 'metabolic', 
                                 'autism', 'early_onset', 'previous_test_negative', 'family_history']}
        unstructured_profile["clinical_note"] = note
        
        if unstructured_profile['sample_type'] == "2a":
            _2a_assign_invalid_icd(unstructured_profile)     
        unstructured_profiles.append(unstructured_profile)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(unstructured_profiles, f, indent=2, ensure_ascii=False)
    logger.info(f"Wrote {len(unstructured_profiles)} profiles to {output_path}")

def main():
    try:
        with open("all_samples.json", "r", encoding="utf-8") as f:
            groundtruth_profiles = json.load(f)
        if not isinstance(groundtruth_profiles, list):
            logger.error("Input JSON must be a list of patient profiles.")
            return
    except FileNotFoundError:
        logging.error(f"File not found: all_samples.json")
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