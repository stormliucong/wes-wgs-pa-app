#!/usr/bin/env python3
"""
Synthetic Patient Data Generator for WES/WGS Pre-Authorization Form
This script generates groundtruth profiles (i.e., think of completely correct submitted forms). All data is completely fictional and for testing purposes only.

Sample categories:

  label_type = 1 (PERFECT):
    - All clinical indications, and family history are relevant to the test request
    - ICD codes are consistent with clinical indication and primary diagnosis
    - CPT codes are consistent with test_type and test_configuration
    - No intentional data errors

  label_type = 2 (ERROR)
    - ICD codes are relevant to the test request
    - 2a) Invalid ICD codes - invalid icd code assigned (code does not exist)
    - 2b) CPT codes are inconsistent with test_type
    - 2c) Invalid CPT codes - code does not exist
    - 2d) Data Collection date before Prior Test Date #issue
    - 2e) Data Collection is empty

  label_type = 3 (IRRELEVANT):
    - 3a) Partially irrelevant ICD codes: original relevant ICD codes + some irrelevant ICD codes
    - 3b) Irrelevant ICD codes only 
    - 3c) Irrelevant family history

Usage:
    python generate_test_patients.py -n 50 -o test_patients.jsonl
    python generate_test_patients.py --count 100 --output bulk_test_data.jsonl
"""
import argparse
import json
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Tuple
random.seed(120)

class GroundtruthGenerator: 
    def __init__(self):
        self.first_names = {
            'Male': ['James', 'John', 'Robert', 'Michael', 'William', 'David', 'Richard', 'Joseph', 'Thomas', 'Christopher', 'Charles', 'Daniel', 'Matthew', 'Anthony', 'Mark', 'Donald', 'Steven', 'Paul', 'Andrew', 'Joshua', 'Kenneth', 'Kevin', 'Brian', 'George', 'Timothy'],
            'Female': ['Mary', 'Patricia', 'Jennifer', 'Linda', 'Elizabeth', 'Barbara', 'Susan', 'Jessica', 'Sarah', 'Karen', 'Lisa', 'Nancy', 'Betty', 'Helen', 'Sandra', 'Donna', 'Carol', 'Ruth', 'Sharon', 'Michelle', 'Laura', 'Sarah', 'Kimberly', 'Deborah', 'Dorothy']
        }
        
        self.last_names = [
            'Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis', 'Rodriguez', 
            'Martinez', 'Hernandez', 'Lopez', 'Gonzalez', 'Wilson', 'Anderson', 'Thomas', 'Taylor', 
            'Moore', 'Jackson', 'Martin', 'Lee', 'Perez', 'Thompson', 'White', 'Harris', 'Sanchez', 
            'Clark', 'Ramirez', 'Lewis', 'Robinson', 'Walker', 'Young', 'Allen', 'King', 'Wright', 
            'Scott', 'Torres', 'Nguyen', 'Hill', 'Flores', 'Green', 'Adams', 'Nelson', 'Baker', 
            'Hall', 'Rivera', 'Campbell', 'Mitchell', 'Carter', 'Roberts'
        ]
        
        self.ct_cities = [
            'Hartford', 'New Haven', 'Bridgeport', 'Stamford', 'Waterbury', 'Norwalk', 'Danbury', 
            'New Britain', 'West Hartford', 'Greenwich', 'Hamden', 'Meriden', 'Bristol', 'Manchester', 
            'West Haven', 'Milford', 'Middletown', 'Norwich', 'Shelton', 'Torrington', 'Trumbull', 
            'Glastonbury', 'Newington', 'New London', 'Enfield', 'Windsor', 'Stratford', 'East Hartford'
        ]
        
        self.street_names = [
            'Main St', 'Oak Ave', 'Park Rd', 'Church St', 'Elm St', 'Washington Ave', 'Maple St', 
            'Second St', 'School St', 'High St', 'State St', 'Broad St', 'Union St', 'Water St', 
            'Court St', 'North St', 'South St', 'West St', 'East St', 'Mill St', 'Center St', 
            'Pleasant St', 'Franklin St', 'Highland Ave', 'Spring St', 'Cedar St', 'Pine St', 
            'River Rd', 'Hill St', 'Forest Ave', 'Valley Rd', 'Meadow Ln', 'Sunset Ave'
        ]
        
        self.provider_names = [
            'Dr. Sarah Johnson', 'Dr. Michael Smith', 'Dr. Jennifer Wilson', 'Dr. David Brown', 
            'Dr. Lisa Garcia', 'Dr. Robert Miller', 'Dr. Emily Davis', 'Dr. James Rodriguez', 
            'Dr. Maria Martinez', 'Dr. Christopher Lee', 'Dr. Angela Thompson', 'Dr. William Jones', 
            'Dr. Patricia Anderson', 'Dr. Thomas Taylor', 'Dr. Nancy Moore', 'Dr. Daniel Jackson', 
            'Dr. Karen White', 'Dr. Joseph Harris', 'Dr. Susan Clark', 'Dr. Mark Lewis', 
            'Dr. Helen Robinson', 'Dr. Anthony Walker', 'Dr. Betty Young', 'Dr. Paul Allen', 
            'Dr. Sandra King', 'Dr. Matthew Wright', 'Dr. Donna Scott', 'Dr. Steven Torres'
        ]
        
        self.provider_specialties = [
            'Genetics', 'Medical Genetics', 'Neurology', 'Pediatric Genetics', 'Oncology', 
            'Cardiology', 'Endocrinology', 'Nephrology', 'Neurology', 'Pediatrics', 
            'Internal Medicine', 'Family Medicine', 'Maternal-Fetal Medicine'
        ]
        
        self.test_types = ['WES', 'WGS']
        self.test_configurations = ['Proband', 'Trio']

        self.test_cpt_map: Dict[Tuple[str, str], List[str]] = {
            ('WES', 'Proband'): ['81415'], 
            ('WES', 'Trio'): ['81415', '81416'],
            ('WGS', 'Proband'): ['81425'],
            ('WGS', 'Trio'): ['81425', '81426'],
        }
        
        self.urgency_levels = ['Routine', 'Expedited']
        
        self.specimen_types = ['Blood', 'Saliva', 'Buccal', 'Other']
        
        self.sexes = ['Male', 'Female', 'Intersex', 'Unknown']
        
        self.subscriber_relations = ['Self', 'Parent', 'Guardian', 'Other'] 
         
        self.prior_tests = ['CMA', 'Gene panel', 'Single gene']  # empty string = no prior test documented

        self.icd_code_mappings = {  
        "MCA": {
            "Q89.7": "Multiple congenital anomalies, not elsewhere classified",
            "Q89.9": "Congenital malformation, unspecified",
            "Q04.0": "Congenital malformations of corpus callosum",
            "Q04.6": "Congenital cerebral cysts",
            "Q04.9": "Unspecified congenital malformation of brain",
            "Q21.0": "Ventricular septal defect",
            "Q21.1": "Atrial septal defect",
            "Q20.0": "Common arterial truncus",
            "Q20.3": "Transposition of great vessels",
            "Q61.4": "Renal hypoplasia",
            "Q60.0": "Renal agenesis, unilateral",
            "Q60.2": "Renal dysplasia",
            "Q67.4": "Other congenital deformities of skull, face and jaw",
            "Q78.9": "Osteochondrodysplasia, unspecified",
            "Q66.89": "Other congenital deformities of feet"
        },

        "DD or ID": {
            "R62.50": "Unspecified lack of expected normal physiological development",
            "R62.0": "Delayed milestone in childhood",
            "F88": "Other disorders of psychological development",
            "F70": "Mild intellectual disability",
            "F71": "Moderate intellectual disability",
            "F72": "Severe intellectual disability",
            "F73": "Profound intellectual disability",
            "F84.2": "Rett syndrome",
        },

        "Neurological": {
            "R56.9": "Unspecified convulsions",
            "G40.919": "Epilepsy, unspecified, intractable",
            "G40.311": "Generalized idiopathic epilepsy, intractable",
            "G25.9": "Extrapyramidal and movement disorder, unspecified",
            "G25.0": "Essential tremor",
            "G25.3": "Myoclonus",
            "G24.9": "Dystonia, unspecified",
            "G24.0": "Drug-induced dystonia",
            "G24.8": "Other dystonia",
            "R27.0": "Ataxia, unspecified",
            "G11.1": "Early-onset cerebellar ataxia",
            "G11.4": "Hereditary spastic paraplegia",
            "P94.2": "Congenital hypotonia",
            "M62.81": "Muscle weakness (generalized)",
            "G71.0": "Muscular dystrophy"
        },

        "Autsim": {
            "F84.0": "Autistic disorder",
            "F84.5": "Asperger's syndrome",
            "F84.9": "Pervasive developmental disorder, unspecified",
        },

        "Red flags":{
            "F98.4": "Stereotyped movement disorders",
            "F98.8": "Other specified behavioral and emotional disorders with onset usually occurring in childhood",
            "F80.9": "Developmental disorder of speech and language, unspecified",
            "F82": "Specific developmental disorder of motor function",
            "R48.8": "Other symbolic dysfunctions (e.g., atypical social communication)",
            "R63.3": "Feeding difficulties (often present with ASD regression)",
            "R46.89": "Other symptoms and signs involving appearance and behavior",
            "R41.840": "Attention and concentration deficit",
            "R41.83": "Borderline intellectual functioning",
        },

        "Family history":{
            "Z84.81": "Family history of carrier of genetic disease",
            "Z82.0": "Family history of epilepsy",
            "Z81.8": "Family history of other mental and behavioral disorders"
        }
    }
    
    def generate_address(self) -> str:
        """Generate a realistic Connecticut address (state may later be corrupted)."""
        number = random.randint(1, 9999)
        street = random.choice(self.street_names)
        city = random.choice(self.ct_cities)
        zip_code = random.randint(6000, 6999)  # CT zip codes
        return f"{number} {street}, {city}, CT {zip_code:05d}"
    
    def generate_phone(self) -> str:
        """Generate a realistic phone number."""
        area = random.choice([203, 860, 475, 959])  # CT area codes
        exchange = random.randint(200, 999)
        number = random.randint(1000, 9999)
        return f"({area}) {exchange}-{number}"
    
    def generate_member_id(self) -> str:
        """Generate a realistic Medicaid member ID."""
        prefix = random.choice(['MCD', 'CT', 'HUS'])
        number = random.randint(100000000, 999999999)
        return f"{prefix}{number}"
    
    def generate_npi(self) -> str:
        """Generate a valid-format NPI number."""
        return str(random.randint(1000000000, 9999999999))
    
    def generate_date_of_birth(self) -> str:
        """Generate a realistic date of birth (1-30 years ago)."""
        years_ago = random.randint(1, 20)
        days_ago = random.randint(0, 365)
        birth_date = datetime.now() - timedelta(days=years_ago * 365 + days_ago)
        return birth_date.strftime('%Y-%m-%d')
    
    def generate_recent_date(self) -> str:
        """Generate a recent date (within last 30 days)."""
        days_ago = random.randint(0, 30)
        recent_date = datetime.now() - timedelta(days=days_ago)
        return recent_date.strftime('%Y-%m-%d')
    
    def choose_icd(self,category):
        """Return a random ICD-10 code from a dict-of-dict category."""
        return random.choice(list(self.icd_code_mappings[category].keys()))
    
    def generate_icd_codes(self, rationale) -> list:
        icd_codes = []
        if rationale == 1: # MCA + DD + prior_test
            mca_icd = self.choose_icd("MCA")
            ddid_icd = self.choose_icd("DD or ID")
            neuro_icd = self.choose_icd("Neurological")
            icd_codes = [mca_icd, ddid_icd, neuro_icd]
       
        elif rationale == 2: #autism + family history
            autism_icd = self.choose_icd("Autsim")
            redflag_icd = self.choose_icd("Red flags")
            fam_icd = self.choose_icd("Family history")

            icd_codes = [autism_icd, redflag_icd, fam_icd]
        
        return icd_codes

    def assign_prior_test_and_rationale(self, rationale: int, profile: Dict):
        """Populate prior test only if rationale = 1."""
        if rationale == 1:
            profile['prior_test_type'] = random.choice(self.prior_tests)  # Exclude empty option
            profile['prior_test_result'] = "negative"
            current_date = datetime.now()
            prior_test_date = current_date - timedelta(days=random.randint(30, 365))
            profile['prior_test_date'] = prior_test_date.strftime('%Y-%m-%d')  
            profile['mca'] = True
            profile['dd_id'] = True
            profile['neurological'] = True
            profile['previous_test_negative'] = True
        
        else:
            profile['autism'] = True
            profile['family_history'] = True

    def generate_testing_info(self) -> Dict:
            """Assign test_type, test_configuration, urgency, specimen_type and consistent CPT codes."""
            test_key = random.choice(list(self.test_cpt_map.keys()))
            test_type, test_config = test_key
            specimen_type = random.choice(self.specimen_types)
            cpt_codes = self.test_cpt_map[test_key]  
            urgency = random.choice(self.urgency_levels)
            return {
                'test_type': test_type,
                'test_configuration': test_config,
                'urgency': urgency,
                'specimen_type': specimen_type,
                'cpt_codes': list(cpt_codes)
            }
    @staticmethod
    def _is_leap_year(year: int) -> bool:
        """Check if a given year is a leap year."""
        return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    
    def _2a_assign_invalid_icd(self, profile: Dict[str, Any]) -> None:
        """Insert an invalid ICD code to the list"""
        invalid_icd_codes = [ 
        "Q12.345",
        "X99.9",
        "M54.5A",
        "F88.99",
        "R62.501",
        "G40.A01",
        "Q04.99X",
        "Z82.999",
        "H91.A0",
        "B25.123",
        "K21.A9",
        "P94.200",
        "M79.Z91",
        "T88.999A",
        "E11.90X",
        "L30.90Z",
        "S10.1XXZ",
        "J02.901",
        "N39.000",
        "R05.A9"
        ]
        original_icd_codes = profile.get('icd_codes', [])
        # Insert a random invalid ICD code
        invalid_code = random.choice(invalid_icd_codes)
        original_icd_codes.append(invalid_code)
        profile['icd_codes'] = original_icd_codes

    def _2b_assign_wrong_cpt(self, profile: Dict) -> None:
        """Assign test_type and test_configuration, but inconsistent CPT codes."""
        valid_cpt_codes = ['81415','81416','81417','81425','81426','81427']
        # Choose a different CPT code set
        original_cpt_codes = profile.get('cpt_codes', [])
        other_cpt_codes = [k for k in valid_cpt_codes if k not in original_cpt_codes]
        wrong_cpt = random.sample(other_cpt_codes, random.choice([1,2]))
        profile['cpt_codes'] = list(wrong_cpt)  # copy
        
    def _2c_assign_invalid_cpt(self, profile: Dict) -> None:
        """Assign invalid CPT codes to the profile."""
        invalid_cpt_codes = ['812345','814199','72555','81599','90210']
        invalid_cpt = random.sample(invalid_cpt_codes, random.choice([1,2]))
        profile['cpt_codes'] = list(invalid_cpt)  

    def _2d_assign_wrong_collection_date(self, profile: Dict) -> None: # only applies to rationale = 1
        """Assign collection date before prior test date."""
        prior_test_date_str = profile.get('prior_test_date')
        if not prior_test_date_str:
            logging.error("prior_test_date is missing or None")
            return
        try:
            prior_test_dt = datetime.strptime(prior_test_date_str, '%Y-%m-%d')
            earlier_collection_date = prior_test_dt - timedelta(days=random.randint(1, 10))
            profile['collection_date'] = earlier_collection_date.strftime('%Y-%m-%d')
        except ValueError as e:
            logging.error(f"Error parsing prior_test_date: {e}")
            profile['collection_date'] = ''  # Fallback to empty if parsing fails

    def _2e_assign_empty_collection_date(self, profile: Dict) -> None:
            """Assign empty collection date for WES/WGS."""
            profile['collection_date'] = ''

    def introduce_sample_2_errors(self, profile: Dict, sub_label: str) -> Dict:
        """
        Introduce specific data errors into the profile for negative testing.
        Used ONLY for label_type = 2 subcategories (2a, 2b, 2c, 2d, 2e).
        """
        if sub_label == "2a":
            self._2a_assign_invalid_icd(profile)
        elif sub_label == "2b":
            self._2b_assign_wrong_cpt(profile)
        elif sub_label == "2c":
            self._2c_assign_invalid_cpt(profile)
        elif sub_label == "2d":
            self._2d_assign_wrong_collection_date(profile)
        else:
            self._2e_assign_empty_collection_date(profile)
        return profile

    def add_irrelevant_info(self, subsample, profile: Dict) -> Dict:
        """
        Add some irrelevant ICD codes and family history to the profile for label_type = 3.
        a) Keep the original ICD codes and add some irrelevant ones
        b) ICD codes completely irrelevant (not for genetic testing) #irrelevant clinical features
        c) Insert irrelevant family history  
        """
        irrelevant_icd_code_mapping = {
            "chest_pain": {
                "R07.2": "Precordial pain",           
            },
            "shortness_of_breath": {
                "R06.02": "Shortness of breath (dyspnea)",
            },
            "paralysis": {
                "G81.91": "Hemiplegia, unspecified affecting right dominant side",  # Example paralytic symptom code :contentReference[oaicite:8]{index=8}
            },
            "headache": {
                "R51.9": "Headache, unspecified"
            }
        }

        # Randomly pick 2 or 3 unique irrelevant ICD codes
        all_irrelevant_codes = [
            code 
            for category_codes in irrelevant_icd_code_mapping.values() 
            for code in category_codes.keys()
        ]

        num_irrelevant = random.randint(2, 3)
        irrelevant_codes = random.sample(all_irrelevant_codes, num_irrelevant)
        if subsample == "3a":
            profile['icd_codes'].extend(irrelevant_codes)
        elif subsample == "3b":
            profile['icd_codes'] = irrelevant_codes          
        return profile
    
    def generate_groundtruth_profile(self, sample_label) -> Dict:
        sex = random.choice(self.sexes)
        first_name = random.choice(self.first_names.get(sex, self.first_names['Male']))
        last_name = random.choice(self.last_names)   
        is_self_subscriber = random.choice([True, True, True, False, False]) # 60% chance self
        rationale = random.choice([1, 2])  # 1 = MCA + DD/ID + Neuro + Prior; 2 = Autism + Red flags + Family history
        # Force rationale 1 for sample 2d so prior testing exists (needed to set an earlier collection date)
        if sample_label == "2d":
            rationale = 1
        test_info = self.generate_testing_info()

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
        
        if sample_label == "3b": # irrelevant to genetic testing, no need to assign rationale or prior test
            profile = self.add_irrelevant_info(sample_label, profile)
            return profile
        
        self.assign_prior_test_and_rationale(rationale, profile)

        if sample_label.startswith("2"):
            profile = self.introduce_sample_2_errors(profile, sample_label)
        elif sample_label.startswith("3") and sample_label != "3b":
            profile = self.add_irrelevant_info(sample_label, profile)
        return profile
 
    def generate_bulk_profiles(self, sample_label, count: int) -> List[Dict[str, Any]]:
        """Generate multiple patient profiles of a given sample type."""
        profiles = []
        for _ in range(count):
            profiles.append(self.generate_groundtruth_profile(sample_label))
        return profiles
    
    def save_as_json(self, profiles: List[Dict[str, Any]], output_file: str) -> None:
        """Save profiles as JSON format."""
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with output_path.open('w', encoding='utf-8') as f:
            json.dump(profiles, f, ensure_ascii=False, indent=2)
            f.write('\n')
        
        print(f"Generated {len(profiles)} patient profiles saved to: {output_file}")
    
    def validate_profile(self, profile: Dict[str, Any]) -> bool:
        """Validate that a generated profile meets form requirements (may fail due to intentional errors)."""
        try:
            from app.models import validate_submission, normalize_payload
            normalized = normalize_payload(profile)
            valid, errors = validate_submission(normalized)
            if not valid:
                print(f"Validation errors: {errors}")
            return valid
        except ImportError:
            print("Warning: Could not import validation functions. Skipping validation.")
            return True

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate synthetic patient data for WES/WGS pre-authorization testing')
    parser.add_argument('-o', '--output', type=str, default='test_patients_groundtruth.json', 
                        help='Output file path (default: test_patients_groundtruth.json)')
    args = parser.parse_args()

    generator = GroundtruthGenerator()

    # Generate 5 profiles for each sample category
    sample_categories = ['1', '2a', '2b', '2c', '2d', '2e', '3a', '3b', '3c']
    profiles = []

    for category in sample_categories:
        category_profiles = generator.generate_bulk_profiles(category, 5)
        profiles.extend(category_profiles)
        print(f"Generated 5 profiles for category {category}")

    # Save all profiles to JSON file
    generator.save_as_json(profiles, args.output)
