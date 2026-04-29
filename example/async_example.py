"""
Async Camoufox example for scraping multiple pages concurrently.

Install deps:
    pip install camoufox
    python -m camoufox fetch

Local repo development:
    export CAMOUFOX_EXECUTABLE_PATH=/path/to/Camoufox.app/Contents/MacOS/camoufox
    uv run --project pythonlib --group dev python example/async_example.py
"""

import asyncio
import os

from camoufox import AsyncCamoufox, AsyncNewContext

URLS = [
    "https://httpbin.org/headers",
    "https://httpbin.org/user-agent",
    "https://httpbin.org/ip",
]


async def scrape(page, url: str) -> dict:
    await page.goto(url)
    body = await page.inner_text("body")
    return {"url": url, "body": body[:300]}


async def main():
    launch_options = {"headless": True}
    if os.getenv("CAMOUFOX_EXECUTABLE_PATH"):
        launch_options["executable_path"] = os.environ["CAMOUFOX_EXECUTABLE_PATH"]

    async with AsyncCamoufox(**launch_options) as browser:
        context = await AsyncNewContext(browser)

        pages = [await context.new_page() for _ in URLS]
        results = await asyncio.gather(*[scrape(p, u) for p, u in zip(pages, URLS)])

        for r in results:
            print(f"\n--- {r['url']} ---")
            print(r["body"])


if __name__ == "__main__":
    asyncio.run(main())
