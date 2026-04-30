"""
Quick example to test Camoufox.

Install deps:
    pip install camoufox
    python -m camoufox fetch

Local repo development:
    export CAMOUFOX_EXECUTABLE_PATH=/path/to/Camoufox.app/Contents/MacOS/camoufox
    uv run --group dev python example/example.py
"""

import os

from camoufox import Camoufox, NewContext

LAUNCH_OPTIONS = {"headless": False}
if os.getenv("CAMOUFOX_EXECUTABLE_PATH"):
    LAUNCH_OPTIONS["executable_path"] = os.environ["CAMOUFOX_EXECUTABLE_PATH"]

with Camoufox(**LAUNCH_OPTIONS) as browser:
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
