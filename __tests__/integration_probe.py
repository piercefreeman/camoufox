from __future__ import annotations

import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


_DEFAULT_TIMEOUT_SECONDS = 20
_ENV_TRUE = {"1", "true", "yes", "on"}


def _resolve_executable_path(executable_path: str) -> Path:
    resolved = Path(executable_path).expanduser().resolve()

    if sys.platform == "darwin" and resolved.suffix == ".app":
        for binary_name in ("camoufox", "firefox"):
            candidate = resolved / "Contents" / "MacOS" / binary_name
            if candidate.is_file():
                return candidate

    return resolved


def _probe_timeout_seconds() -> int:
    configured = os.getenv("CAMOUFOX_INTEGRATION_PROBE_TIMEOUT_SECONDS", "").strip()
    if not configured:
        return _DEFAULT_TIMEOUT_SECONDS
    try:
        return max(1, int(configured))
    except ValueError:
        return _DEFAULT_TIMEOUT_SECONDS


@lru_cache(maxsize=8)
def get_external_executable_bootstrap_failure(executable_path: str | None) -> str | None:
    if not executable_path:
        return None

    if os.getenv("CAMOUFOX_DISABLE_EXECUTABLE_PROBE_XFAIL", "").strip().lower() in _ENV_TRUE:
        return None

    resolved = _resolve_executable_path(executable_path)
    if not resolved.is_file():
        return f"external executable is unavailable for the integration probe: {resolved}"

    command = [
        sys.executable,
        "-c",
        """
import asyncio
import sys
from playwright.async_api import async_playwright

async def main() -> None:
    executable_path = sys.argv[1]
    async with async_playwright() as playwright:
        browser = await playwright.firefox.launch(
            executable_path=executable_path,
            headless=True,
        )
        try:
            context = await browser.new_context(
                no_viewport=True,
                color_scheme="no-override",
                reduced_motion="no-override",
                forced_colors="no-override",
                contrast="no-override",
            )
            try:
                page = await context.new_page()
                await page.goto("about:blank", wait_until="domcontentloaded", timeout=5_000)
                await page.close()
            finally:
                await context.close()
        finally:
            await browser.close()

asyncio.run(main())
""".strip(),
        str(resolved),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_probe_timeout_seconds(),
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        return (
            f"external executable cannot bootstrap a Playwright page within "
            f"{_probe_timeout_seconds()}s: {resolved}"
        )

    if result.returncode == 0:
        return None

    detail = (result.stderr or result.stdout or "").strip().splitlines()
    if detail:
        summary = detail[-1]
    else:
        summary = f"probe exited with code {result.returncode}"

    return f"external executable cannot bootstrap a Playwright page: {summary}"
