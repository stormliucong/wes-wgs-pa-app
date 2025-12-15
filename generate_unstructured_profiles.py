import argparse
import json
import logging
import random
from typing import Dict, List

import openai

random.seed(120)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# OpenAI API key configuration
openai.api_key = "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"


def generate_text(structured_profile: Dict) -> str:
    """Call the LLM using the existing prompt and include the structured profile for context."""
    prompt = (
        "The input dictionary represents a structured patient profile. Generate a realistic clinical note based on the following fields: "
        "relevant_clinical_features, irrelevant_clinical_features, icd_codes, relevant_family_history, irrelevant_family_history, and prior_testing. "
        "Please follow the instructions below. \n"
        "1) Write clinical indications and describe all clinical features (both relevant and irrelevant) marked true with details by referring to the ICD codes, "
        "but do not explicitly cite the ICD codes or specify whether the features are relevant or irrelevant. Also, do NOT make any conclusive statements such as, "
        "the patient has been evaluated to demonstrate multiple congenital anomalies, developmental delay or intellectual disabilities, and neurological symptoms. \n"
        "2) If any fields under relevant_clinical_features or irrelevant_clinical_features are marked false, completely ignore them and do NOT explicitly mention that the patient does not have these conditions. \n"
        "3) If the fields under relevant_family_history are marked true, generate records for affected relatives or consanguinity with details rather than a generic statement."
        "If irrelevant_family_history is marked true, generate records for affected relatives with diseases that are completely irrelevant to the patient's relevant_clinical_features. "
        "In case where both relevant and irrelevant family history are marked, mix them together without specifying if they are relevant or irrelevant. \n"
        "4) If all fields under relevant_family_history and irrelevant_family_history are marked False, leave a statement indicating no significant family history reported."
        "5) Do not mention about the WES/WGS or justify the need for testing. \n"
        "Return one text paragraph including everything and make sure that it reads like a realistic clinical note from EHR."
    )

    try:
        response = openai.chat.completions.create(
            model="gpt-5.1",
            messages=[
            {"role": "system", "content": "You are a helpful clinical assistant that converts structured data to free text clinical notes."},
            {"role": "user", "content": prompt},
            {"role": "user", "content": f"Structured profile:\n{json.dumps(structured_profile, ensure_ascii=False)}"},
            ],
            max_completion_tokens=300,
            temperature=0.7,
        )
        content = response.choices[0].message.content or ""
        return content.strip()
    except Exception as e:
        logging.error(f"Error generating free text: {e}")
        return ""

def generate_unstructured_profile(structured_profile: Dict) -> Dict:
    """Generate clinical_indication and family_history text, replacing structured clinical blocks."""
    free_text = generate_text(structured_profile)
    
    unstructured_profile = {
        k: v
        for k, v in structured_profile.items()
        if k not in {
            "relevant_clinical_features",
            "irrelevant_clinical_features",
            "relevant_family_history",
            "irrelevant_family_history",
        }
    }
    unstructured_profile["clinical_note"] = free_text
    return unstructured_profile

def generate_unstructured_profiles_json(input_file: str, output_file: str) -> None:
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            structured_profiles: List[Dict] = json.load(f)
    except FileNotFoundError:
        logging.error(f"Input file not found: {input_file}")
        return
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON from {input_file}: {e}")
        return

    unstructured = [generate_unstructured_profile(p) for p in structured_profiles]

    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(unstructured, f, indent=2, ensure_ascii=False)
        logging.info(f"Unstructured profiles saved to {output_file}")
    except IOError as e:
        logging.error(f"Error writing to file {output_file}: {e}")

generate_unstructured_profiles_json("structured_profiles.json", "unstructured_profiles.json")



