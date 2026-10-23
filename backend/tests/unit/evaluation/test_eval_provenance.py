from cso.evaluation.panel_report import label_provenance


def test_only_claude_is_reported_as_ai_only() -> None:
    text = label_provenance(["claude", "claude"], ["claude"])
    assert text.startswith("LABELS: AI-ONLY")
    assert "not human-validated" in text


def test_no_adjudicator_still_ai_only() -> None:
    assert label_provenance(["claude"], []).startswith("LABELS: AI-ONLY")


def test_a_person_makes_it_mixed_and_is_named() -> None:
    text = label_provenance(["claude", "Yogesh"], ["claude"])
    assert text.startswith("LABELS: MIXED")
    assert "Yogesh" in text


def test_person_adjudicator_makes_it_mixed() -> None:
    assert label_provenance(["claude"], ["Yogesh"]).startswith("LABELS: MIXED")


def test_name_match_is_case_insensitive() -> None:
    assert label_provenance(["Claude"], ["CLAUDE"]).startswith("LABELS: AI-ONLY")
