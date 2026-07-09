"""
Local Browser Use deployment.

Usage:
    python scripts/local_deploy.py
"""

import asyncio
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from browser_use import Agent, ChatGoogle, ChatAnthropic, ChatOpenAI, ChatOllama

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL     = os.getenv("APP_BASE_URL", "https://wes-wgs-pa-app-u2c8s.ondigitalocean.app")
PATIENT_NAME = "Richard Wood"
PROVIDER     = "google"    # "openai" | "anthropic" | "google"
MODEL        = "gemini-3-flash-preview"
MAX_STEPS    = 40
USE_VISION   = True

TASK = (
    f'Visit the web app at {BASE_URL}. On the first log-in page, sign in with '
    f'username "user2" and password "pass789". '
    f"Find the patient record for {PATIENT_NAME} using the patient search function, "
    f"then fill out and submit a Pre-Authorization Form for this patient. "
    f"Verify all required fields before submitting. "
    f"If you find any issues, immediately stop and report them."
)

# ── LLM factory ───────────────────────────────────────────────────────────────
def create_llm(provider: str, model: str):
    if provider == "openai":
        return ChatOpenAI(model=model)
    elif provider == "anthropic":
        return ChatAnthropic(model=model)
    elif provider == "google":
        return ChatGoogle(model=model)
    else:
        raise ValueError(f"Unknown provider: {provider!r}. Use 'openai', 'anthropic', or 'google'.")


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    llm = ChatOllama(model="llama3.1:8b")

    print(f"\n{'═' * 60}")
    print(f"  Task:      {TASK[:80]}{'...' if len(TASK) > 80 else ''}")
    print(f"  Model:     {PROVIDER}/{MODEL}  |  max_steps={MAX_STEPS}")
    print(f"{'═' * 60}\n")

    agent = Agent(
        task=TASK,
        llm=llm, # type: ignore
        use_vision=USE_VISION,
        max_actions_per_step=4,
        calculate_cost=True,
    )

    history = await agent.run(max_steps=MAX_STEPS)

    final = history.final_result()

    print(f"\n{'═' * 60}")
    print("  SUMMARY")
    print(f"{'═' * 60}")
    print(f"  Token usage:    {history.usage}")
    print(f"{'═' * 60}")

    if final:
        print(f"\n  Result: {final[:500]}")

    usage = history.usage
    token_usage = {k: v for k, v in vars(usage).items() if v is not None} if usage else {}
    report_path = Path("data/results/token_usage_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_data = {"token_usage": token_usage, "final_result": final}

    existing = []
    if report_path.exists():
        try:
            existing = json.loads(report_path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = [existing]
        except Exception:
            existing = []
    existing.append(report_data)
    report_path.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")
    print(f"\n  Report saved to: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
