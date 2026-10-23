from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import check_docs as check

Write = Callable[[str, str], Path]


def messages(root: Path) -> list[str]:
    return [str(f) for f in check.check(root)]


def test_the_real_repository_passes(repo_root: Path) -> None:
    assert check.check(repo_root) == []


def test_slugs_follow_github(repo_root: Path) -> None:
    assert check.slug("What it cannot do yet") == "what-it-cannot-do-yet"
    assert check.slug("Licences and attribution") == "licences-and-attribution"
    assert check.slug("`cso eval` and **friends**") == "cso-eval-and-friends"
    assert check.slug("A [link](x.md) here") == "a-link-here"
    assert check.slug("Ten questions, not one verdict") == "ten-questions-not-one-verdict"


def test_repeated_headings_get_numbered_anchors() -> None:
    assert check.anchors("# A\n## B\n## B\n") == {"a", "b", "b-1"}


def test_a_broken_relative_link_is_flagged_with_its_line(tmp_path: Path, write: Write) -> None:
    write("README.md", "fine\nsee [the guide](guides/guide.md) now\n")
    assert messages(tmp_path) == ["README.md:2: broken link: guides/guide.md"]


def test_a_link_to_an_existing_file_directory_and_heading_passes(
    tmp_path: Path, write: Write
) -> None:
    write("guides/guide.md", "# Guide\n\n## Set up\n")
    write(
        "README.md",
        "[a](guides/guide.md) [b](guides/) [c](guides/guide.md#set-up) [d](#top)\n# Top\n",
    )
    assert messages(tmp_path) == []


def test_a_missing_heading_is_flagged(tmp_path: Path, write: Write) -> None:
    write("guides/guide.md", "# Guide\n")
    write("README.md", "[a](guides/guide.md#nowhere) and [b](#also-nowhere)\n")
    found = messages(tmp_path)
    assert len(found) == 2 and all("no such heading" in m for m in found)


def test_web_links_are_not_fetched_and_code_is_ignored(tmp_path: Path, write: Write) -> None:
    write(
        "README.md",
        "[x](https://example.org/nope) [m](mailto:a@b.c)\n"
        "`[no](missing.md)`\n"
        "```\n[no](missing.md)\n```\n",
    )
    assert messages(tmp_path) == []


def test_images_and_html_sources_are_checked(tmp_path: Path, write: Write) -> None:
    write("images/a.png", "x")
    write(
        "README.md",
        '![ok](images/a.png)\n<img src="images/b.png">\n<source srcset="images/c.png">\n',
    )
    found = messages(tmp_path)
    assert [m.split(": ", 1)[1] for m in found] == [
        "broken link: images/b.png",
        "broken link: images/c.png",
    ]


def test_reference_style_links_are_checked(tmp_path: Path, write: Write) -> None:
    write("README.md", "[see][g]\n\n[g]: guides/gone.md\n")
    assert messages(tmp_path) == ["README.md:3: broken link: guides/gone.md"]


def test_a_link_out_of_the_repository_is_flagged(tmp_path: Path, write: Write) -> None:
    write("README.md", "[x](../elsewhere.md)\n")
    assert "leaves the repository" in messages(tmp_path)[0]


def test_the_plain_writing_rules(tmp_path: Path, write: Write) -> None:
    write(
        "README.md",
        "# Why does it work?\n\nWe leverage a robust, seamless design!\n\n"
        "It is powerful and cutting-edge, AI-powered even.\n",
    )
    found = " | ".join(messages(tmp_path))
    for expected in (
        "heading is a question",
        "'leverage'",
        "'robust'",
        "'seamless'",
        "exclamation mark",
        "'powerful'",
        "'cutting-edge'",
        "'AI-powered'",
    ):
        assert expected in found, expected


def test_code_and_urls_do_not_trip_the_style_rules(tmp_path: Path, write: Write) -> None:
    write(
        "README.md",
        "Run `robust!` and see [it](https://example.org/powerful!).\n"
        "```\nleverage!\n```\nA clean sentence.\n",
    )
    assert messages(tmp_path) == []


def test_a_long_list_is_flagged_once_and_a_short_one_is_not(tmp_path: Path, write: Write) -> None:
    items = "".join(f"- item {i}\n" for i in range(8))
    write("README.md", f"Intro\n\n{items}\nNext paragraph\n\n- a\n- b\n")
    found = messages(tmp_path)
    assert len(found) == 1 and "longer than 7" in found[0]


def test_nested_items_and_separate_lists_do_not_add_up(tmp_path: Path, write: Write) -> None:
    nested = "- a\n  - n1\n  - n2\n  - n3\n  - n4\n- b\n- c\n- d\n- e\n- f\n"
    write("README.md", f"{nested}\nA paragraph breaks the list.\n\n{nested}")
    assert messages(tmp_path) == []


def test_only_the_named_files_are_held_to_the_style_rules(tmp_path: Path, write: Write) -> None:
    write("notes/other.md", "We leverage this!\n")
    assert messages(tmp_path) == []
