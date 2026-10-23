"""Community configuration: load, validate and content-address the YAML in config/communities/."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Self

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from cso.domain.enums import Nature, Response
from cso.domain.panel import COMPOSITION_VERSION, PANEL_NOUL_IDS

CONFIG_PATH_ENV = "CSO_COMMUNITY_CONFIG"
_REPO_ROOT = Path(__file__).resolve().parents[4]  # backend/src/cso/domain/config.py -> repo root


class ConfigError(ValueError):
    """The community configuration is missing, unparsable or invalid."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Option(_Frozen):
    """One answer option of a Decider question, with UI/criteria text."""

    code: str
    label: str
    description: str


class OptionSets(_Frozen):
    """Option sets for Q1 (nature) and Q2 (response)."""

    nature: list[Option]
    response: list[Option]


class Bands(_Frozen):
    """Provisional sharpness-band thresholds."""

    confident_min: float = Field(gt=0.0, le=1.0)
    unsure_min: float = Field(gt=0.0, le=1.0)
    order_sensitivity_max: float = Field(default=0.30, ge=0.0)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.unsure_min < self.confident_min:
            raise ValueError("bands.unsure_min must be lower than bands.confident_min")
        return self


class PanelThresholds(_Frozen):
    """Tri-state cut points for panel probabilities: below `low` no, above `high` yes."""

    low: float = Field(gt=0.0, lt=1.0)
    high: float = Field(gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.low < self.high:
            raise ValueError("panel.thresholds.low must be lower than panel.thresholds.high")
        return self


class PanelBand(_Frozen):
    """Backend band from how many composed probes read `unknown` (cautious reading)."""

    confident_max_unknown: int = Field(default=1, ge=0)
    unsure_max_unknown: int = Field(default=3, ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.unsure_max_unknown < self.confident_max_unknown:
            raise ValueError(
                "panel.band.unsure_max_unknown must not be below confident_max_unknown"
            )
        return self


class CompositionOptions(_Frozen):
    """Options of the composition tables a community may switch (both off by default).

    They never touch the rules or the parsed-fact floor: they only change which table row a
    given set of readings lands on.
    """

    # P4 needs both reassurance probes (conventions and comment) to read no, not either one.
    p4_requires_both: bool = False
    # When the account may be new (its first-edits reading is unknown) and no concern probe reads
    # yes, the answer is a welcome (P4) instead of a source question (P6).
    newcomer_welcome_over_question: bool = False


#: Calibrated cut points never leave this range (ADR-010): a probe cannot be tuned into
#: calling almost everything yes or almost everything no.
CALIBRATION_MIN, CALIBRATION_MAX = 0.15, 0.85


class CalibrationRef(_Frozen):
    """The calibration whose thresholds are folded into this configuration, if any."""

    id: str = Field(min_length=1, max_length=64)


class Panel(_Frozen):
    """Fact panel: the yes/no probe ids asked of the Decider and the tri-state thresholds."""

    noul_ids: list[str]
    thresholds: PanelThresholds
    band: PanelBand = PanelBand()
    composition: CompositionOptions = CompositionOptions()
    # Per-probe cut points from a calibration; a probe not listed uses `thresholds`.
    probe_thresholds: dict[str, PanelThresholds] = Field(default_factory=dict)

    def thresholds_for(self, probe_id: str) -> PanelThresholds:
        """The cut points of one probe: its calibrated pair, else the pack default."""
        return self.probe_thresholds.get(probe_id, self.thresholds)

    @model_validator(mode="after")
    def _calibrated_in_range(self) -> Self:
        unknown = sorted(set(self.probe_thresholds) - set(self.noul_ids))
        if unknown:
            raise ValueError(f"panel.probe_thresholds names unknown probes {unknown}")
        for probe, pair in self.probe_thresholds.items():
            if not CALIBRATION_MIN <= pair.low < pair.high <= CALIBRATION_MAX:
                raise ValueError(
                    f"panel.probe_thresholds.{probe} must stay within "
                    f"[{CALIBRATION_MIN}, {CALIBRATION_MAX}]"
                )
        return self

    @model_validator(mode="after")
    def _known_ids(self) -> Self:
        if len(self.noul_ids) != len(set(self.noul_ids)):
            raise ValueError("panel.noul_ids contains duplicates")
        if set(self.noul_ids) != set(PANEL_NOUL_IDS):
            raise ValueError(
                f"panel.noul_ids {sorted(self.noul_ids)} must be exactly {sorted(PANEL_NOUL_IDS)}"
            )
        return self


class RuleConfig(_Frozen):
    """Parameters of one deterministic policy rule."""

    code: str
    label: str
    params: dict[str, Any] = Field(default_factory=dict)


# The built-in minimum of words drafts must never contain (invariant 6). Configuration can ADD to
# this set; it cannot remove entries or empty it (review F-M3). `draft_validation` also enforces the
# floor itself, so a `Tone` built in code cannot switch it off either. (The docstring of `Tone`
# stays as it was: it is part of the published OpenAPI schema.)
BANNED_WORDS_FLOOR: tuple[str, ...] = ("vandal", "vandalism", "spam", "illegal", "stop", "must")


class Tone(_Frozen):
    """Drafting tone constraints."""

    language_policy: str
    allowed_links: list[str]
    banned_words: list[str]

    @model_validator(mode="after")
    def _non_empty_words(self) -> Self:
        if any(not word.strip() for word in self.banned_words):
            raise ValueError("tone.banned_words must not contain empty entries")
        present = {word.strip().lower() for word in self.banned_words}
        missing = [word for word in BANNED_WORDS_FLOOR if word not in present]
        if missing:
            raise ValueError(
                f"tone.banned_words may add to the built-in minimum set but not remove from it; "
                f"missing {missing}"
            )
        return self


class PackInfo(_Frozen):
    """Who a pack is for and who wrote it; shown in the pack list. Not used by the decision code."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=400)
    author: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=1, max_length=20)


class CommunityConfig(_Frozen):
    """Validated community configuration; `version` is the sha256 of the canonical YAML."""

    id: str
    version: str
    pack: PackInfo | None = None
    calibration: CalibrationRef | None = None
    option_sets: OptionSets
    bands: Bands
    panel: Panel
    rules: list[RuleConfig]
    tone: Tone

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        for name, options, enum in (
            ("nature", self.option_sets.nature, Nature),
            ("response", self.option_sets.response, Response),
        ):
            codes = [o.code for o in options]
            expected = {e.value for e in enum}
            if len(codes) != len(set(codes)) or set(codes) != expected:
                raise ValueError(
                    f"option_sets.{name} codes {sorted(codes)} must be exactly {sorted(expected)}"
                )
        rule_codes = [r.code for r in self.rules]
        if len(rule_codes) != len(set(rule_codes)):
            raise ValueError("rules contain duplicate codes")
        return self

    @property
    def pack_id(self) -> str:
        """The pack this configuration belongs to (its `pack.id`, else its own `id`)."""
        return self.pack.id if self.pack else self.id

    @model_validator(mode="after")
    def _pack_matches_id(self) -> Self:
        if self.pack is not None and self.pack.id != self.id:
            raise ValueError(f"pack.id {self.pack.id!r} must equal id {self.id!r}")
        return self

    def rule(self, code: str) -> RuleConfig:
        """Return the rule with this code or raise KeyError."""
        for rule in self.rules:
            if rule.code == code:
                return rule
        raise KeyError(code)

    @classmethod
    def from_yaml_text(cls, text: str, *, source: str = "<string>") -> CommunityConfig:
        """Parse and validate YAML text; raises ConfigError with an explicit message."""
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigError(f"{source}: invalid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"{source}: top level must be a mapping")
        if "version" in data:
            raise ConfigError(f"{source}: 'version' is computed from content and must not be set")
        try:
            return cls(version=content_version(data), **data)
        except (ValidationError, TypeError) as exc:
            raise ConfigError(f"{source}: invalid community config: {exc}") from exc

    @classmethod
    def load(cls, path: Path | str | None = None) -> CommunityConfig:
        """Load `path`, else $CSO_COMMUNITY_CONFIG, else config/communities/default.yaml."""
        resolved = Path(path) if path is not None else default_config_path()
        try:
            text = resolved.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"cannot read community config {resolved}: {exc}") from exc
        return cls.from_yaml_text(text, source=str(resolved))

    @classmethod
    def load_all_with_text(
        cls, directory: Path | str | None = None
    ) -> dict[str, tuple[CommunityConfig, str]]:
        """Every `*.yaml` pack in `directory` (default: the folder of the default config), by id,
        each with the exact file text whose content hash names its version.

        Raises ConfigError when a file is invalid (a pack that removes a built-in banned word is
        invalid) or when two files use the same pack id.
        """
        folder = Path(directory) if directory is not None else default_config_path().parent
        try:
            files = sorted(folder.glob("*.yaml"))
        except OSError as exc:
            raise ConfigError(f"cannot read the pack folder {folder}: {exc}") from exc
        packs: dict[str, tuple[CommunityConfig, str]] = {}
        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise ConfigError(f"cannot read community config {path}: {exc}") from exc
            config = cls.from_yaml_text(text, source=str(path))
            if config.pack_id in packs:
                raise ConfigError(f"{path}: pack id {config.pack_id!r} is used by two files")
            packs[config.pack_id] = (config, text)
        return packs

    @classmethod
    def load_all(cls, directory: Path | str | None = None) -> dict[str, CommunityConfig]:
        """Every pack in `directory` by id (see `load_all_with_text`)."""
        return {pack_id: pair[0] for pack_id, pair in cls.load_all_with_text(directory).items()}


def default_config_path() -> Path:
    """Path of the default community config (env override for deployments without the repo tree)."""
    override = os.environ.get(CONFIG_PATH_ENV)
    return Path(override) if override else _REPO_ROOT / "config" / "communities" / "default.yaml"


def content_version(data: dict[str, Any]) -> str:
    """Content-address parsed config data: sha256 over canonical (key-sorted, compact) JSON.

    The hash covers the whole file (so the pack id and its metadata are in it) and the version of
    the composition code, so a change to the P and N tables makes a new version too (review F-M20).
    """
    payload = {"composition": COMPOSITION_VERSION, "config": data}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
