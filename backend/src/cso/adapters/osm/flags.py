"""Stage-1 flags: eight reason strings computed offline from already-fetched data.

Everything here is original to this project. The reason strings are a fixed vocabulary that the
policy gate, the stored snapshots and the demo fixtures already use, so they keep their spelling:
`suspect_word`, `Software editor was not declared`, `Review requested`, `possible import`,
`mass modification`, `mass deletion`, `New mapper`, `User has multiple blocks`.

No network call and no third-party code is involved. The rules read the fetched `changeset.json`
envelope, the element counts per action from the parsed osmChange, and the fetched `user.json`
envelope. Flags are parsed evidence: they order the queue and are shown to the reviewer, they never
hide a case, and a rule whose input is missing is skipped.

The suspect word list lives in `suspect_words.txt` next to this module (original, Apache-2.0).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import cache
from importlib import resources
from typing import Any

from cso.adapters.osm.errors import OsmError
from cso.domain.enums import ChangeAction

NEW_MAPPER_MAX_CHANGESETS = 50  # "New mapper" when the user has 50 changesets or fewer
MULTIPLE_BLOCKS_MIN = 2  # "User has multiple blocks" from two received blocks

# Element-count rules. One action must make up more than DOMINANT_SHARE of all elements and pass
# its own minimum. These numbers are this project's own choices, not values taken from another tool.
DOMINANT_SHARE = 0.7
IMPORT_MIN_POWER_EDITOR = 250  # creations needed when the editor is made for bulk work
IMPORT_MIN_OTHER_EDITOR = 1000  # creations needed for any other editor
MODIFY_MIN = 250
DELETE_MIN = 100
DELETE_MIN_ANY_SHARE = 1000  # this many deletions are flagged whatever the share

# `created_by` values (lower case, matched at the start) of editors built for bulk or desktop work.
POWER_EDITORS = ("josm", "merkaartor", "level0", "qgis")

REASON_SUSPECT_WORD = "suspect_word"
REASON_NO_EDITOR = "Software editor was not declared"
REASON_REVIEW_REQUESTED = "Review requested"
REASON_IMPORT = "possible import"
REASON_MASS_MODIFICATION = "mass modification"
REASON_MASS_DELETION = "mass deletion"
REASON_NEW_MAPPER = "New mapper"
REASON_MULTIPLE_BLOCKS = "User has multiple blocks"

_WORD_FILE = "suspect_words.txt"
_TEXT_TAGS = ("comment", "source", "imagery_used")


class FlagsUnavailableError(OsmError):
    """The suspect word list could not be read (packaging problem)."""


@cache
def load_suspect_words() -> tuple[str, ...]:
    """Entries of `suspect_words.txt`, lower case, without comments or blank lines."""
    try:
        text = (resources.files("cso.adapters.osm") / _WORD_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeError, ModuleNotFoundError) as exc:
        raise FlagsUnavailableError(f"suspect word list unavailable: {exc}") from exc
    words = []
    for line in text.splitlines():
        entry = line.strip().casefold()
        if entry and not entry.startswith("#"):
            words.append(" ".join(entry.split()))
    return tuple(words)


@cache
def _suspect_pattern() -> re.Pattern[str] | None:
    words = load_suspect_words()
    if not words:
        return None
    alternatives = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


def _has_suspect_word(tags: Mapping[str, Any]) -> bool:
    pattern = _suspect_pattern()
    if pattern is None:
        return False
    return any(
        isinstance(tags.get(key), str) and pattern.search(tags[key]) is not None
        for key in _TEXT_TAGS
    )


def _editor_declared(tags: Mapping[str, Any]) -> bool:
    value = tags.get("created_by")
    return isinstance(value, str) and bool(value.strip())


def _is_power_editor(tags: Mapping[str, Any]) -> bool:
    value = tags.get("created_by")
    return isinstance(value, str) and value.strip().casefold().startswith(POWER_EDITORS)


def compute_flags(
    changeset_raw: Mapping[str, Any],
    *,
    action_counts: Mapping[ChangeAction, int] | None = None,
    user_raw: Mapping[str, Any] | None = None,
) -> list[str]:
    """Reason strings for a fetched `changeset.json` envelope, deduplicated and sorted.

    `action_counts` are element counts per action from the parsed osmChange (enables the
    import/mass-modification/mass-deletion rules); `user_raw` is the `user/{uid}.json` envelope
    (enables the new-mapper and multiple-blocks rules). Missing inputs skip their rules.
    """
    cs = changeset_raw.get("changeset")
    if not isinstance(cs, Mapping):
        raise ValueError("changeset_raw must contain a 'changeset' object")
    raw_tags = cs.get("tags")
    tags: Mapping[str, Any] = raw_tags if isinstance(raw_tags, Mapping) else {}

    reasons: set[str] = set()
    if _has_suspect_word(tags):
        reasons.add(REASON_SUSPECT_WORD)
    if not _editor_declared(tags):
        reasons.add(REASON_NO_EDITOR)
    if tags.get("review_requested") == "yes":
        reasons.add(REASON_REVIEW_REQUESTED)
    if action_counts is not None:
        reasons.update(_count_rules(action_counts, power_editor=_is_power_editor(tags)))
    if user_raw is not None:
        reasons.update(_user_rules(user_raw))
    return sorted(reasons)


def _count_rules(counts: Mapping[ChangeAction, int], *, power_editor: bool) -> set[str]:
    """At most one of import, mass modification, mass deletion, from the element counts."""
    create = counts.get(ChangeAction.CREATE, 0)
    modify = counts.get(ChangeAction.MODIFY, 0)
    delete = counts.get(ChangeAction.DELETE, 0)
    total = create + modify + delete
    if total == 0:
        return set()
    import_min = IMPORT_MIN_POWER_EDITOR if power_editor else IMPORT_MIN_OTHER_EDITOR
    if create / total > DOMINANT_SHARE and create > import_min:
        return {REASON_IMPORT}
    if modify / total > DOMINANT_SHARE and modify > MODIFY_MIN:
        return {REASON_MASS_MODIFICATION}
    if (delete / total > DOMINANT_SHARE and delete > DELETE_MIN) or delete > DELETE_MIN_ANY_SHARE:
        return {REASON_MASS_DELETION}
    return set()


def _user_rules(user_raw: Mapping[str, Any]) -> set[str]:
    """New-mapper and multiple-blocks rules over a fetched user.json."""
    user = user_raw.get("user")
    if not isinstance(user, Mapping):
        return set()
    reasons: set[str] = set()
    count = (user.get("changesets") or {}).get("count")
    if isinstance(count, int) and count <= NEW_MAPPER_MAX_CHANGESETS:
        reasons.add(REASON_NEW_MAPPER)
    blocks = ((user.get("blocks") or {}).get("received") or {}).get("count")
    if isinstance(blocks, int) and blocks >= MULTIPLE_BLOCKS_MIN:
        reasons.add(REASON_MULTIPLE_BLOCKS)
    return reasons
