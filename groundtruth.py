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
    - 2d) Data Collection date before Prior Test Date
    - 2e) Data Collection date is empty

  label_type = 3 (IRRELEVANT):
    - 3a) Partially irrelevant ICD codes: original relevant ICD codes + some irrelevant ICD codes
    - 3b) Irrelevant ICD codes only 
    - 3c) Irrelevant family history
"""
import argparse
import json
import logging
import random
from datetime import datetime, timedelta
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Any, Tuple
random.seed(120)

class GroundtruthGenerator: 
    def __init__(self):
        self.first_names = {
            'Male': [
                'James', 'John', 'Robert', 'Michael', 'William', 'David', 'Richard', 'Joseph', 'Thomas',
                'Christopher', 'Charles', 'Daniel', 'Matthew', 'Anthony', 'Mark', 'Donald', 'Steven',
                'Paul', 'Andrew', 'Joshua', 'Kenneth', 'Kevin', 'Brian', 'George', 'Timothy',
                'Edward', 'Jason', 'Jeffrey', 'Ryan', 'Jacob', 'Gary', 'Nicholas', 'Eric', 'Stephen',
                'Larry', 'Justin', 'Scott', 'Brandon', 'Benjamin', 'Adam', 'Samuel', 'Gregory',
                'Patrick', 'Alexander', 'Jonathan', 'Tyler', 'Zachary', 'Peter', 'Aaron'
            ],
            'Female': [
                'Mary', 'Patricia', 'Jennifer', 'Linda', 'Elizabeth', 'Barbara', 'Susan', 'Jessica',
                'Sarah', 'Karen', 'Lisa', 'Nancy', 'Betty', 'Helen', 'Sandra', 'Donna', 'Carol',
                'Ruth', 'Sharon', 'Michelle', 'Laura', 'Sarah', 'Kimberly', 'Deborah', 'Dorothy',
                'Amanda', 'Melissa', 'Stephanie', 'Rebecca', 'Shirley', 'Cynthia', 'Angela', 'Brenda',
                'Pamela', 'Nicole', 'Christina', 'Katherine', 'Theresa', 'Julie', 'Megan', 'Rachel',
                'Victoria', 'Diane', 'Alice', 'Janet', 'Christine', 'Maria', 'Monica'
            ]
        }
        
        self.last_names = [
            'Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis', 'Rodriguez',
            'Martinez', 'Hernandez', 'Lopez', 'Gonzalez', 'Wilson', 'Anderson', 'Thomas', 'Taylor',
            'Moore', 'Jackson', 'Martin', 'Lee', 'Perez', 'Thompson', 'White', 'Harris', 'Sanchez',
            'Clark', 'Ramirez', 'Lewis', 'Robinson', 'Walker', 'Young', 'Allen', 'King', 'Wright',
            'Scott', 'Torres', 'Nguyen', 'Hill', 'Flores', 'Green', 'Adams', 'Nelson', 'Baker',
            'Hall', 'Rivera', 'Campbell', 'Mitchell', 'Carter', 'Roberts', 'Phillips', 'Evans',
            'Turner', 'Parker', 'Collins', 'Edwards', 'Stewart', 'Morris', 'Rogers', 'Reed',
            'Cook', 'Morgan', 'Bell', 'Murphy', 'Bailey', 'Cooper', 'Richardson', 'Cox', 'Howard',
            'Ward', 'Peterson', 'Gray', 'Ramsey', 'Price', 'Bennett', 'Wood', 'Barnes', 'Ross',
            'Henderson', 'Coleman', 'Jenkins', 'Perry'
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

        self.lab_test_code_map = {
            "GeneDx":{
                "WES":{
                    "Regular":{"Proband":"561b", "Duo": "561e", "Trio":"561a"},
                    "Expedited":{"Proband":"896b", "Duo":"896e", "Trio":"896a"}
                },
                "WGS":{
                    "Regular":{"Proband":"J744b", "Duo": "J744e", "Trio":"J744a"},
                    "Expedited":{"Proband":"TH78b", "Duo":"TH78e", "Trio":"TH78a"}
                }
            },
            "Invitae":{
                "WES":{
                    "Regular":{"Proband":"80001", "Duo": "80002", "Trio":"80003"},
                    "Expedited":{"Proband":"80001", "Duo":"80002", "Trio":"80003"}   
                }
            },
            "LabCorp":{
                "WES":{
                    "Regular":{"Proband":"620024", "Duo": "620023", "Trio":"620022"},
                    "Expedited":{"Proband":"620024", "Duo":"620024", "Trio":"620024"}
                },
                "WGS":{
                    "Regular":{"Proband":"WGS003", "Duo": "WGS008", "Trio":"WGS001"},
                    "Expedited":{"Proband":"WGS003X", "Duo":"WGS008X", "Trio":"WGS001X"}
                }
            },
            "Ambry":{
                "WES":{
                    "Regular":{
                        "Proband":"9993",   # ExomeNext-Proband
                        "Duo":"9991",       # ExomeNext-Duo
                        "Trio":"9995"      # ExomeNext-Trio
                    },
                    "Expedited":{
                        "Proband":"9999R",  # ExomeNext-Rapid (used for rapid WES)
                        "Duo":"9999R",
                        "Trio":"9999R"
                    }
                },
                "WGS":{}
            }
        }
        
        self.urgency_levels = ['Regular', 'Expedited']
        
        self.specimen_types = ['Blood', 'Saliva', 'Buccal']
        
        self.sexes = ['Male', 'Female']
        
        self.subscriber_relations = ['Self', 'Parent', 'Guardian', 'Other'] 
         
        self.prior_tests = ['CMA', 'Gene panel', 'Single gene']  # empty string = no prior test documented

        self.icd_code_mapping = {
            "neurological": {
                "G40.419": "Other generalized epilepsy and epileptic syndromes, intractable, without status epilepticus",
                "R27.0": "Ataxia, unspecified",
                "P94.2": "Congenital hypotonia",
                "R56.9": "Unspecified convulsions"
            },
            "dd_id": {
                "R62.50": "Unspecified lack of expected normal physiological development",
                "F71": "Moderate intellectual disability",
                "F72": "Severe intellectual disability",
                "R41.840": "Cognitive communication deficit"
            },
            "early_onset_progressive": {
                "R41.840": "Cognitive communication deficit (for regression)",
                "R79.89": "Other specified abnormal findings of blood chemistry (for deterioration)",
                "R62.51": "Failure to thrive (adult) (for growth faltering)"
            },
            "mca": {   # Structural or functional defects present at birth          
                "Q21.1": "Atrial septal defect",
                "Q22.2": "Congenital malformation of pulmonary valve",               
                "Q61.4": "Renal hypoplasia",              
                "Q66.89": "Other congenital deformities of feet",                 
                "Q04.0": "Congenital malformations of corpus callosum",
                "Q39.1": "Atresia of esophagus", 
                "Q67.4": "Other congenital deformities of skull, face and jaw", 
                "Q10.3": "Other congenital malformations of eyelid",    
                "Q17.0": "Accessory auricle"
            },
            "dysmorphic": {   # Unusual physical features
                "Q87.0": "Congenital malformation syndromes predominantly affecting facial appearance",  
            },
            "metabolic": {
                "E70.20": "Disorders of tyrosine metabolism",
                "E73.0": "Congenital lactase deficiency",
                "E88.40": "Disorder of mitochondrial metabolism, unspecified",
                "R79.89": "Other specified abnormal findings of blood chemistry",
                "E87.2": "Acidosis"
            },
            "family_history":{
                "Z82.0": "Family history of epilepsy and other diseases of the nervous system",
                "Z83.4":  "Family history of metabolic disorders"
            }
        }
        
        self.irrelevant_icd_code_mapping = {
            "T20.00XA": "burn",
            "T36.0X1A": "poisoning",
            "S93.401A": "sprain",
            "S06.0X0A": "concussion",
            "S01.01XA": "laceration"
        }

        self.sample_categories = {'1':5, '2a':5, '2b':5, '2c':5, '2d':5, '2e':5, '3a':5, '3b':5, '3c':5}
    
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
        """Generate a realistic date of birth (3-18 years old)."""
        years_ago = random.randint(3, 18)
        days_ago = random.randint(0, 365)
        birth_date = datetime.now() - timedelta(days=years_ago * 365 + days_ago)
        return birth_date.strftime('%Y-%m-%d')
    
    def generate_recent_date(self) -> str:
        """Generate a recent date (within last 30 days)."""
        days_ago = random.randint(0, 30)
        recent_date = datetime.now() - timedelta(days=days_ago)
        return recent_date.strftime('%Y-%m-%d')
    
    def pick_icd_code(self,phenotype:str):
        """Pick a random ICD code from the given phenotype category."""
        codes = list(self.icd_code_mapping.get(phenotype, {}).keys())
        if phenotype == 'mca': 
            k = min(len(codes), random.randint(2, 3))  # For MCA, pick more than one ICD code from the list
            return random.sample(codes, k)
        return random.choice(codes)
    
    def generate_icd_codes(self, rationale: int) -> list:
        """Generate ICD codes based on the rationale."""
        icd_codes = []
        phenotypes = []
        if rationale == 1: 
            phenotypes = ["mca", "dd_id", "dysmorphic"] # prior testing negative
        else:
            phenotypes = ["metabolic", "neurological"] # family history
        
        for phenotype in phenotypes:
            code = self.pick_icd_code(phenotype)
            if isinstance(code, list):
                icd_codes.extend(code)
            else:
                icd_codes.append(code)
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
            profile['dysmorphic'] = True
            profile['previous_test_negative'] = True
        
        else:
            profile['metabolic'] = True
            profile['neurological'] = True
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

    def introduce_sample_2_errors(self, profile: Dict, sub_label: str):
        """
        Introduce specific data errors into the profile for negative testing.
        Used ONLY for label_type = 2 subcategories (2a, 2b, 2c, 2d, 2e).
        """    
        if sub_label == "2b":
            self._2b_assign_wrong_cpt(profile)
        elif sub_label == "2c":
            self._2c_assign_invalid_cpt(profile)
        elif sub_label == "2d":
            self._2d_assign_wrong_collection_date(profile)
        elif sub_label == "2e":
            self._2e_assign_empty_collection_date(profile)

    def reset_profile_for_3b(self, profile: Dict):        
        for key in ('mca', 'dd_id', 'dysmorphic', 'neurological', 'metabolic', 'family_history', 'previous_test_negative'):
            profile[key] = False
        for key in ('prior_test_type', 'prior_test_result', 'prior_test_date'):
            profile.pop(key, None)
    
    def _3_irrelevant_info(self, label, profile: Dict):
        """
        Add some irrelevant ICD codes and family history to the profile for label_type = 3.
        a) Keep the original ICD codes and add some irrelevant ones
        b) ICD codes completely irrelevant (not for genetic testing) #irrelevant clinical features
        c) Irrelevant family history only
        """
        # Randomly pick 2 or 3 unique irrelevant ICD codes
        all_irrelevant_codes = list(self.irrelevant_icd_code_mapping.keys())
        num_irrelevant = random.randint(2, 3)
        irrelevant_codes = random.sample(all_irrelevant_codes, num_irrelevant)
        if label == "3a":
            profile['icd_codes'].extend(irrelevant_codes)
        if label == "3b":
            profile['icd_codes'] = irrelevant_codes
            self.reset_profile_for_3b(profile)    
       
    def generate_groundtruth_profile(self) -> Dict:
        sex = random.choice(self.sexes)
        first_name = random.choice(self.first_names.get(sex, self.first_names['Male']))
        last_name = random.choice(self.last_names)   
        is_self_subscriber = random.choice([True, True, True, False, False]) # 60% chance self
        rationale = random.choice([1, 2])

        # Assign lab and internal test code based on test_info
        lab_name = random.choice(['LabCorp', 'GeneDx', 'Invitae'])
        test_info = self.generate_testing_info()
        test_type = test_info['test_type']
        urgency = test_info['urgency']
        config = test_info['test_configuration']
        
        # Get internal test code from lab_test_code_map
        internal_test_code = self.lab_test_code_map.get(lab_name, {}).get(test_type, {}).get(urgency, {}).get(config, "")

        # Force rationale 1 for sample 2d so prior testing exists (needed to set an earlier collection date)
        
        profile = {
            'patient_id': f"PAT-{random.randint(1000, 9999)}",
            'patient_first_name': first_name,
            'patient_last_name': last_name,
            'dob': self.generate_date_of_birth(),
            'sex': sex,
            'member_id': self.generate_member_id(),
            'patient_address': self.generate_address(),
            'subscriber_name': f"{random.choice(self.first_names['Male'] + self.first_names['Female'])} {last_name}",
            'subscriber_relation': random.choice(self.subscriber_relations[1:]),
            'provider_name': random.choice(self.provider_names),
            'provider_npi': self.generate_npi(),
            'provider_phone': self.generate_phone(),
            'provider_fax': self.generate_phone(),
            'provider_address': self.generate_address(),         
            'lab_name': lab_name,
            'lab_npi': self.generate_npi(),
            'lab_address': self.generate_address(),
            'test_type': test_type,
            'test_configuration': config,
            'cpt_codes': test_info['cpt_codes'],
            'urgency': urgency,
            'specimen_type': test_info['specimen_type'],
            'collection_date': self.generate_recent_date(),
            'internal_test_code':internal_test_code,
            'mca': False,
            'dd_id': False,
            'dysmorphic': False,
            'neurological': False,
            'metabolic': False,
            'autism': False,
            'early_onset': False,          
            'previous_test_negative': False,
            'family_history': False,
            'icd_codes': [],
            'icd_descriptions': ""
        }
         
        self.assign_prior_test_and_rationale(rationale, profile)
        profile["icd_codes"] = self.generate_icd_codes(rationale)
        return profile
    
    def generate_bulk_groundtruth_profiles(self, count: int) -> List[Dict[str, Any]]:
        """Generate multiple patient profiles of a given sample type."""
        profiles = []
        for _ in range(count):
            profiles.append(self.generate_groundtruth_profile())
        return profiles
    
    def generate_imperfect_profile(self, groundtruth, sample_label) -> Dict:
        """Generate an imperfect profile by introducing specific errors based on the sample label."""
        gt = groundtruth.copy()  # or groundtruth.copy() if no nested mutation

        if sample_label.startswith("2"):
            self.introduce_sample_2_errors(gt, sample_label)
        elif sample_label.startswith("3"):
            self._3_irrelevant_info(sample_label, gt)
        labelled_profile = {'sample_type': sample_label, **gt}
        
        return labelled_profile
       
    def generate_all_sample_profiles(self, groundtruth_profiles, sample_categories):  
        # Make a shallow copy to avoid mutating the caller's list
        groundtruth_copy = groundtruth_profiles.copy()
        labelled_profiles = []

        for label, count in sample_categories.items():
            for _ in range(count):
                base_profile = groundtruth_copy.pop(0)
                
                if label == '2d' and not base_profile.get('prior_test_date'):
                    self.assign_prior_test_and_rationale(1, base_profile)  # Ensure prior test exists for 2d samples
                
                labelled_profiles.append(self.generate_imperfect_profile(base_profile, label))

        return labelled_profiles
    
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
    
    n = 50
    groundtruth_profiles = generator.generate_bulk_groundtruth_profiles(n)
    generator.save_as_json(groundtruth_profiles, "groundtruth.json")

    # Define desired distribution across sample categories (must sum to 1.0)
    sample_categories = {
        '1': 10,
        '2a': 5,
        '2b': 5,
        '2c': 5,
        '2d': 5,
        '2e': 5,
        '3a': 5,
        '3b': 5,
        '3c': 5,
    }

    # Create labeled profiles according to self.sample_categories distribution
    all_sample_profiles = generator.generate_all_sample_profiles(groundtruth_profiles, sample_categories)
    generator.save_as_json(all_sample_profiles, "all_samples.json")