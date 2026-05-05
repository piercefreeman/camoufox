"""
Quick example to test Rotunda.

Install deps:
    pip install rotunda
    python -m rotunda fetch

Local repo development:
    export ROTUNDA_EXECUTABLE_PATH=/path/to/Rotunda.app/Contents/MacOS/rotunda
    uv run --group dev python example/example.py
"""

import os

from rotunda import Rotunda, NewContext

LAUNCH_OPTIONS = {"headless": False}
if os.getenv("ROTUNDA_EXECUTABLE_PATH"):
    LAUNCH_OPTIONS["executable_path"] = os.environ["ROTUNDA_EXECUTABLE_PATH"]

with Rotunda(**LAUNCH_OPTIONS) as browser:
    context = NewContext(browser)
    page = context.new_page()

    # Visit a fingerprint test page
    page.goto("https://abrahamjuliot.github.io/creepjs/")
    page.wait_for_load_state("networkidle", timeout=30_000)

    title = page.title()
    print(f"Page title: {title}")

    # Grab the trust score CreepJS assigns
    score_el = page.query_selector("#creep-results .grade")
    if score_el:
        print(f"CreepJS trust grade: {score_el.inner_text()}")
    else:
        print("Score element not found — page may still be loading.")

    # Print the spoofed user-agent the browser reported
    ua = page.evaluate("navigator.userAgent")
    print(f"User-Agent: {ua}")

    input("\nPress Enter to close the browser...")
