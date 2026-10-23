from __future__ import annotations

import ast
from pathlib import Path

import pytest

from cso.adapters.osm import ReplayClient, collect
from cso.domain.config import CommunityConfig
from cso.domain.evidence import render
from cso.domain.fixtures import load_case
from cso.domain.models import EvidenceSnapshot
from cso.evaluation.label_cli import adjudication_prompt, label_session
from cso.evaluation.labels import LabelStore, adjudicate

CASES = Path(__file__).resolve().parents[3] / "fixtures" / "cases"
SRC = Path(__file__).resolve().parents[3] / "src" / "cso" / "evaluation"
FORBIDDEN_IMPORT_PARTS = ("decider", "runner", "baselines", "spike")
CONFIG = CommunityConfig.load()


async def _snapshots(*names: str) -> dict[int, EvidenceSnapshot]:
    out: dict[int, EvidenceSnapshot] = {}
    for name in names:
        case_dir = next(d for d in CASES.iterdir() if d.name.startswith(name))
        cs = load_case(case_dir).expected.changeset_id
        out[cs] = await collect(ReplayClient(case_dir), cs)
    return out


class Script:
    """Scripted answers; records everything printed."""

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.printed: list[str] = []

    def input(self, _prompt: str) -> str:
        return self.answers.pop(0)

    def print(self, text: str) -> None:
        self.printed.append(text)

    @property
    def output(self) -> str:
        return "\n".join(self.printed)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
            names += [f"{node.module}.{a.name}" for a in node.names]
    return names


@pytest.mark.parametrize("module", ["label_cli.py", "labels.py"])
def test_labelling_modules_never_import_model_code(module: str) -> None:
    for imported in _imports(SRC / module):
        assert not any(part in imported for part in FORBIDDEN_IMPORT_PARTS), imported


async def test_labeller_sees_rendered_evidence_and_menus_only(tmp_path: Path) -> None:
    snaps = await _snapshots("01", "02")
    store = LabelStore(tmp_path / "dev.jsonl", "dev")
    script = Script(["1", "1", "2", "2"])  # two items: nature 1/response 1, nature 2/response 2
    labelled = label_session(
        store=store,
        ids=list(snaps),
        snapshots=lambda cs: snaps[cs],
        config=CONFIG,
        labeller="me",
        session="s1",
        input_fn=script.input,
        print_fn=script.print,
    )
    assert labelled == 2
    out = script.output
    for snapshot in snaps.values():
        assert render(snapshot, CONFIG).text in out
    lowered = out.lower()
    for leaked in (
        "probab",
        "k=3",
        "decider",
        "rule baseline",
        "weak",
        "maproulette",
        "confidence",
    ):
        assert leaked not in lowered, leaked
    rows = store.rows()
    assert len(rows) == 2 and {r.session for r in rows} == {"s1"}


async def test_session_resumes_skips_and_quits(tmp_path: Path) -> None:
    snaps = await _snapshots("01", "02", "05")
    store = LabelStore(tmp_path / "dev.jsonl", "dev")
    kwargs = dict(
        store=store,
        ids=list(snaps),
        snapshots=lambda cs: snaps[cs],
        config=CONFIG,
        labeller="me",
        session="s1",
    )
    first = Script(["1", "1", "q"])  # label one item, then quit
    assert label_session(**kwargs, input_fn=first.input, print_fn=first.print) == 1  # type: ignore[arg-type]
    second = Script(["s", "5", "6"])  # skip one, label the other as ambiguous
    assert label_session(**kwargs, input_fn=second.input, print_fn=second.print) == 1  # type: ignore[arg-type]
    done = {r.changeset_id for r in store.rows()}
    assert len(done) == 2  # the skipped item is still pending
    assert any(r.nature == "ambiguous" for r in store.rows())


async def test_invalid_answers_reprompt(tmp_path: Path) -> None:
    snaps = await _snapshots("01")
    store = LabelStore(tmp_path / "dev.jsonl", "dev")
    script = Script(["9", "x", "2", "0", "3"])
    label_session(
        store=store,
        ids=list(snaps),
        snapshots=lambda cs: snaps[cs],
        config=CONFIG,
        labeller="me",
        session="s1",
        input_fn=script.input,
        print_fn=script.print,
    )
    row = store.rows()[0]
    assert (row.nature, row.response) == ("likely_good_faith_mistake", "ask_source_question")
    assert "enter 1-5" in script.output


async def test_adjudication_shows_evidence_and_both_labels_but_no_model_output(
    tmp_path: Path,
) -> None:
    snaps = await _snapshots("01")
    (cs,) = snaps
    store = LabelStore(tmp_path / "dev.jsonl", "dev")
    store.append(
        changeset_id=cs,
        labeller="me",
        session="s1",
        nature="consistent_edit",
        response="no_action_suggested",
    )
    store.append(
        changeset_id=cs,
        labeller="me",
        session="s2",
        nature="needs_local_knowledge",
        response="request_local_check",
    )
    script = Script(["4", "4"])
    gold, _ = adjudicate(
        store,
        session_a=("me", "s1"),
        session_b=("me", "s2"),
        decide=adjudication_prompt(
            snapshots=lambda c: snaps[c],
            config=CONFIG,
            input_fn=script.input,
            print_fn=script.print,
        ),
        adjudicator="adj",
    )
    assert (gold[0].nature, gold[0].response) == ("needs_local_knowledge", "request_local_check")
    assert "session A: nature=consistent_edit" in script.output
    assert "probab" not in script.output.lower()
