import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
client = OpenAI()

def profile_key(profile: Dict) -> str:
    patient_id = profile.get("patient_id")
    if patient_id:
        return str(patient_id)
    fallback = (
        profile.get("sample_type"),
        profile.get("patient_first_name"),
        profile.get("patient_last_name"),
        profile.get("patient_dob"),
    )
    return json.dumps(fallback, separators=(',', ':'), ensure_ascii=False)

def load_existing_profiles(output_path: str) -> List[Dict]:
    output_file = Path(output_path)
    if not output_file.exists() or output_file.stat().st_size == 0:
        return []

    with output_file.open('r', encoding='utf-8') as f:
        existing_content = json.load(f)
    if not isinstance(existing_content, list):
        raise ValueError(f"Existing output must be a JSON list: {output_path}")
    return existing_content

def filter_missing_profiles(all_samples: List[Dict], existing_profiles: List[Dict]) -> List[Dict]:
    existing_keys = {profile_key(profile) for profile in existing_profiles}
    return [profile for profile in all_samples if profile_key(profile) not in existing_keys]

def create_prompt_dict(profile: Dict) -> dict:
    # Create a copy of the input profile with only the required fields
    key_fields = ['sample_type', 'patient_first_name', 'patient_last_name', 'patient_dob', 'sex', 
                  'mca', 'dd_id', 'dysmorphic', 'neurological', 'metabolic', 'autism', 'early_onset',
                  'family_history', 'consanguinity', 'icd_codes','secondary_icd_codes', 'prior_test_type', 
                  'prior_test_result', 'prior_test_date']
    input_dict = {}
    for key in key_fields:
        value = profile.get(key)
        if value is not None and value is not False:
            input_dict[key] = value
    return input_dict

def create_user_prompt(input_dict: Dict) -> str:
    prompt = """ 1) Clinical description: Use the provided icd_codes strictly as the source defining what may be described in the clinical note. 
    Each major clinical feature must be directly supported by one or more of the provided ICD codes, and descriptions must remain within the semantic 
    scope of each code. If an ICD code represents a symptom or sign (e.g.,codes in the R-category), describe only observable features and do not 
    upgrade these findings into a formal diagnosis unless supported by other ICD codes. If an ICD code represents a specific diagnosis or named 
    condition (e.g., congenital malformations or defined metabolic disorders), describe with specificity encoded by the ICD code and do NOT 
    generalize it into a broader category. Do NOT state the ICD codes explicitly in the note. 
    2) If the metabolic flag is true, describe with clinically interpretable results, such as the named analyte, direction 
    and magnitude of abnormality, and whether the finding is persistent or episodic (for example, chronically elevated phenylalanine 
    levels with dietary sensitivity). You may also generate specific lab results as supporting evidence. Do not use vague or placeholder 
    language such as “abnormal labs,” “blood chemistry findings,” or nonspecific “laboratory abnormalities.” 
    3) If the dysmorphic flag is true, explain with 1~2 concrete descriptors rather than a broad statement.
    4) Family history: If family_history is true, generate records for affected relatives and/or consanguinity with details. Provide details 
    such as the relative's relationship and specific conditions. If consanguinity is true, explicitly describe the parents’ actual biological 
    relationship (for example, “the parents are first cousins”) rather than using vague language such as “biologically related”.
    5) Prior testing: If prior_test_type, prior_test_result, and prior_test_date are present, include a brief factual summary of the test, date, 
    and result only.
    6) Age calculation: Calculate the patient’s current age accurately using today’s date. If it is absent, do not mention age.
    7) Language: Avoid lists, headings, or formulaic expressions when making clinical descriptions (e.g., “The patient presents with…”). Use natural 
    clinical phrasing such as “History is notable for…,” “Since early childhood…,” or “Clinical concerns include…”. Use concrete descriptions and avoid 
    non-informative or defensive phrasing such as “no documented evidence of…” and “otherwise unremarkable” unless uncertainty is clinically meaningful. 
    Clearly describe symptom type, pattern, and functional impact (e.g., frequency, severity, triggers, effect on school or daily activities). Avoid 
    generic terms like “issues”, “concerns” or “abnormalities” without qualification.
    8) Format: Generate one paragraph of at least 160 words and no more than 200 words for the primary clinical description (including symtoms/phenotypes 
    and family history/prior test). If the sample type is 3a where secondary_icd_codes list also provided, generate a separate paragraph indicated as secondary 
    medical issues or histories of no more than 100 words. The note should read like a real specialist clinical document, suitable for chart review.
    9) Realism: Do not make extra interpretation or imply any causations between co-existing conditions. Avoid vague or placeholder laboratory language. 
    Do not include assessment plans, recommendations, or speculative commentary beyond what the data supports.

    Input dictionary:
    """
    profile_string = json.dumps(input_dict, separators=(',', ':'), ensure_ascii=False)
    prompt += f"\n{profile_string}\n"
    return prompt

def create_batch_input(structured_profiles: List[dict], output: str):
    system_prompt = """You are an experienced medical scribe tasked with generating a concise, clinically realistic narrative note 
    for a patient encounter. The input dictionary at the end defines the patient’s clinical profile. Follow all rules below strictly."""

    with open(output, 'w', encoding='utf-8') as outfile:
        for i, profile in enumerate(structured_profiles):
            prompt_dict = create_prompt_dict(profile)
            body = {
                "model": "gpt-5.2",
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": create_user_prompt(prompt_dict)}
                ],
                "max_output_tokens": 400,
                "temperature": 0.7,
            }

            request_object = {
                "custom_id": f"patient_{i+1}",
                "method": "POST",
                "url": "/v1/responses",
                "body": body,
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
                
def create_unstructured_profiles(
    all_samples: List[dict],
    clinical_notes: List[str],
    output_path: str = 'unstructured_profiles.json',
    existing_profiles: Optional[List[Dict]] = None,
):
    output_file = Path(output_path)
    existing_profiles = existing_profiles if existing_profiles is not None else load_existing_profiles(output_path)

    existing_keys = {profile_key(p) for p in existing_profiles}
    unstructured_profiles = []
    for groundtruth_profile, note in zip(all_samples, clinical_notes):
        key = profile_key(groundtruth_profile)
        if key in existing_keys:
            continue
        unstructured_profile = {key: value for key, value in groundtruth_profile.items() 
                                if key not in 
                                ['mca', 'dd_id', 'dysmorphic', 'neurological', 'metabolic', 'autism', 
                                 'early_onset', 'previous_test_negative', 'family_history', 'consanguinity']}
        unstructured_profile["clinical_note"] = note
        unstructured_profiles.append(unstructured_profile)
        existing_keys.add(key)

    combined_profiles = existing_profiles + unstructured_profiles
    with output_file.open('w', encoding='utf-8') as f:
        json.dump(combined_profiles, f, indent=2, ensure_ascii=False)
    logger.info(
        f"Wrote {len(unstructured_profiles)} new profiles to {output_path} "
        f"(total: {len(combined_profiles)})"
    )

if __name__ == "__main__":
    try:
        with open("all_samples.json", "r", encoding="utf-8") as f:
            groundtruth_profiles = json.load(f)
        if not isinstance(groundtruth_profiles, list):
            logger.error("Input JSON must be a list of patient profiles.")
            sys.exit(1)
    except FileNotFoundError:
        logger.error(f"File not found: all_samples.json")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON: {e}")
        sys.exit(1)

    output_path = "unstructured_profiles.json"
    try:
        existing_profiles = load_existing_profiles(output_path)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Error reading existing {output_path}: {e}")
        sys.exit(1)

    missing_profiles = filter_missing_profiles(groundtruth_profiles, existing_profiles)
    if not missing_profiles:
        logger.info("No new profiles to process. unstructured_profiles.json is already up to date.")
        sys.exit(0)
    logger.info(f"Found {len(missing_profiles)} new profiles to generate clinical notes for.")
    
    batch_input_file = "batch_input.jsonl"
    create_batch_input(missing_profiles, batch_input_file)
    batch_output = process_batch(batch_input_file)
    if batch_output is None:
        logger.error("No batch output returned from processing.")
        sys.exit(1)
    clinical_notes = extract_clinical_notes(batch_output)
    if clinical_notes is None:
        logger.error("No clinical notes returned from batch processing.")
        sys.exit(1)
    create_unstructured_profiles(
        missing_profiles,
        clinical_notes,
        output_path=output_path,
        existing_profiles=existing_profiles,
    )

