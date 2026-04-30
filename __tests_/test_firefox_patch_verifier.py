from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import verify_firefox_patches as verifier


def test_parse_patch_entries_handles_modify_create_and_delete(tmp_path: Path) -> None:
    patch_path = tmp_path / "sample.patch"
    patch_path.write_text(
        """\
diff --git a/foo.cpp b/foo.cpp
--- a/foo.cpp
+++ b/foo.cpp
@@ -1 +1 @@
-old
+new
diff --git a/new.h b/new.h
--- /dev/null
+++ b/new.h
@@ -0,0 +1 @@
+#pragma once
diff --git a/old.h b/old.h
--- a/old.h
+++ /dev/null
@@ -1 +0,0 @@
-#pragma once
""",
        encoding="utf-8",
    )

    entries = verifier.parse_patch_entries(patch_path)

    assert entries == [
        verifier.PatchEntry(old_path="foo.cpp", new_path="foo.cpp"),
        verifier.PatchEntry(old_path=None, new_path="new.h"),
        verifier.PatchEntry(old_path="old.h", new_path=None),
    ]


def test_order_patch_paths_moves_roverfox_to_the_end() -> None:
    paths = [
        Path("/repo/patches/zeta.patch"),
        Path("/repo/patches/roverfox/core.patch"),
        Path("/repo/patches/alpha.patch"),
    ]

    ordered = verifier.order_patch_paths(paths)

    assert ordered == [
        Path("/repo/patches/zeta.patch"),
        Path("/repo/patches/alpha.patch"),
        Path("/repo/patches/roverfox/core.patch"),
    ]


def test_unique_paths_normalizes_deduplicates_and_sorts() -> None:
    assert verifier.unique_paths(
        [
            "browser/../dom/base/File.cpp",
            "dom/base/File.cpp",
            "dom\\base\\Other.cpp",
        ]
    ) == [
        "dom/base/File.cpp",
        "dom/base/Other.cpp",
    ]


def test_parse_patch_entries_requires_complete_header_pairs(tmp_path: Path) -> None:
    patch_path = tmp_path / "broken.patch"
    patch_path.write_text(
        """\
diff --git a/foo.cpp b/foo.cpp
--- a/foo.cpp
""",
        encoding="utf-8",
    )

    try:
        verifier.parse_patch_entries(patch_path)
    except ValueError as exc:
        assert "Unterminated patch header sequence" in str(exc)
    else:
        raise AssertionError("Expected parse_patch_entries to reject unterminated headers")
