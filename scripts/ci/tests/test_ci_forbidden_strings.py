from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import check_forbidden_strings as check

Write = Callable[[str, str], Path]


def messages(root: Path) -> list[str]:
    return [str(f) for f in check.check(root)]


def test_the_real_repository_passes(repo_root: Path) -> None:
    assert check.check(repo_root) == []


def test_strong_words_are_flagged_anywhere_in_a_source_file(tmp_path: Path, write: Write) -> None:
    write("web/src/a.tsx", "// remove the vandalism label\nexport const x = 1;\n")
    found = messages(tmp_path)
    assert any("a.tsx:1" in m and "vandalism" in m for m in found)


def test_spam_and_illegal_are_flagged_in_css_and_json(tmp_path: Path, write: Write) -> None:
    write("web/src/s.css", ".spam-banner { color: red }\n")
    write("web/src/messages/en.json", '{"a": "this looks illegal"}\n')
    found = messages(tmp_path)
    assert any("s.css" in m for m in found)
    assert any("en.json" in m for m in found)


def test_stop_and_must_are_flagged_only_in_string_literals(tmp_path: Path, write: Write) -> None:
    write(
        "web/src/b.ts",
        "event.stopPropagation();\n"
        "const mustard = 1;\n"
        'export const label = "You must review this";\n'
        "export const other = `Please stop here`;\n",
    )
    found = messages(tmp_path)
    assert any("b.ts:3" in m and "'must'" in m for m in found)
    assert any("b.ts:4" in m and "'stop'" in m for m in found)
    assert not any("b.ts:1" in m or "b.ts:2" in m for m in found)


def test_message_catalogue_values_are_checked_for_stop_and_must(
    tmp_path: Path, write: Write
) -> None:
    write(
        "web/src/messages/en.json",
        '{"ok": "Review when ready", "bad": "You must act"}\n',
    )
    found = messages(tmp_path)
    assert any("message 'bad'" in m for m in found)
    assert not any("message 'ok'" in m for m in found)


def test_tests_generated_client_and_fonts_are_skipped(tmp_path: Path, write: Write) -> None:
    write("web/src/x.test.ts", 'expect("vandalism must stop").toBe(1);\n')
    write("web/src/api/sdk.gen.ts", 'export const d = "illegal must stop";\n')
    write("web/src/test/helper.ts", "// spam\n")
    write("web/src/fonts/LICENSE.txt", "illegal\n")
    assert messages(tmp_path) == []


def test_index_html_is_checked(tmp_path: Path, write: Write) -> None:
    write("web/index.html", "<title>Spam review</title>\n")
    assert any("index.html" in m for m in messages(tmp_path))


def test_config_text_is_checked_but_the_banned_words_list_is_not(
    tmp_path: Path, write: Write
) -> None:
    write(
        "config/communities/default.yaml",
        "tone:\n"
        "  banned_words: [vandal, vandalism, spam, illegal, stop, must]\n"
        "options:\n"
        "  - label: Looks fine\n",
    )
    assert messages(tmp_path) == []
    write(
        "config/communities/bad.yaml",
        "options:\n  - description: This edit is illegal and you must stop\n",
    )
    found = messages(tmp_path)
    assert any("bad.yaml" in m for m in found)


def test_fallback_yaml_scan_skips_the_banned_words_block() -> None:
    text = "tone:\n  banned_words:\n    - vandal\n    - must\n  language: en\nlabel: fine\n"
    assert check._scan_yaml_without_pyyaml(text, "c.yaml") == []
    bad = "tone:\n  banned_words:\n    - vandal\nnote: you must go\n"
    found = check._scan_yaml_without_pyyaml(bad, "c.yaml")
    assert [f.line for f in found] == [4]


def test_main_exit_codes(tmp_path: Path, write: Write) -> None:
    assert check.main(["--root", str(tmp_path)]) == 0
    write("web/src/a.ts", "// spam\n")
    assert check.main(["--root", str(tmp_path)]) == 1
