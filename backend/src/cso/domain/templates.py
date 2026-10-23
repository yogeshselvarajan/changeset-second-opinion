"""Offline comment templates, one per comment type.

Used whenever the model is unavailable, over budget, refused, or its draft failed validation twice,
and in replay mode. They state no facts about the changeset, so they cite no evidence, and they
pass the same validator as a model draft. English only: a draft in the mapper's own language needs
the model, and a person edits every draft before anything is posted.
"""

from __future__ import annotations

from cso.domain.config import Tone
from cso.domain.draft_validation import DraftFields
from cso.domain.enums import Response

TEMPLATE_VERSION = "template-v1"

_GREETING = {
    Response.WELCOME_AND_TIPS: "Hello, and welcome to OpenStreetMap!",
    Response.ASK_SOURCE_QUESTION: "Hello, and thank you for your edit.",
    Response.REQUEST_LOCAL_CHECK: "Hello, and thank you for your work on this area.",
}

_CLOSING = {
    Response.WELCOME_AND_TIPS: "Happy mapping!",
    Response.ASK_SOURCE_QUESTION: "Thanks for your help!",
    Response.REQUEST_LOCAL_CHECK: "Thank you!",
}

_BODY = {
    Response.WELCOME_AND_TIPS: (
        "Thank you for contributing to the map. I had a look at your recent changeset and wanted "
        "to share a few friendly pointers. The wiki{link} has short guides on tagging and on "
        "noting where your information comes from, and the community is happy to help if "
        "anything is unclear."
    ),
    Response.ASK_SOURCE_QUESTION: (
        "I could not tell from the changeset where the information came from. Could you share "
        "the source, for example a survey, imagery or another reference? Adding it to the "
        "changeset helps other mappers follow along. Guidance on sources is on the wiki{link}."
    ),
    Response.REQUEST_LOCAL_CHECK: (
        "A few of the changes in this changeset are hard to confirm from tags and history alone. "
        "If you know the area, could you take a quick look and say whether they match what is on "
        "the ground? Local knowledge is very helpful here, and any note is welcome."
    ),
}

TEMPLATE_RESPONSES = frozenset(_BODY)


def template_fields(response_type: Response, tone: Tone) -> DraftFields:
    """The template for a comment type; ValueError for a response that is not a comment type."""
    if response_type not in _BODY:
        raise ValueError(f"no comment template for {response_type.value}")
    wiki = next((link for link in tone.allowed_links if link.strip()), None)
    link = f" ({wiki})" if wiki else ""
    return DraftFields(
        greeting=_GREETING[response_type],
        body=_BODY[response_type].format(link=link),
        closing=_CLOSING[response_type],
        cited_evidence_ids=(),
    )
