#!/usr/bin/env python3
"""
Synthetic Patient Data Generator for WES/WGS Pre-Authorization Form

This script generates realistic synthetic patient profiles that can be used to test
the pre-authorization form. All data is completely fictional and for testing purposes only.

Usage:
    python generate_test_patients.py -n 50 -o test_patients.jsonl
    python generate_test_patients.py --count 100 --output bulk_test_data.jsonl
"""

import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any


class PatientDataGenerator:
    """Generates synthetic patient data for testing pre-authorization forms."""
    
    def __init__(self):
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
        
        self.test_types = ['WES', 'WGS']
        
        self.test_configurations = ['Proband', 'Duo', 'Trio']
        
        self.urgency_levels = ['Routine', 'Expedited']
        
        self.specimen_types = ['Blood', 'Saliva', 'Buccal', 'Other']
        
        self.sexes = ['Male', 'Female', 'Intersex', 'Unknown']
        
        self.subscriber_relations = ['Self', 'Parent', 'Guardian', 'Other']
        
        # Medical data
        self.icd_codes = [
            'Z87.891', 'Q87.89', 'G80.9', 'F84.0', 'Q93.9', 'Q91.3', 'Z13.79', 'Z87.41',
            'C78.00', 'D49.9', 'Z85.3', 'Q87.1', 'F70', 'G40.909', 'Q87.0', 'Z87.891',
            'Q99.9', 'F79', 'G93.1', 'Q90.9', 'Z83.79', 'Q87.2', 'C50.911', 'Z15.01'
        ]
        
        self.cpt_codes = ['81415', '81416', '81425', '81426', '81427']
        
        self.clinical_indications = [
            'Suspected genetic etiology for developmental delay and intellectual disability',
            'Family history of hereditary cancer syndrome requiring genetic evaluation',
            'Multiple congenital anomalies of unknown etiology',
            'Progressive neurological symptoms with suspected genetic cause',
            'Autism spectrum disorder with associated dysmorphic features',
            'Unexplained seizure disorder with developmental delay',
            'Suspected metabolic disorder based on clinical presentation',
            'Multiple primary cancers suggesting hereditary cancer syndrome',
            'Consanguineous family with multiple affected children',
            'Neurodevelopmental disorder with family history of similar symptoms'
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
    
    def generate_address(self) -> str:
        """Generate a realistic Connecticut address."""
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
    
    def generate_patient_profile(self) -> Dict[str, Any]:
        """Generate a complete synthetic patient profile."""
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
            
            # Test Information
            'test_type': random.choice(self.test_types),
            'test_configuration': random.choice(self.test_configurations),
            'urgency': random.choice(self.urgency_levels),
            'specimen_type': random.choice(self.specimen_types),
            'collection_date': self.generate_recent_date(),
            
            # CPT Codes (1-3 codes typically)
            'cpt_codes': random.sample(self.cpt_codes, random.randint(1, 3)),
            
            # Diagnosis Information
            'icd_codes': random.sample(self.icd_codes, random.randint(1, 3)),
            'primary_diagnosis': random.choice([
                'Developmental delay', 'Intellectual disability', 'Autism spectrum disorder',
                'Seizure disorder', 'Multiple congenital anomalies', 'Hereditary cancer syndrome',
                'Neuromuscular disorder', 'Metabolic disorder', 'Chromosomal abnormality'
            ]),
            'clinical_indication': random.choice(self.clinical_indications),
            
            # Prior Testing
            'family_history': random.choice(self.family_histories),
            
            # Medical Necessity checkboxes
            'mn_suspected_genetic': random.choice([True, False]),
            'mn_results_influence_management': random.choice([True, True, False]),  # More likely True
            'mn_genetic_counseling': random.choice([True, True, False]),  # More likely True
            
            # Consent and Signature
            'consent_ack': True,  # Always True for valid submissions
            'provider_signature': random.choice(self.provider_names),
            'signature_date': self.generate_recent_date(),
        }
        
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
        """Validate that a generated profile meets form requirements."""
        # Import validation from models
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
        description='Generate synthetic patient profiles for WES/WGS pre-authorization form testing',
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
        default=10,
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
        print("Preview of generated patient profile:")
        print("-" * 50)
        profile = generator.generate_patient_profile()
        print(json.dumps(profile, indent=2, ensure_ascii=False))
        return
    
    # Generate profiles
    print(f"Generating {args.count} synthetic patient profiles...")
    profiles = generator.generate_bulk_profiles(args.count)
    
    # Validate if requested
    if args.validate:
        print("Validating generated profiles...")
        valid_count = 0
        for i, profile in enumerate(profiles):
            if generator.validate_profile(profile):
                valid_count += 1
            else:
                print(f"Profile {i+1} failed validation")
        
        print(f"Validation results: {valid_count}/{len(profiles)} profiles are valid")
        
        if valid_count < len(profiles):
            response = input("Some profiles failed validation. Continue anyway? (y/N): ")
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


if __name__ == '__main__':
    main()