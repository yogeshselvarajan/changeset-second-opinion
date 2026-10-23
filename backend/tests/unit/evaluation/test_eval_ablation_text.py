"""Ablation wording: every variant covers the ten probes, keeps or drops cues as designed, and the
variant request differs from the product request in the instruction strings only."""

from __future__ import annotations

import copy
import re

import pytest
from heldout_support import CONFIG, decider

from cso.adapters.decider import build_fact_panel_plan
from cso.domain.panel import PANEL_INSTRUCTIONS
from cso.evaluation.ablation_text import (
    CUE_FRAGMENTS,
    INSTRUCTION_VARIANTS,
    PARAPHRASE_NAMES,
    PRODUCT,
    WITHOUT_CUES,
    instructions_for,
)
from cso.evaluation.variants import make_variant_decide, variant_plan

BANNED = re.compile(r"(?i)vandal|\b(spam|illegal|stop|must)\b")
NUMBERS = re.compile(r"\d+")


def test_four_variants_exist_and_each_covers_exactly_the_panel_probes_in_order() -> None:
    assert set(INSTRUCTION_VARIANTS) == {WITHOUT_CUES, *PARAPHRASE_NAMES}
    assert len(PARAPHRASE_NAMES) == 3
    for name, texts in INSTRUCTION_VARIANTS.items():
        assert tuple(texts) == tuple(PANEL_INSTRUCTIONS), name
        assert all(isinstance(t, str) and t.strip() for t in texts.values())


def test_no_variant_uses_a_banned_word() -> None:
    for name, texts in INSTRUCTION_VARIANTS.items():
        for probe, text in texts.items():
            assert not BANNED.search(text), (name, probe)


def test_without_cues_drops_every_threshold_and_number() -> None:
    cues = INSTRUCTION_VARIANTS[WITHOUT_CUES]
    for probe, text in cues.items():
        assert not NUMBERS.search(text), probe
        assert not any(fragment in text for fragment in CUE_FRAGMENTS), probe
    product = " ".join(PANEL_INSTRUCTIONS.values())
    assert all(fragment in product for fragment in CUE_FRAGMENTS)  # the cues really exist there
    for probe, text in cues.items():
        assert text != PANEL_INSTRUCTIONS[probe]


def test_paraphrases_keep_every_threshold_but_change_the_words() -> None:
    seen: set[str] = set()
    for name in PARAPHRASE_NAMES:
        for probe, original in PANEL_INSTRUCTIONS.items():
            text = INSTRUCTION_VARIANTS[name][probe]
            assert NUMBERS.findall(text) == NUMBERS.findall(original), (name, probe)
            assert text != original
            assert text not in seen  # no two paraphrases share a sentence
            seen.add(text)


def test_instructions_for_returns_copies_and_rejects_unknown_names() -> None:
    assert instructions_for(PRODUCT) == dict(PANEL_INSTRUCTIONS)
    mutable = instructions_for("paraphrase_1")
    mutable["mature_feature_deleted"] = "changed"
    assert INSTRUCTION_VARIANTS["paraphrase_1"]["mature_feature_deleted"] != "changed"
    with pytest.raises(ValueError, match="unknown instruction variant"):
        instructions_for("paraphrase_9")


# ------------------------------------------------------------------------ the variant request


def test_a_variant_request_differs_from_the_product_only_in_instruction_text() -> None:
    state = "evidence text"
    product = build_fact_panel_plan(state, CONFIG)
    variant = variant_plan(state, CONFIG, instructions_for("paraphrase_2"))
    assert variant.questions_hash != product.questions_hash
    assert (variant.orders, variant.groups, variant.nouls) == (
        product.orders,
        product.groups,
        product.nouls,
    )
    normalised = copy.deepcopy(variant.request)
    for noul_id in product.nouls:
        normalised["questions"][noul_id]["instructions"] = PANEL_INSTRUCTIONS[noul_id]
    assert normalised == product.request  # state, nature question, option sets: untouched
    for noul_id in product.nouls:
        assert (
            variant.request["questions"][noul_id]["instructions"]
            == (INSTRUCTION_VARIANTS["paraphrase_2"][noul_id])
        )


def test_the_product_wording_reproduces_the_product_hash() -> None:
    product = build_fact_panel_plan("s", CONFIG)
    assert variant_plan("s", CONFIG, instructions_for(PRODUCT)).questions_hash == (
        product.questions_hash
    )


def test_a_variant_cannot_drop_or_add_a_question() -> None:
    texts = instructions_for(WITHOUT_CUES)
    missing = {k: v for k, v in texts.items() if k != "mass_retag_single_key"}
    with pytest.raises(ValueError, match="every panel probe"):
        variant_plan("s", CONFIG, missing)
    with pytest.raises(ValueError, match="every panel probe"):
        variant_plan("s", CONFIG, {**texts, "extra_probe": "True if anything."})


async def test_the_variant_decide_sends_its_wording_and_returns_a_validated_panel() -> None:
    bodies: list[dict] = []
    client = decider(bodies=bodies)
    decide = make_variant_decide(client, instructions_for(WITHOUT_CUES))
    result = await decide("some evidence", CONFIG)
    product = await client.decide_panel("some evidence", CONFIG)
    await client.aclose()
    assert len(bodies) == 2
    variant_body, product_body = bodies
    assert (
        variant_body["questions"]["new_account_first_edits"]["instructions"]
        == (INSTRUCTION_VARIANTS[WITHOUT_CUES]["new_account_first_edits"])
    )
    assert (
        product_body["questions"]["new_account_first_edits"]["instructions"]
        == (PANEL_INSTRUCTIONS["new_account_first_edits"])
    )
    assert variant_body["state"] == product_body["state"] == "some evidence"
    assert result.questions_hash != product.questions_hash
    assert set(result.panel.readings) == set(PANEL_INSTRUCTIONS)
