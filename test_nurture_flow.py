"""
Practical test for the event-driven lead nurture flow.

Simulates exactly what happens when someone DMs "batch fees" on Instagram:
  1. LeadCaptureAgent  — scores the lead, writes instant auto-reply
  2. LeadNurtureAgent  — generates Day 3, 7, 14 WhatsApp messages

No database, Redis, or Celery needed. Just the Groq API key.
Run: python test_nurture_flow.py
"""

import os
import sys
import json
from pathlib import Path

# ── Load .env ────────────────────────────────────────────────────────────────
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

# ── Add src to path ──────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

# ── Colour helpers ───────────────────────────────────────────────────────────
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
DIM    = "\033[2m"

def header(text):
    print(f"\n{BOLD}{CYAN}{'─'*60}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*60}{RESET}")

def step(n, text):
    print(f"\n{BOLD}{GREEN}[Step {n}]{RESET} {text}")

def field(label, value, color=RESET):
    print(f"  {DIM}{label}:{RESET} {color}{value}{RESET}")

def box(title, content, color=YELLOW):
    print(f"\n  {BOLD}{color}┌─ {title} {'─'*(50-len(title))}┐{RESET}")
    for line in content.strip().splitlines():
        print(f"  {color}│{RESET}  {line}")
    print(f"  {BOLD}{color}└{'─'*52}┘{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# TEST SCENARIOS
# ─────────────────────────────────────────────────────────────────────────────

SCENARIOS = [
    {
        "ig_handle": "rahul_upsc_2025",
        "message":   "Hi, what are the fees for the full batch? When does it start?",
        "label":     "Hot lead — fees + batch inquiry",
    },
    {
        "ig_handle": "priya_ias_aspirant",
        "message":   "How do I join TOPPER IAS? What's the admission process?",
        "label":     "Warm lead — admission inquiry",
    },
    {
        "ig_handle": "ankit_civil_services",
        "message":   "Nice content! Keep it up 👍",
        "label":     "Cold lead — no intent",
    },
]


def run_test(scenario: dict, scenario_num: int):
    from src.agents.lead_capture_agent import run_lead_capture_agent
    from src.agents.lead_nurture_agent import run_lead_nurture_agent

    ig_handle = scenario["ig_handle"]
    message   = scenario["message"]

    header(f"Scenario {scenario_num}: {scenario['label']}")
    print(f"\n  {DIM}Instagram DM from @{ig_handle}:{RESET}")
    print(f"  {YELLOW}\"{ message}\"{RESET}")

    # ── Step 1: LeadCaptureAgent ─────────────────────────────────────────────
    step(1, "LeadCaptureAgent — scoring the lead...")
    try:
        score = run_lead_capture_agent(message_text=message, ig_handle=ig_handle)

        status_color = RED if score.status.value == "hot" else YELLOW if score.status.value == "warm" else DIM
        field("Status",    score.status.value.upper(), status_color)
        field("Keywords",  ", ".join(score.intent_keywords_found) or "none")
        field("Notify admin", "YES 🔥" if score.should_notify_admin else "no", RED if score.should_notify_admin else DIM)

        box("Instant Instagram Auto-Reply", score.auto_reply_message, CYAN)

    except Exception as e:
        print(f"  {RED}LeadCaptureAgent failed: {e}{RESET}")
        return

    # ── Skip nurture for cold leads ──────────────────────────────────────────
    if score.status.value == "cold":
        print(f"\n  {DIM}Cold lead — no nurture sequence scheduled.{RESET}")
        return

    # ── Step 2: Schedule Day 3 / 7 / 14 ─────────────────────────────────────
    step(2, "Scheduling nurture sequence (Day 3 → 7 → 14)...")
    print(f"  {DIM}In production: 3 Celery ETA tasks queued in Redis{RESET}")
    print(f"  {DIM}  Day 3  fires at: enrolled_at + 3 days{RESET}")
    print(f"  {DIM}  Day 7  fires at: enrolled_at + 7 days{RESET}")
    print(f"  {DIM}  Day 14 fires at: enrolled_at + 14 days{RESET}")

    keywords = score.intent_keywords_found

    for day, label in [(3, "Adaptiq free trial"), (7, "Batch urgency"), (14, "Topper testimonial")]:
        step(f"2.{day//3}", f"LeadNurtureAgent — Day {day} ({label})...")
        try:
            nurture = run_lead_nurture_agent(
                lead_name=ig_handle,
                day_number=day,
                lead_status=score.status.value,
                intent_keywords=keywords,
            )
            field("Template", nurture.template_name)
            field("CTA link",  nurture.cta_link or "—")
            box(f"Day {day} WhatsApp Message", nurture.message, GREEN if day == 3 else YELLOW if day == 7 else RED)

        except Exception as e:
            print(f"  {RED}Day {day} nurture failed: {e}{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{BOLD}BrandIQ — Lead Nurture Flow Test{RESET}")
    print(f"{DIM}Testing the full event-driven sequence: DM → Score → Auto-reply → Day 3/7/14{RESET}")

    # Allow running a single scenario: python test_nurture_flow.py 1
    if len(sys.argv) > 1:
        idx = int(sys.argv[1]) - 1
        if 0 <= idx < len(SCENARIOS):
            run_test(SCENARIOS[idx], idx + 1)
        else:
            print(f"Usage: python test_nurture_flow.py [1|2|3]")
    else:
        # Run all scenarios
        for i, scenario in enumerate(SCENARIOS, 1):
            run_test(scenario, i)
            if i < len(SCENARIOS):
                input(f"\n{DIM}  Press Enter for next scenario...{RESET}")

    print(f"\n{BOLD}{GREEN}✓ Test complete{RESET}\n")
