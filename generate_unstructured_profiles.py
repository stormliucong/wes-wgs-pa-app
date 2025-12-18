import json
import logging
import time
from typing import Dict, List
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

client = OpenAI()

def create_patient_prompt(structured_profile: Dict) -> str:
    prompt = """ The input dictionary represents a structured patient profile. Generate a realistic clinical note based on the following fields:
        relevant_clinical_features, irrelevant_clinical_features, icd_codes, relevant_family_history, irrelevant_family_history, and prior_testing.
        
        Please follow the instructions below:
        1) Write clinical indications and describe all clinical features (both relevant and irrelevant) marked true with details by referring 
        to the ICD codes, but do not explicitly cite the ICD codes or specify whether the features are relevant or irrelevant.

        2) Do NOT make any conclusive statements such as, "the patient has been evaluated to demonstrate multiple congenital anomalies,
        developmental delay or intellectual disabilities, and neurological symptoms."

        3) If any fields under relevant_clinical_features or irrelevant_clinical_features are marked false, completely ignore them and do NOT 
        explicitly mention that the patient does not have these conditions (or, just do not mention at all)."

        4) If the fields under relevant_family_history are marked true, generate records for affected relatives or consanguinity with details 
        rather than a generic statement. If irrelevant_family_history is marked true, generate records for affected relatives with diseases that are 
        completely irrelevant to the patient's relevant_clinical_features.

        5) In case where both relevant and irrelevant family history are marked, mix them together without specifying if they are relevant or irrelevant.
        If all fields under relevant_family_history and irrelevant_family_history are marked False, leave a statement indicating no significant family 
        history reported.

        6) Do not mention about WES/WGS or justify the need for testing.
        
        Example: Suppose in a structured patient profile, ONLY the multiple_congenital_anomalies, global_developmental_delay_or_ID, and unexplained_neurological_symptoms
        under relevant_clinical_history are marked True (i.e., all fields under irrelevant_clinical_features, relevant_family_history and irrelevant_family_history 
        are marked False and prior test includes a single-gene test with a negative result. The clinical note is written as:

        The patient has abnormal skull and facial shape noted since infancy, with persistent craniofacial asymmetry and atypical head contour on physical 
        examination, raising concern for an underlying disorder of cranial or skeletal development. The patient also has a history of significant delays across 
        multiple domains; he walked and talked later than expected and currently demonstrates moderate limitations in intellectual functioning and adaptive skills.
        Additionally, he has a diagnosis of focal epilepsy with impairment of consciousness and intractable seizures, with episodes characterized by focal 
        onset progressing to bilateral tonic-clonic activity and prolonged postictal confusion, despite treatment with multiple antiseizure medications.
        No significant family history is reported, and there is no known parental consanguinity. Prior genetic evaluation includes a single-gene test which was negative
        and did not identify a molecular diagnosis.

        The output one text paragraph including everything and make sure that it reads like a realistic clinical note from EHR. Below is the structured profile to use:
    """
    profile_string = json.dumps(structured_profile, separators=(',', ':'), ensure_ascii=False)
    prompt += f"\n{profile_string}\n"

    return prompt

def create_batch_input(structured_profiles: List[dict], output: str):
    
    with open(output, 'w', encoding='utf-8') as outfile:
        for i, profile in enumerate(structured_profiles):
            request_object = {
                "custom_id": f"patient_{i+1}",
                "method": "POST",
                "url": "/v1/responses",
                "body": {
                    "model": "gpt-5.1",
                    "input": create_patient_prompt(profile),
                    "max_output_tokens": 200,
                    "temperature": 0.7,
                },
            }

            json_line = json.dumps(request_object, ensure_ascii=False)
            outfile.write(json_line + '\n')

    logger.info(f"Batch input file created successfully: {output}")

def process_batch(batch_input: str) -> List[str] | None:
    try:
        upload_batch = client.files.create(file=open(batch_input, "rb"), purpose="batch")
        print("Upload ID:", upload_batch.id)

        batch_job = client.batches.create(
            input_file_id=upload_batch.id,
            endpoint="/v1/responses",
            completion_window="24h",
        )
        print("Batch ID:", batch_job.id)

        while True:
            batch = client.batches.retrieve(batch_job.id)
            print(f"Current batch status: {batch.status}")         
            if batch.status in ["completed", "failed", "cancelled", "expired"]:
                logger.info(f"Batch job finished with status: {batch.status}")
                break
            time.sleep(30)  # Wait for 30 seconds before checking again

        if batch.status == "completed":
            output_file_id = getattr(batch, "output_file_id", None)
            if output_file_id is None:
                logger.error("Batch completed but output_file_id is None")
                return None
            raw_responses = client.files.content(output_file_id).text

            clinical_notes = []
            for line in raw_responses.strip().split('\n'):
                result = json.loads(line)
                note = result.get('response', {}).get('body', {}).get('output', [''])[0]
                clinical_notes.append(note)

            return clinical_notes
    
    except Exception as e:
        logger.error(f"Error downloading or parsing results: {e}")

def create_unstructured_profiles(structured_profiles: List[dict], clinical_notes: List[str], output_path: str = 'unstructured_profile.json'):
    unstructured_profiles = []
    for profile, note in zip(structured_profiles, clinical_notes):
        unstructured_profile = {key: value for key, value in profile.items() 
                                if key not in 
                                ['relevant_clinical_features', 'irrelevant_clinical_features', 'relevant_family_history',
                                 'irrelevant_family_history']}
        unstructured_profile["clinical_note"] = note
        unstructured_profiles.append(unstructured_profile)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(unstructured_profiles, f, indent=2, ensure_ascii=False)

def main():
    try:
        with open("structured_profiles.json", "r", encoding="utf-8") as f:
            structured_profiles = json.load(f)
    except FileNotFoundError:
        logging.error(f"File not found: test_patients_groundtruth.json")
        return
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON: {e}")
        return

    batch_input_file = "batch_input.jsonl"

    create_batch_input(structured_profiles, batch_input_file)
    clinical_notes = process_batch(batch_input_file)
    if clinical_notes is None:
        logger.error("No clinical notes returned from batch processing.")
        return
    create_unstructured_profiles(structured_profiles, clinical_notes, output_path='unstructured_profile.json')

main()