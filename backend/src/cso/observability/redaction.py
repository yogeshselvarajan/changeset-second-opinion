"""Log redaction: secrets never reach a log line, user names are hashed, evidence is truncated.

Applied as a structlog processor after exception formatting, so it also scrubs tracebacks and
the text of exceptions. Rules:

* values under secret-looking keys (sessions, CSRF, invite codes, tokens, API keys, `Cookie`,
  `Authorization` ...) are replaced wholesale;
* strings are scrubbed for invite codes, session or CSRF cookie assignments, bearer tokens, AWS
  access keys, `key=value` secrets and bare 43-character url-safe tokens (the shape of session
  and CSRF tokens);
* user and author names are replaced by a stable short hash, so lines can still be correlated;
* long text is truncated, evidence-like fields much more tightly, so content is logged by id.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, MutableMapping
from typing import Any

REDACTED = "<redacted>"
MAX_STRING = 300
EVIDENCE_STRING = 80

_SECRET_KEY = re.compile(
    r"(authorization|cookie|csrf|x-csrf|session|invite|passw|secret|token|api[_-]?key|"
    r"access[_-]?key|credential|signature)",
    re.IGNORECASE,
)
# Keys that look like secrets by name but are plain facts or counters.
_SECRET_KEY_ALLOW = frozenset(
    {"session_factory", "session_count", "sessions", "tokens", "input_tokens", "output_tokens"}
)
_USER_KEYS = frozenset(
    {
        "user",
        "username",
        "user_name",
        "display_name",
        "author",
        "reviewer",
        "mapper",
        "labeller",
        "actor",
    }
)
_NOT_PERSONAL = frozenset({"system", "anonymous", "worker", "api", "claude", ""})
_EVIDENCE_KEYS = frozenset(
    {"evidence", "rendered_text", "comment", "text", "discussion", "tags", "raw", "body", "state"}
)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"cso-[0-9a-f]{8}-[A-Za-z0-9_-]{8,}"), "cso-<redacted>"),
    (re.compile(r"(?i)\b(cso_session|cso_csrf)=[^;\s,]+"), r"\1=<redacted>"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 <redacted>"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "<redacted-aws-key>"),
    (
        re.compile(
            r"(?i)\b(aws_secret_access_key|api[_-]?key|secret|passw(?:or)?d|token|csrf|session)"
            r"(\s*[=:]\s*)[^\s,;&\"']+"
        ),
        r"\1\2<redacted>",
    ),
    # Session and CSRF tokens are 32 random bytes in url-safe base64: exactly 43 characters.
    (re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])"), "<redacted-token>"),
)


def hash_name(name: str) -> str:
    """A stable, non-reversible handle for a user name (same input, same output)."""
    return "u_" + hashlib.sha256(f"cso-log:{name}".encode()).hexdigest()[:10]


def scrub_text(text: str) -> str:
    """Remove secret-shaped substrings from a string."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...[+{len(text) - limit} chars]"


def _is_secret_key(key: str) -> bool:
    return key not in _SECRET_KEY_ALLOW and bool(_SECRET_KEY.search(key))


def redact_value(key: str, value: Any) -> Any:
    """Redact one value according to its key (recursing into mappings and sequences)."""
    lowered = key.lower()
    if _is_secret_key(lowered):
        return REDACTED
    if lowered in _USER_KEYS and isinstance(value, str):
        return value if value.lower() in _NOT_PERSONAL else hash_name(value)
    if isinstance(value, Mapping):
        return {str(k): redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact_value(key, v) for v in value]
    if isinstance(value, str):
        limit = EVIDENCE_STRING if lowered in _EVIDENCE_KEYS else MAX_STRING
        return _truncate(scrub_text(value), limit)
    return value


def redact_event(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> dict[str, Any]:
    """The structlog processor: returns a redacted copy of the event."""
    return {key: redact_value(key, value) for key, value in event_dict.items()}
