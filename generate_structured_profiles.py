import logging
import random
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Tuple


def generate_structured_profile(groundtruth: Dict) -> Dict:
    """
    Sample = 3a (partially irrelevant ICD codes)
    Sample = 3b (irrelevant ICD codes only): all relevant clinical features marked false, irrelevant features marked true 
    Sample = 3c (irrelevant family history): 
    """
    clinical_profile = {
        "relevant_clinical_features": {
            "multiple_congenital_anomalies": False,
            "global_developmental_delay_or_ID": False,
            "unexplained_neurological_symptoms": False,
            "unexplained_metabolic_phenotype": False,
            "autism_with_red_flags": False,
            "early_onset_or_multisystem_disease": False     
        },
        "irrelevant_clinical_features":{
            "chest_pain": False,
            "shortness_of_breath":False,
            "paralysis":False,
            "headache":False
        },
        "icd_codes": groundtruth.get("icd_codes", []),
        "relevant_family_history": {
            "affected_relatives": False,
            "consanguinity": False,
        },
        "irrelevant_family_history": False,
        "prior_testing": {
            "test_type": "",
            "test_date": "",
            "test_result": ""
        }
    }

    sample = groundtruth.get("sample_type", "")
    
    if groundtruth.get("mca"):
        clinical_profile["relevant_clinical_features"]["multiple_congenital_anomalies"] = True
        clinical_profile["relevant_clinical_features"]["global_developmental_delay_or_ID"] = True
        clinical_profile["relevant_clinical_features"]["unexplained_neurological_symptoms"] = True
        clinical_profile["prior_testing"]["test_type"] = groundtruth.get("prior_test_type", "")
        clinical_profile["prior_testing"]["test_date"] = groundtruth.get("prior_test_date", "")
        clinical_profile["prior_testing"]["test_result"] = "negative"
    
    if groundtruth.get("autism"):
        clinical_profile["relevant_clinical_features"]["autism_with_red_flags"] = True
        clinical_profile['relevant_family_history']["affected_relatives"] = True
        clinical_profile['relevant_family_history']["consanguinity"] = random.choice([True, False])
        

    if sample in ("3a", "3b"):
        irrelevant_icd = {
            "R07.2": "chest_pain",
            "R06.02": "shortness_of_breath",
            "G81.91": "paralysis",
            "R51.9": "headache"
        }   
        for icd_code, feature in irrelevant_icd.items():
            if icd_code in clinical_profile["icd_codes"]:
                clinical_profile["irrelevant_clinical_features"][feature] = True
    
    if sample == "3c":
        clinical_profile["irrelevant_family_history"] = True
        
    other_info = dict(list(groundtruth.items())[:24])  # Copy other fields
    complete_profile = {**other_info, **clinical_profile}

    return complete_profile

def structured_profiles_json(groundtruth_json):

    try:
        with open(groundtruth_json, "r", encoding="utf-8") as f:
            groundtruth_list = json.load(f)
    except FileNotFoundError:
        logging.error(f"File not found: {groundtruth_json}")
        return
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON: {e}")
        return

    profiles = [generate_structured_profile(groundtruth) for groundtruth in groundtruth_list]

    output_file = "structured_profiles.json"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2, ensure_ascii=False)
        logging.info(f"Structured profiles saved to {output_file}")
    except IOError as e:
        logging.error(f"Error writing to file {output_file}: {e}")

structured_profiles = structured_profiles_json("test_patients_groundtruth.json")