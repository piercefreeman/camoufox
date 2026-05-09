from __future__ import annotations

import importlib
from typing import Any


def test_repo_config_autopopulates_python_library_version(monkeypatch) -> None:
    pkgman = importlib.import_module("rotunda.pkgman")
    monkeypatch.setattr(pkgman, "installed_library_version", lambda: "0.7.0")

    config = pkgman.RepoConfig.load_repos()[0]

    assert config.python_library_version == "0.7.0"
    assert config.is_version_supported(pkgman.Version(build="beta.1", version="0.7.0"))
    assert not config.is_version_supported(pkgman.Version(build="beta.1", version="0.7.1"))


def test_list_available_versions_filters_to_current_python_library_version(
    monkeypatch,
) -> None:
    pkgman = importlib.import_module("rotunda.pkgman")
    config = pkgman.RepoConfig.from_dict(
        {
            "repo": "MonkeySee-AI/rotunda",
            "name": "Official",
            "pattern": "{name}-{version}-{build}-{os}.{arch}.zip",
        },
        spoof_library_version="0.7.0",
    )

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict[str, Any]]:
            return [
                {
                    "prerelease": False,
                    "assets": [
                        {
                            "name": "rotunda-0.7.0-beta.1-mac.arm64.zip",
                            "browser_download_url": "https://example.test/0.7.0.zip",
                            "id": 1,
                        },
                        {
                            "name": "rotunda-0.7.1-beta.1-mac.arm64.zip",
                            "browser_download_url": "https://example.test/0.7.1.zip",
                            "id": 2,
                        },
                        {
                            "name": "rotunda-0.7.0-beta.1-lin.x86_64.zip",
                            "browser_download_url": "https://example.test/linux.zip",
                            "id": 3,
                        },
                    ],
                }
            ]

    monkeypatch.setattr(pkgman.requests, "get", lambda *args, **kwargs: Response())

    versions = pkgman.list_available_versions(
        config,
        spoof_os="mac",
        spoof_arch="arm64",
    )

    assert [version.version.full_string for version in versions] == ["0.7.0-beta.1"]
    assert versions[0].url == "https://example.test/0.7.0.zip"


def test_installed_browser_version_must_match_python_library_version(monkeypatch) -> None:
    pkgman = importlib.import_module("rotunda.pkgman")
    monkeypatch.setattr(pkgman, "installed_library_version", lambda: "0.7.0")

    assert pkgman.Version(build="beta.1", version="0.7.0").is_supported()
    assert not pkgman.Version(build="beta.1", version="0.7.1").is_supported()
    assert not pkgman.Version(build="beta.1").is_supported()
