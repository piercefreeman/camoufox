import asyncio
import os
from pathlib import Path

import pytest

import run_tests as service_tester

pytestmark = pytest.mark.integration


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_proxies_path() -> Path | None:
    configured_path = os.getenv("ROTUNDA_SERVICE_PROXIES")
    if configured_path:
        return Path(configured_path)

    default_path = Path(__file__).with_name("proxies.txt")
    if default_path.exists():
        return default_path

    return None


def test_service_tester_integration(pytestconfig: pytest.Config) -> None:
    if not pytestconfig.getoption("--integration"):
        pytest.skip("Service integration tests are disabled; pass --integration to run them.")

    proxies_path = _resolve_proxies_path()
    if proxies_path is None:
        pytest.skip(
            "Service tester requires ROTUNDA_SERVICE_PROXIES or __tests__/service-tester/proxies.txt."
        )

    executable_path = os.getenv("ROTUNDA_EXECUTABLE_PATH")
    if not executable_path:
        pytest.skip("Service tester requires ROTUNDA_EXECUTABLE_PATH.")

    exit_code = asyncio.run(
        service_tester.run_tests(
            browser_version=os.getenv("ROTUNDA_SERVICE_BROWSER_VERSION", "official/stable"),
            profile_count=int(os.getenv("ROTUNDA_SERVICE_PROFILE_COUNT", "6")),
            headful=_env_flag("ROTUNDA_SERVICE_HEADFUL"),
            proxies_path=proxies_path,
            secret=os.getenv("ROTUNDA_SERVICE_SECRET", "rotunda-service-test"),
            save_cert=os.getenv("ROTUNDA_SERVICE_SAVE_CERT"),
            no_cert=_env_flag("ROTUNDA_SERVICE_NO_CERT"),
            executable_path=executable_path,
        )
    )

    assert exit_code == 0
