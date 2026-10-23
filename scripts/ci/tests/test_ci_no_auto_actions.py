from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import check_no_auto_actions as check

Write = Callable[[str, str], Path]


def messages(root: Path) -> list[str]:
    return [str(f) for f in check.check(root)]


def test_the_real_repository_passes(repo_root: Path) -> None:
    assert check.check(repo_root) == []


def test_python_names_for_automatic_actions_are_flagged(tmp_path: Path, write: Write) -> None:
    write(
        "backend/src/cso/a.py",
        "def auto_post_comment(case):\n    return case\n"
        "def post_to_osm(x):\n    return x\n"
        "close_changeset = None\n",
    )
    found = messages(tmp_path)
    assert any("auto_post_comment" in m for m in found)
    assert any("post_to_osm" in m for m in found)
    assert any("close_changeset" in m for m in found)


def test_typescript_camel_case_names_are_flagged(tmp_path: Path, write: Write) -> None:
    write("web/src/a.ts", "const autoClose = () => 1;\nfunction hideCase() {}\n")
    found = messages(tmp_path)
    assert any("autoClose" in m for m in found)
    assert any("hideCase" in m for m in found)


def test_hyphenated_prose_and_neutral_names_are_not_flagged(tmp_path: Path, write: Write) -> None:
    write(
        "backend/src/cso/ok.py",
        '"""Never auto-post; a person posts. Nothing is auto-closed."""\n'
        "def draft_comment(case):\n    return case\n"
        "def post_ready(draft):\n    return draft\n",
    )
    write("web/src/ok.ts", "// no auto-post here\nconst closeDialog = () => 1;\n")
    assert messages(tmp_path) == []


def test_test_files_and_the_generated_client_are_skipped(tmp_path: Path, write: Write) -> None:
    write("web/src/x.test.ts", "const autoPost = 1;\n")
    write("web/src/api/gen.ts", "export const autoClose = 1;\n")
    assert messages(tmp_path) == []


def test_main_exit_codes(tmp_path: Path, write: Write) -> None:
    assert check.main(["--root", str(tmp_path)]) == 0
    write("backend/src/cso/a.py", "def auto_close_case():\n    pass\n")
    assert check.main(["--root", str(tmp_path)]) == 1
