import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SMOKE = Path(r"D:\personal projects\Job Hunt Mangement System\_bmad-output\implementation-artifacts\story-3-2-smoke")
BACKEND = Path(r"D:\personal projects\Job Hunt Mangement System\backend")
PYTHON = BACKEND / ".venv" / "Scripts" / "python.exe"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS" if ok else "FAIL"), name, detail)


seed_code = r"""
from django.utils import timezone
from listings.models import Listing
from collector.pipeline.dedupe import compute_fingerprint

Listing.objects.filter(company__in=['SmokeCrossCo', 'SmokeGrowthCo', 'SmokeControlCo']).delete()

def mk(title, company, url, seen, days_ago=0, **kw):
    return Listing.objects.create(
        dedup_fingerprint=compute_fingerprint(title, company, url),
        title=title, company=company, url=url,
        published_at=timezone.now() - __import__('datetime').timedelta(hours=days_ago * 24),
        seen_sources=seen, status='new', **kw,
    )

mk('Cross Posted Job', 'SmokeCrossCo', 'https://smoke.example/cross', ['ouedkniss', 'google-jobs'])
mk('Growth Role 1', 'SmokeGrowthCo', 'https://smoke.example/g1', ['ouedkniss'], days_ago=2)
mk('Growth Role 2', 'SmokeGrowthCo', 'https://smoke.example/g2', ['ouedkniss'], days_ago=1)
mk('Growth Role 3', 'SmokeGrowthCo', 'https://smoke.example/g3', ['ouedkniss'], days_ago=0)
mk('Control Job', 'SmokeControlCo', 'https://smoke.example/control', ['ouedkniss'], days_ago=0)
print('seeded')
"""

seed = subprocess.run(
    [str(PYTHON), "manage.py", "shell", "-c", seed_code],
    cwd=BACKEND, capture_output=True, text=True,
)
check("seed_listings", seed.returncode == 0 and "seeded" in seed.stdout,
      seed.stdout.strip() or seed.stderr.strip())

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.set_default_timeout(20000)

    page.goto("http://localhost:3000/?bucket=all", wait_until="networkidle")
    time.sleep(1)

    rows = page.locator("li[data-row='listing']")
    titles = {}
    for i in range(rows.count()):
        row = rows.nth(i)
        title = row.locator("h2").first.inner_text()
        signals = row.locator("span[data-signal]").all_inner_texts()
        titles[title] = signals

    check("cross_posted_chip", "Cross Posted Job" in titles and "cross-posted" in titles["Cross Posted Job"],
          f"chips for cross-posted: {titles.get('Cross Posted Job')}")
    check("growth_chip", "Growth Role 3" in titles and "growth?" in titles["Growth Role 3"],
          f"chips for growth target: {titles.get('Growth Role 3')}")
    control = titles.get("Control Job")
    check("control_no_signals", control is not None and control == [],
          f"control chips: {control}")

    page.screenshot(path=str(SMOKE / "step-1-signals.png"))
    browser.close()

cleanup = subprocess.run(
    [str(PYTHON), "manage.py", "shell", "-c",
     "from listings.models import Listing; Listing.objects.filter(company__in=['SmokeCrossCo','SmokeGrowthCo','SmokeControlCo']).delete(); print('cleaned')"],
    cwd=BACKEND, capture_output=True, text=True,
)
check("cleanup_smoke_rows", cleanup.returncode == 0 and "cleaned" in cleanup.stdout,
      cleanup.stdout.strip() or cleanup.stderr.strip())

failed = any(not ok for _, ok, _ in results)
print("TOTAL", len(results), "FAILED", sum(1 for _, ok, _ in results if not ok))
sys.exit(1 if failed else 0)