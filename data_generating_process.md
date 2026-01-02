# WES/WGS Pre-Authorization Data Generation Process

## Overview

The synthetic data generation pipeline for WES/WGS pre-authorization forms consists of three sequential stages, each implemented as a separate Python script. The pipeline is designed to generate diverse patient profiles spanning three major sample categories: 
**1. perfect profiles with no errors and irrelevant clinical information (label_type=1)**
**2. profiles with intentional errors (label_type=2)**
    2a. Invalid ICD codes
    2b. Wrong / inconsistent CPT codes
    2c. Invalid CPT codes
    2d. Correction date is earlier than prior test date
    2e. Collection date is empty
**3. profiles with irrelevant clinical information (label_type=3)**
    3a. Partially irrelevant ICD codes
    3b. Completely irrelevant ICD codes
    3c. Irrelevant family history

## Stage 1: Groundtruth Generation (groundtruth.py)

A groundtruth profile is designed to look like a successfully submitted pre-authorization form. It is first initialized as follows:
    profile = {
                'sample_type': sample_label, 
                'patient_first_name': first_name,
                'patient_last_name': last_name,
                'dob': self.generate_date_of_birth(),
                'sex': sex,
                'member_id': self.generate_member_id(),
                'patient_address': self.generate_address(),
                'subscriber_name': '' if is_self_subscriber else f"{random.choice(self.first_names['Male'] + self.first_names['Female'])} {last_name}",
                'subscriber_relation': 'Self' if is_self_subscriber else random.choice(self.subscriber_relations[1:]),
                'provider_name': random.choice(self.provider_names),
                'provider_npi': self.generate_npi(),
                'provider_phone': self.generate_phone(),
                'provider_fax': self.generate_phone(),
                'provider_address': self.generate_address(),         
                'lab_name': random.choice(['LabCorp', 'Quest Diagnostics', 'GeneDx', 'Invitae', '']),
                'lab_npi': self.generate_npi() if random.choice([True, False]) else '',
                'lab_address': self.generate_address() if random.choice([True, False]) else '',
                'test_type': test_info['test_type'],
                'test_configuration': test_info['test_configuration'],
                'cpt_codes': test_info['cpt_codes'],
                'urgency': test_info['urgency'],
                'specimen_type': test_info['specimen_type'],
                'collection_date': self.generate_recent_date(),
                'internal_test_code':"",
                'mca':"",
                'dd_id':"",
                'dysmorphic':"",
                'neurological':"",
                'metabolic':"",
                'autism':"",
                'early_onset':"",
                'previous_test_negative':"",
                'family_history':"",
                'other_details':"",
                'mn_suspected_genetic': True,
                "mn_results_influence_management": True,
                "mn_genetic_counseling": True,
                "consent_ack": True,
                'icd_codes': self.generate_icd_codes(rationale),
                'icd_descriptions': ""
            }

We predefine two different checkbox answers for rationale of testing section:
    ***rationale = 1: MCA + DD/ID + neurological simptoms + previous test is negative***
    ***rationale = 2: Autism with red flags + relevant family history***
The rationale is randomly selected and relevant clinical features will be assigned to the initialized profile (E.g., if rationale = 2, 'autism' & 'family_history' fields of the profile will be set to True). Functions are defined for each subsample category (line 275 ~ 390), and the initialized profile is updated according to the subsample (line 392 ~ 456).

## Stage 2: Structured Profile Generation (generate_structured_profiles.py)

The structured profile generation stage transforms groundtruth profiles into an intermediate structured format that explicitly categorizes clinical features and family history information into boolean fields. This is basically a patient's clinical profile initialized as follows:

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

Profile population examines the clinical flags in the groundtruth data and appropriately set boolean values. Logic is summarized as follows:

**1. When the groundtruth indicates MCA, `multiple_congenital_anomalies`, `global_developmental_delay_or_ID`, and `unexplained_neurological_symptoms` fields of the clinical profiel are updated to True, `prior_testing` section will also be updated.**

**2. When the groundtruth indicates autism, the `autism_with_red_flags flag` and `affected_relatives` under family history are set to True, and consanguinity is randomly assigned to True or False to introduce realistic variation.**

**3. For subsample type 3a and 3b where irrelevant ICD codes are involved, the system examines each ICD code in the profile against a mapping of irrelevant codes and sets the corresponding `irrelevant_clinical_features` flag to True (line 59 ~ 68).**

**4. For subsample type 3c, the `irrelevant_family_history` flag is simply set to True without further detail, allowing the LLM to fabricate appropriate but clinically unnecessary family history narratives.**

Lastly, the structured profile preserves all demographic, administrative, and test-related fields from the groundtruth by copying the first 24 key-value pairs, then merges them with the newly created clinical profile structure. 

## Stage 3: Unstructured Profile Generation (generate_unstructured_profiles.py)

The unstructured profile generation stage represents the final transformation, using OpenAI's GPT-5.1 model to convert structured boolean flags and ICD code lists into realistic free-text clinical narratives that simulate how providers actually document patient presentations. The `generate_text` function constructs carefully engineered prompts to guide the LLM's narrative generation for a given structured profile. The prompt is designed as follows:
    
    The input dictionary represents a structured patient profile. Generate a realistic clinical note based on the following fields: `relevant_clinical_features`, `irrelevant_clinical_features`, `icd_codes`, `relevant_family_history`, `irrelevant_family_history`, and `prior_testing`. "
    Please follow the instructions below.

    1. Write clinical indications and describe all clinical features (both relevant and irrelevant) marked true with details by referring to the ICD codes, but do not explicitly cite the ICD codes or specify whether the features are relevant or irrelevant. Also, do NOT make any conclusive statements such as, "the patient has been evaluated to demonstrate multiple congenital anomalies, developmental delay or intellectual disabilities, and neurological symptoms."

    2. If any fields under relevant_clinical_features or irrelevant_clinical_features are marked false, completely ignore them and do NOT explicitly mention that the patient does not have these conditions.

    3.  If the fields under relevant_family_history are marked true, generate records for affected relatives or consanguinity with details rather than a generic statement. If irrelevant_family_history is marked true, generate records for affected relatives with diseases that are completely irrelevant to the patient's relevant_clinical_features. In case where both relevant and irrelevant family history are marked, mix them together without specifying if they are relevant or irrelevant.

    4. If all fields under relevant_family_history and irrelevant_family_history are marked False, leave a statement indicating no significant family history reported.
    
    5. Do not mention about the WES/WGS or justify the need for testing.

    Return one text paragraph including everything and make sure that it reads like a realistic clinical note from EHR.

Lastly, an unstructured profile replaces the clinical features and family history in the structured profile with a single `clinical_note` field with the free text generated with the prompt above.