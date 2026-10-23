from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import no_dashes as check

Write = Callable[[str, str], Path]
EM, EN = "—", "–"


def messages(root: Path) -> list[str]:
    return [str(f) for f in check.check(root)]


def test_the_real_repository_passes(repo_root: Path) -> None:
    assert check.check(repo_root) == []


def test_an_em_dash_and_an_en_dash_are_flagged_with_their_line(
    tmp_path: Path, write: Write
) -> None:
    write("site/src/content/docs/a.mdx", f"fine\nthis {EM} is wrong\nand 1{EN}2 too\n")
    found = messages(tmp_path)
    assert any("a.mdx:2" in m and "em dash" in m for m in found)
    assert any("a.mdx:3" in m and "en dash" in m for m in found)


def test_a_hyphen_and_a_minus_sign_are_fine(tmp_path: Path, write: Write) -> None:
    write("notes/a.md", "a - b, 1-2, − 3\n")
    assert messages(tmp_path) == []


def test_each_covered_kind_of_file_is_read(tmp_path: Path, write: Write) -> None:
    for path in (
        "README.md",
        "site/src/content/docs/page.mdx",
        "infra/stack.yaml",
        ".github/workflows/ci.yml",
        "web/src/a.ts",
        "web/src/deep/b.tsx",
        "backend/src/cso/c.py",
        "config/communities/d.yaml",
        "config/anything.txt",
        "web/public/site.webmanifest",
        "web/public/robots.txt",
    ):
        write(path, f"x {EM} y\n")
    found = messages(tmp_path)
    assert len(found) == 11


def test_the_evaluation_labels_and_results_are_allowed(tmp_path: Path, write: Write) -> None:
    write("evaluation/labels/dev.jsonl", f'{{"text": "a {EM} b"}}\n')
    write("evaluation/results/report.md", f"quoted {EM} text\n")
    write("evaluation/README.md", f"not allowed {EM} here\n")
    found = messages(tmp_path)
    assert len(found) == 1 and "evaluation/README.md" in found[0]


def test_other_file_types_and_folders_are_not_read(tmp_path: Path, write: Write) -> None:
    write("web/src/data.csv", f"a{EM}b\n")
    write("backend/src/cso/data.json", f"a{EM}b\n")
    write("web/node_modules/pkg/readme.md", f"a {EM} b\n")
    write("backend/.venv/lib/doc.md", f"a {EM} b\n")
    assert messages(tmp_path) == []


def test_a_binary_file_with_a_text_suffix_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "notes" / "weird.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe\x00\x81" + EM.encode("utf-8"))
    assert messages(tmp_path) == []
