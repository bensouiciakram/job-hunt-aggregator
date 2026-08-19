import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SMOKE = Path(r"D:\personal projects\Job Hunt Mangement System\_bmad-output\implementation-artifacts\story-3-3-smoke")
BACKEND = Path(r"D:\personal projects\Job Hunt Mangement System\backend")
PYTHON = BACKEND / ".venv" / "Scripts" / "python.exe"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS" if ok else "FAIL"), name, detail)


def run_backend(code):
    return subprocess.run(
        [str(PYTHON), "manage.py", "shell", "-c", code],
        cwd=BACKEND, capture_output=True, text=True,
    )


seed_code = r"""
from django.utils import timezone
from listings.models import Application, Listing
from listings.services import apply_to_listing

Listing.objects.filter(company='SmokePaceCo').delete()

for i in range(11):
    listing = Listing.objects.create(
        dedup_fingerprint=f'smoke-pace-{i}',
        title=f'Smoke Pace Job {i}',
        company='SmokePaceCo',
        url=f'https://smoke.example/pace/{i}',
        published_at=timezone.now(),
        status='new',
        seen_sources=['ouedkniss'],
    )
    apply_to_listing(listing)
    if i == 0:
        print('TARGET', listing.id)
print('seeded')
"""

seed = run_backend(seed_code)
print(seed.stdout.strip() or seed.stderr.strip())

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.set_default_timeout(20000)

    page.goto("http://localhost:3000/?bucket=all", wait_until="networkidle")
    time.sleep(1)

    rest_line = page.locator("[data-pacing-rest]")
    check("pacing_rest_line", rest_line.count() == 1, "rest line visible in header")

    target = page.locator("li[data-row='listing']", has_text="Smoke Pace Job 0")
    check("target_row_found", target.count() == 1, "target row present")
    target.get_by_role("button", name="response").click()
    page.wait_for_timeout(500)
    badge = target.locator("text=Applied · response")
    check("outcome_badge_updates", badge.count() == 1, "badge shows 'Applied · response'")

    page.screenshot(path=str(SMOKE / "step-1-outcome-and-pacing.png"))
    browser.close()

cleanup = run_backend(
    "from listings.models import Listing; Listing.objects.filter(company='SmokePaceCo').delete(); print('cleaned')"
)
check("cleanup_smoke_rows", cleanup.returncode == 0 and "cleaned" in cleanup.stdout,
      cleanup.stdout.strip() or cleanup.stderr.strip())

failed = any(not ok for _, ok, _ in results)
print("TOTAL", len(results), "FAILED", sum(1 for _, ok, _ in results if not ok))
sys.exit(1 if failed else 0)