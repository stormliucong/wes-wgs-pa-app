#!/usr/bin/env python3
"""
Synthetic Patient Data Generator for WES/WGS Pre-Authorization Form

This script generates realistic synthetic patient profiles that can be used to test
the pre-authorization form. All data is completely fictional and for testing purposes only.

This version generates THREE TYPES of patients, labeled via `label_type`:

  label_type = 1 (CONSISTENT):
    - ICD codes are consistent with clinical indication and primary diagnosis
    - CPT codes are consistent with test_type and test_configuration
    - No intentional data errors

  label_type = 2 (ICD INCONSISTENT):
    - Clinical indication and primary diagnosis are internally consistent
    - ICD codes are intentionally mismatched with the indication / primary dx
    - No other errors
    
  label_type = 3 (CPT INCONSISTENT):
    - CPT codes are intentionally mismatched with the test_type / configuration
    - No other errors

  label_type = 4 (ERROR PROFILES):
    - Starts from a consistent base (like label 1)
    - Then injects one or more random errors, e.g.:
        * invalid / unexpected ICD and CPT codes
        * invalid state codes (e.g., 'TT')
        * impossible date of birth values (e.g., 2019-02-29)
        * sample collection dates that occur BEFORE the date of birth

Usage:
    python generate_test_patients.py -n 50 -o test_patients.jsonl
    python generate_test_patients.py --count 100 --output bulk_test_data.jsonl
"""

import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Tuple


class PatientDataGenerator:
    """Generates synthetic patient data for testing pre-authorization forms (with controllable consistency/error labels)."""
    
    def __init__(self):
        # --- Label distribution for (1, 2, 3, 4) ---
        # 1 = fully consistent, 2 = ICD-inconsistent, 3 = CPT-inconsistent, 4 = error profiles
        self.label_distribution: Tuple[float, float, float, float] = (0.2, 0.2, 0.2, 0.4)

        # Sample data for realistic generation
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
        
        # Test types & configurations
        self.test_types = ['WES', 'WGS']
        self.test_configurations = ['Proband', 'Trio']

        # Deterministic mapping: (test_type, test_configuration) -> CPT codes
        # These represent the “consistent” CPT codes for label_type 1 & 2 (before error injection in label 3).
        self.test_cpt_map: Dict[Tuple[str, str], List[str]] = {
            ('WES', 'Proband'): ['81415'],
            ('WES', 'Trio'): ['81415', '81416'],
            ('WGS', 'Proband'): ['81425'],
            ('WGS', 'Trio'): ['81425', '81426', '81427'],
        }

        # This is only kept for reference / fallback; normal generation uses self.test_cpt_map
        self.cpt_codes = ['81415', '81416', '81425', '81426', '81427']
        
        self.urgency_levels = ['Routine', 'Expedited']
        
        self.specimen_types = ['Blood', 'Saliva', 'Buccal', 'Other']
        
        self.sexes = ['Male', 'Female', 'Intersex', 'Unknown']
        
        self.subscriber_relations = ['Self', 'Parent', 'Guardian', 'Other']
        
        # Medical data: ICD codes aligned to clinical_indications by index
        self.icd_codes = [
            ["F81.9", "F79", "R62.50"],       # 0: Suspected genetic etiology for developmental delay
            ["Z80.9", "Z84.81"],              # 1: Family history of hereditary cancer syndrome
            ["Q89.7", "Q99.9"],               # 2: Multiple congenital anomalies of unknown etiology
            ["G32.8", "G31.9"],               # 3: Progressive neurological symptoms, genetic cause
            ["F84.0", "Q89.7"],               # 4: Autism with dysmorphic features
            ["G40.909", "R62.50"],            # 5: Seizure disorder with developmental delay
            ["E88.9"],                        # 6: Suspected metabolic disorder
            ["C80.1", "Z84.81"],              # 7: Multiple primary cancers, hereditary cancer syndrome
            ["Z84.2"],                        # 8: Consanguinity with affected children
            ["F89", "Z84.81"]                 # 9: Neurodevelopmental disorder + family history
        ]
        
        # Purposely invalid / unexpected codes for error injection (label_type 3)
        self.invalid_icd_codes = ['XXX.999', 'A00.0000', '123.456', 'Z99.ZZ9']
        self.invalid_cpt_codes = ['99999', 'ABCDE', '81X15', '00000']
        
        self.clinical_indications = [
            "Suspected genetic etiology for developmental delay and intellectual disability",
            "Family history of hereditary cancer syndrome requiring genetic evaluation",
            "Multiple congenital anomalies of unknown etiology",
            "Progressive neurological symptoms with suspected genetic cause",
            "Autism spectrum disorder with associated dysmorphic features",
            "Unexplained seizure disorder with developmental delay",
            "Suspected metabolic disorder based on clinical presentation",
            "Multiple primary cancers suggesting hereditary cancer syndrome",
            "Consanguineous family with multiple affected children",
            "Neurodevelopmental disorder with family history of similar symptoms"
        ]

        # Primary diagnoses aligned by index to clinical_indications/icd_codes
        self.primary_diagnoses = [
            "Developmental delay and intellectual disability",
            "Hereditary cancer syndrome",
            "Multiple congenital anomalies",
            "Progressive neurological disorder",
            "Autism spectrum disorder with dysmorphic features",
            "Seizure disorder with developmental delay",
            "Suspected metabolic disorder",
            "Multiple primary cancers",
            "Genetic disorder in consanguineous family",
            "Neurodevelopmental disorder with family history"
        ]
        
        self.clinical_histories = [
            'Patient presents with global developmental delay, hypotonia, and dysmorphic features. Family history significant for similar symptoms in maternal cousin.',
            'History of multiple primary cancers including breast and ovarian. Strong family history of cancer on maternal side with early onset.',
            'Progressive muscle weakness and atrophy beginning in early childhood. EMG findings consistent with myopathy.',
            'Severe intellectual disability with autism spectrum disorder. Multiple congenital anomalies including cardiac defects.',
            'Seizure disorder beginning in infancy, refractory to multiple antiepileptic medications. Associated developmental delay.',
            'Hearing loss, vision problems, and developmental delay. Metabolic workup suggests possible storage disorder.',
            'Multiple miscarriages and one child with severe congenital anomalies. Concerns for genetic etiology.',
            'Early-onset Parkinson-like symptoms with family history of neurodegenerative disease.',
            'Failure to thrive, developmental delay, and unusual facial features. Previous genetic testing inconclusive.',
            'Recurrent infections, immunodeficiency, and growth delays. Suspected primary immunodeficiency disorder.'
        ]
        
        self.family_histories = [
            'Maternal grandmother with intellectual disability, paternal uncle with similar features',
            'Mother diagnosed with breast cancer at age 35, maternal aunt with ovarian cancer at 42',
            'Two siblings with developmental delays, parents are first cousins',
            'Father with late-onset neurological symptoms, paternal grandfather with dementia',
            'Multiple family members with autism spectrum disorders across generations',
            'Sister with seizure disorder, maternal cousin with developmental delay',
            'No significant family history of genetic disorders or congenital anomalies',
            'Extensive family history of cancer including colon, breast, and prostate cancers',
            'Consanguineous marriage, previous child with similar presentation deceased in infancy',
            'Family history of hearing loss and vision problems in multiple relatives'
        ]

        # Prior testing options (including "empty")
        self.prior_tests = ['CMA', 'Gene panel', 'Single gene', '']  # empty string = no prior test documented
    
    # -------------------------------------------------------------------------
    # Basic generators
    # -------------------------------------------------------------------------
    
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
        """Generate a realistic date of birth (1-80 years ago)."""
        years_ago = random.randint(1, 80)
        days_ago = random.randint(0, 365)
        birth_date = datetime.now() - timedelta(days=years_ago * 365 + days_ago)
        return birth_date.strftime('%Y-%m-%d')
    
    def generate_recent_date(self) -> str:
        """Generate a recent date (within last 30 days)."""
        days_ago = random.randint(0, 30)
        recent_date = datetime.now() - timedelta(days=days_ago)
        return recent_date.strftime('%Y-%m-%d')

    @staticmethod
    def _is_leap_year(year: int) -> bool:
        """Check if a given year is a leap year."""
        return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)

    # -------------------------------------------------------------------------
    # Label sampling & error injection
    # -------------------------------------------------------------------------

    def _sample_label(self) -> int:
        """Sample a label_type ∈ {1,2,3,4} according to self.label_distribution."""
        p1, p2, p3, p4 = self.label_distribution
        r = random.random()
        if r < p1:
            return 1
        elif r < p1 + p2:
            return 2
        elif r < p1 + p2 + p3:
            return 3
        else:
            return 4

    def introduce_random_errors(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """
        Randomly introduce various data errors into the profile for negative testing.
        Used ONLY for label_type = 3.

        Possible errors:
          - wrong_icd: inject an invalid / unexpected ICD code
          - wrong_cpt: inject an invalid / unexpected CPT code
          - wrong_state: change address state to 'TT'
          - bad_dob_feb29: set DOB to 02-29 on a non-leap year
          - collection_before_prior_test: sample collection occurs before prior testing
        """
        possible_errors = ['wrong_icd', 'wrong_cpt', 'wrong_state', 'bad_dob_feb29', 'collection_before_prior_test']
        # num_errors = random.randint(1, len(possible_errors))
        num_errors = 1
        selected_errors = random.sample(possible_errors, num_errors)

        # Cache original DOB as datetime where possible, for some errors
        original_dob_str = profile.get('dob')
        dob_dt = None
        if original_dob_str:
            try:
                dob_dt = datetime.strptime(original_dob_str, '%Y-%m-%d')
            except ValueError:
                dob_dt = None

        # Apply each selected error
        for error in selected_errors:
            if error == 'wrong_icd':
                if profile.get('icd_codes'):
                    idx = random.randrange(len(profile['icd_codes']))
                    profile['icd_codes'][idx] = random.choice(self.invalid_icd_codes)

            elif error == 'wrong_cpt':
                if profile.get('cpt_codes'):
                    idx = random.randrange(len(profile['cpt_codes']))
                    profile['cpt_codes'][idx] = random.choice(self.invalid_cpt_codes)

            elif error == 'wrong_state':
                for key in ['patient_address', 'provider_address', 'lab_address']:
                    addr = profile.get(key)
                    if addr and ', CT ' in addr and random.random() < 0.8:
                        profile[key] = addr.replace(', CT ', ', TT ', 1)

            elif error == 'bad_dob_feb29':
                non_leap_year = 2019  # clearly non-leap year; intentionally fixed
                profile['dob'] = f"{non_leap_year}-02-29"

            elif error == 'collection_before_prior_test':
                prior_test = profile.get('prior_test')
                prior_test_date_str = profile.get('prior_test_date')
                if prior_test and prior_test_date_str:
                    try:
                        prior_dt = datetime.strptime(prior_test_date_str, '%Y-%m-%d')
                    except ValueError:
                        prior_dt = datetime.now()
                    earlier_date = prior_dt - timedelta(days=random.randint(1, 60))
                    profile['collection_date'] = earlier_date.strftime('%Y-%m-%d')

        return profile

    # -------------------------------------------------------------------------
    # Core patient generation
    # -------------------------------------------------------------------------
    
    def _generate_base_profile_common(self) -> Dict[str, Any]:
        """Generate the common (non-label-specific) portion of a profile."""
        sex = random.choice(self.sexes)
        first_name = random.choice(self.first_names.get(sex, self.first_names['Male']))
        last_name = random.choice(self.last_names)
        
        # Determine if patient is subscriber (most common) or has different subscriber
        is_self_subscriber = random.choice([True, True, True, False])  # 75% self
        
        profile = {
            # Patient & Insurance Information
            'patient_first_name': first_name,
            'patient_last_name': last_name,
            'dob': self.generate_date_of_birth(),
            'sex': sex,
            'member_id': self.generate_member_id(),
            'patient_address': self.generate_address(),
            
            # Subscriber info (if different from patient)
            'subscriber_name': '' if is_self_subscriber else f"{random.choice(self.first_names['Male'] + self.first_names['Female'])} {last_name}",
            'subscriber_relation': 'Self' if is_self_subscriber else random.choice(self.subscriber_relations[1:]),
            
            # Provider Information
            'provider_name': random.choice(self.provider_names),
            'provider_npi': self.generate_npi(),
            'provider_phone': self.generate_phone(),
            'provider_fax': self.generate_phone(),
            'provider_address': self.generate_address(),
            
            # Laboratory (sometimes same as provider)
            'lab_name': random.choice(['LabCorp', 'Quest Diagnostics', 'GeneDx', 'Invitae', 'Ambry Genetics', '']),
            'lab_npi': self.generate_npi() if random.choice([True, False]) else '',
            'lab_address': self.generate_address() if random.choice([True, False]) else '',
            
            # Prior Testing
            'family_history': random.choice(self.family_histories),
            'prior_test': random.choice(self.prior_tests),  # "CMA", "Gene panel", "Single gene", or ""
        }
        return profile

    def _assign_consistent_test_and_cpt(self, profile: Dict[str, Any]) -> None:
        """Assign test_type, test_configuration, urgency, specimen_type and consistent CPT codes."""
        test_key = random.choice(list(self.test_cpt_map.keys()))
        test_type, test_config = test_key
        cpt_codes = self.test_cpt_map[test_key]

        profile['test_type'] = test_type
        profile['test_configuration'] = test_config
        profile['urgency'] = random.choice(self.urgency_levels)
        profile['specimen_type'] = random.choice(self.specimen_types)
        profile['collection_date'] = self.generate_recent_date()
        profile['cpt_codes'] = list(cpt_codes)  # copy
        self._assign_prior_test_details(profile)
        
    def _assign_inconsistent_test_and_cpt(self, profile: Dict[str, Any]) -> None:
        """Assign test_type and test_configuration, but inconsistent CPT codes."""
        test_key = random.choice(list(self.test_cpt_map.keys()))
        test_type, test_config = test_key
        # Choose a different CPT code set
        possible_cpt_keys = [k for k in self.test_cpt_map.keys() if k != test_key]
        inconsistent_key = random.choice(possible_cpt_keys)
        cpt_codes = self.test_cpt_map[inconsistent_key]

        profile['test_type'] = test_type
        profile['test_configuration'] = test_config
        profile['urgency'] = random.choice(self.urgency_levels)
        profile['specimen_type'] = random.choice(self.specimen_types)
        profile['collection_date'] = self.generate_recent_date()
        profile['cpt_codes'] = list(cpt_codes)  # copy
        self._assign_prior_test_details(profile)

    def _assign_prior_test_details(self, profile: Dict[str, Any]) -> None:
        """Populate prior test result/date if a prior test exists."""
        prior_test = profile.get('prior_test')
        if not prior_test:
            profile['prior_test_result'] = ''
            profile['prior_test_date'] = ''
            return

        profile['prior_test_result'] = random.choice(['Positive', 'Negative'])
        collection_date_str = profile.get('collection_date')
        try:
            collection_dt = datetime.strptime(collection_date_str, '%Y-%m-%d') if collection_date_str else None
        except ValueError:
            collection_dt = None

        if collection_dt is None:
            collection_dt = datetime.now()

        prior_dt = collection_dt - timedelta(days=random.randint(7, 180))
        profile['prior_test_date'] = prior_dt.strftime('%Y-%m-%d')

    def _assign_consistent_icd_and_indication(self, profile: Dict[str, Any]) -> None:
        """Assign clinical_indication, primary_diagnosis, and matching ICD codes."""
        idx = random.randrange(len(self.clinical_indications))
        profile['clinical_indication'] = self.clinical_indications[idx]
        profile['primary_diagnosis'] = self.primary_diagnoses[idx]
        profile['icd_codes'] = list(self.icd_codes[idx])  # flat list of strings

    def _assign_inconsistent_icd(self, profile: Dict[str, Any]) -> None:
        """
        Assign indication + primary_diagnosis from one index,
        but ICD codes from a different index (logical inconsistency, but syntactically valid).
        """
        n = len(self.clinical_indications)
        idx_ind = random.randrange(n)
        # Choose a different index for ICD codes
        possible_icd_indices = [i for i in range(n) if i != idx_ind]
        idx_icd = random.choice(possible_icd_indices)

        profile['clinical_indication'] = self.clinical_indications[idx_ind]
        profile['primary_diagnosis'] = self.primary_diagnoses[idx_ind]
        profile['icd_codes'] = list(self.icd_codes[idx_icd]) # flat list of strings

    def generate_patient_profile(self) -> Dict[str, Any]:
        """
        Generate a complete synthetic patient profile and assign label_type:

          1 = Consistent ICD + indication + primary diagnosis AND consistent CPT + tests
          2 = Inconsistent ICD vs indication / primary dx; CPT/tests still consistent
          3 = Start from (1) and then inject random data errors (ICD, CPT, DOB, state, collection_before_birth)
        """
        label_type = self._sample_label()
        profile = self._generate_base_profile_common()

        # ICD / indication / primary diagnosis logic by label_type
        if label_type == 1:
            # Fully consistent
            self._assign_consistent_icd_and_indication(profile)
            self._assign_consistent_test_and_cpt(profile)

        elif label_type == 2:
            # ICD inconsistent with indication / primary diagnosis
            self._assign_inconsistent_icd(profile)
            self._assign_consistent_test_and_cpt(profile)
        elif label_type == 3:
            # CPT inconsistent with test_type / configuration
            self._assign_consistent_icd_and_indication(profile)
            self._assign_inconsistent_test_and_cpt(profile) 
        else:  # label_type == 4
            # Start from fully consistent state, then inject errors
            self._assign_consistent_icd_and_indication(profile)
            self._assign_consistent_test_and_cpt(profile)
            profile = self.introduce_random_errors(profile)

        # Clinical history (used for all labels)
        profile['clinical_history'] = random.choice(self.clinical_histories)

        # Attach label_type for downstream classification/analysis
        profile['label_type'] = label_type

        return profile
    
    def generate_bulk_profiles(self, count: int) -> List[Dict[str, Any]]:
        """Generate multiple patient profiles."""
        profiles = []
        for _ in range(count):
            profiles.append(self.generate_patient_profile())
        return profiles
    
    def save_as_jsonl(self, profiles: List[Dict[str, Any]], output_file: str) -> None:
        """Save profiles as JSONL (JSON Lines) format."""
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with output_path.open('w', encoding='utf-8') as f:
            for profile in profiles:
                f.write(json.dumps(profile, ensure_ascii=False) + '\n')
        
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


def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(
        description='Generate synthetic patient profiles for WES/WGS pre-authorization form testing (with labeled consistency/error types)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -n 50 -o test_patients.jsonl
  %(prog)s --count 100 --output bulk_test_data.jsonl --validate
  %(prog)s -n 25 -o small_batch.jsonl --seed 12345
        """
    )
    
    parser.add_argument(
        '-n', '--count',
        type=int,
        default=50,
        help='Number of patient profiles to generate (default: 10)'
    )
    
    parser.add_argument(
        '-o', '--output',
        type=str,
        default='test_patients.jsonl',
        help='Output file path (default: test_patients.jsonl)'
    )
    
    parser.add_argument(
        '--validate',
        action='store_true',
        help='Validate generated profiles against form validation rules'
    )
    
    parser.add_argument(
        '--seed',
        type=int,
        help='Random seed for reproducible results'
    )
    
    parser.add_argument(
        '--preview',
        action='store_true',
        help='Show a preview of one generated profile without saving'
    )
    
    args = parser.parse_args()
    
    # Set random seed if provided
    if args.seed:
        random.seed(args.seed)
        print(f"Using random seed: {args.seed}")
    
    # Initialize generator
    generator = PatientDataGenerator()
    
    # Preview mode
    if args.preview:
        print("Preview of generated patient profile (with label_type and possible intentional errors for label_type=3):")
        print("-" * 50)
        profile = generator.generate_patient_profile()
        print(json.dumps(profile, indent=2, ensure_ascii=False))
        return
    
    # Generate profiles
    print(f"Generating {args.count} synthetic patient profiles (mixture of label_type 1, 2, and 3)...")
    profiles = generator.generate_bulk_profiles(args.count)
    
    # Validate if requested
    if args.validate:
        print("Validating generated profiles...")
        valid_count = 0
        for i, profile in enumerate(profiles):
            if generator.validate_profile(profile):
                valid_count += 1
            else:
                print(f"Profile {i+1} failed validation (this may be expected for label_type=3 error profiles)")
        
        print(f"Validation results: {valid_count}/{len(profiles)} profiles are valid")
        
        if valid_count < len(profiles):
            response = input("Some profiles failed validation (expected for error profiles). Continue anyway? (y/N): ")
            if response.lower() != 'y':
                print("Aborted.")
                return
    
    # Save to file
    generator.save_as_jsonl(profiles, args.output)
    
    # Show summary
    print("\nSummary:")
    print(f"  Generated: {len(profiles)} profiles")
    print(f"  Output file: {args.output}")
    print(f"  File size: {Path(args.output).stat().st_size / 1024:.1f} KB")
    
    # Show sample of what was generated
    test_types = [p['test_type'] for p in profiles]
    wes_count = test_types.count('WES')
    wgs_count = test_types.count('WGS')
    print(f"  Test types: {wes_count} WES, {wgs_count} WGS")

    # Label distribution summary
    labels = [p['label_type'] for p in profiles]
    label_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for lbl in labels:
        label_counts[lbl] += 1
    print("  Label distribution:")
    for lbl, count in label_counts.items():
        print(f"    Label {lbl}: {count} profiles ({(count / len(profiles)) * 100:.1f}%)")


if __name__ == '__main__':
    main()
