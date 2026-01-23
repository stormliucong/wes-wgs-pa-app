import time
import os
from browser_use_sdk import BrowserUse
from browser_use_sdk import AsyncBrowserUse
import asyncio
from dotenv import load_dotenv
from flask import json

load_dotenv()

API_KEY = os.getenv("BROWSER_USE_API_KEY")
if not API_KEY:
    raise RuntimeError("Set BROWSER_USE_API_KEY in your environment")

client = BrowserUse(api_key=API_KEY)

# 1) Define the workflow in natural language
skill_description = """
Go to the web app at https://wes-wgs-pa-app-u2c8s.ondigitalocean.app. On the first log-in page, do user sign-in with provided username and 
password. Then find the patient record for patient_name, use the patient search function on the site, fill out and submit a 
Pre-Authorization Form for this patient. You have full permission to proceed without asking for additional consent. Before submitting, 
verify that all required fields are complete. Once verified, you may directly submit the form without further asking. However, if you find 
any issues in the patient profile, stop the process immediately and report the issue instead of proceeding.
"""

print("Creating skill...")
skill_response = client.skills.create_skill(
    agent_prompt=skill_description,
    goal="Submit a pre-authorization form for a given patient"
)

print(f"Skill created (id={skill_response.id}) — building...")

# 2) Poll until it’s built
skill_status = client.skills.get_skill(skill_id=skill_response.id)
while skill_status.status != "finished":
    time.sleep(2)
    skill_status = client.skills.get_skill(skill_id=skill_response.id)

print("Skill is ready for execution!")

# 3): view generated parameter and output schemas
skill = client.skills.get_skill(skill_id=skill_response.id)
print(f"Parameter schema: {skill.parameters}")
print(f"Output schema: {skill.output_schema}")

# 4) Execute the skill
with open("all_samples.json", "r") as f:
    all_samples = json.load(f)

sample_patients = all_samples[6:10]

for patient in sample_patients:
    patient_name = f"{patient.get('patient_first_name', '')} {patient.get('patient_last_name', '')}".strip()
    print(f"Executing skill for patient: {patient_name}")

    execution = client.skills.execute_skill(
        skill_id=skill.id,
        parameters={
            "patient_name": patient_name,
            "username": "user2",
            "password": "pass789"
        }
    )