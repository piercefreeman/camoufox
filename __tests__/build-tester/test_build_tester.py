import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

BUILD_TESTER_DIR = Path(__file__).resolve().parent
RUNNER = BUILD_TESTER_DIR / "scripts" / "run_tests.py"


def test_build_tester_integration(pytestconfig: pytest.Config) -> None:
    if not pytestconfig.getoption("--integration"):
        pytest.skip("Build integration tests are disabled; pass --integration to run them.")

    executable_path = os.getenv("CAMOUFOX_EXECUTABLE_PATH")
    if not executable_path:
        pytest.skip("Build tester requires CAMOUFOX_EXECUTABLE_PATH.")

    command = [
        sys.executable,
        str(RUNNER),
        executable_path,
        "--profile-count",
        os.getenv("CAMOUFOX_BUILD_TESTER_PROFILE_COUNT", "8"),
        "--secret",
        os.getenv("CAMOUFOX_BUILD_TESTER_SECRET", "camoufox-tester-dev-secret"),
    ]

    if save_cert := os.getenv("CAMOUFOX_BUILD_TESTER_SAVE_CERT"):
        command.extend(["--save-cert", save_cert])
    if os.getenv("CAMOUFOX_BUILD_TESTER_NO_CERT", "").strip().lower() in {"1", "true", "yes", "on"}:
        command.append("--no-cert")

    result = subprocess.run(
        command,
        cwd=BUILD_TESTER_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
    assert result.returncode == 0
