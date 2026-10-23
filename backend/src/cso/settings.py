from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

USER_AGENT_PLACEHOLDERS = (
    "<REPO_URL>",
    "<CONTACT_EMAIL>",
    "https://github.com/changeset-second-opinion",  # the placeholder used before the guard existed
)
DEFAULT_USER_AGENT = "ChangesetSecondOpinion/0.1 (+<REPO_URL>; <CONTACT_EMAIL>)"


class SettingsError(ValueError):
    """Settings are unusable for the selected mode."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CSO_", env_file=".env", extra="ignore")

    # Each field's description is the text of the generated settings reference in the docs site
    # (site/scripts), so write it for a reader who has never opened this file.
    mode: Literal["replay", "live"] = Field(
        default="replay",
        description=(
            "replay serves saved changesets and never calls OpenStreetMap, the Decider or Amazon "
            "Bedrock. live fetches from OpenStreetMap (GET only) and needs a real CSO_USER_AGENT."
        ),
    )
    database_url: str = Field(
        default="sqlite+aiosqlite:///./cso.db",
        description="SQLAlchemy URL of the database. SQLite by default, one file next to the app.",
    )
    decider_url: str | None = Field(
        default=None,
        description=(
            "Address of the Strands Decider server, for example http://127.0.0.1:8099. Without "
            "it a case is shown with its evidence and rules only, in the Rules only lane."
        ),
    )
    decider_device_class: Literal["gpu", "cpu"] = Field(
        default="gpu",
        description=(
            "The hardware the Decider runs on. It sets the call timeout: 45 s for gpu and "
            "90 s for cpu."
        ),
    )
    bedrock_region: str = Field(
        default="us-east-1", description="AWS region used for Amazon Bedrock draft calls."
    )
    bedrock_model_id: str = Field(
        default="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        description=(
            "Bedrock model or inference profile id that writes draft comments (Claude Haiku 4.5)."
        ),
    )
    user_agent: str = Field(
        default=DEFAULT_USER_AGENT,
        description=(
            "The User-Agent sent to OpenStreetMap and MapRoulette. The OpenStreetMap usage "
            "policy asks for a real repository address and a contact email. Live mode refuses "
            "to start while the placeholders are still in it."
        ),
    )
    jobs_worker_enabled: bool = Field(
        default=True,
        description=(
            "Run the background worker inside the API process. "
            "Turn off when cso worker runs on its own."
        ),
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", description="Log verbosity."
    )
    log_format: Literal["auto", "json", "console"] = Field(
        default="auto",
        description="auto writes JSON in live mode and a readable console format in replay mode.",
    )
    daily_analysis_cap: int = Field(
        default=200,
        description=(
            "Most analyses per UTC day, counted from the jobs table so a restart does not "
            "reset it. 0 allows none (fail closed). A negative value turns the cap off."
        ),
    )
    daily_draft_cap: int = Field(
        default=100,
        description="Most drafts per UTC day. 0 allows none. A negative value turns the cap off.",
    )
    bedrock_daily_usd_cap: float = Field(
        default=10.0,
        description=(
            "Estimated Bedrock spend allowed per UTC day, in US dollars. Calls past it are refused."
        ),
    )
    bedrock_input_usd_per_mtok: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Override of the estimated input price, in US dollars per million tokens. Empty uses "
            "the built-in estimate, which you should check against current Bedrock pricing."
        ),
    )
    bedrock_output_usd_per_mtok: float | None = Field(
        default=None,
        ge=0,
        description="Override of the estimated output price, in US dollars per million tokens.",
    )
    osm_oauth_client_id: str | None = Field(
        default=None,
        description=(
            "Client id of the OpenStreetMap OAuth application. Sign in with OpenStreetMap is on "
            "only when this, the secret and the redirect URL are all set."
        ),
    )
    osm_oauth_client_secret: SecretStr | None = Field(
        default=None,
        description=(
            "Client secret of the OpenStreetMap OAuth application. It is shown once when you "
            "register the app. It is never logged or shown, and never written to the web bundle."
        ),
    )
    osm_oauth_redirect_url: str | None = Field(
        default=None,
        description=(
            "Where OpenStreetMap sends the browser after sign-in, ending in "
            "/api/v1/auth/osm/callback. It has to be https, or http on a loopback address such "
            "as 127.0.0.1."
        ),
    )
    osm_signin_allowed_uids: str = Field(
        default="",
        description=(
            "Optional. Comma-separated OpenStreetMap user ids. When set, only these accounts can "
            "sign in with OpenStreetMap. Empty lets every account in."
        ),
    )
    bootstrap_admin_osm_uids: str = Field(
        default="",
        description=(
            "Comma-separated OpenStreetMap user ids that may become the workspace admin. It says "
            "who, so it is not a secret: OpenStreetMap proves who is signing in. Only a listed "
            "account can claim a fresh workspace. Empty means nobody can claim it from the web, "
            "and an admin invite made with cso auth create-invite --role admin is the way in."
        ),
    )
    web_base_url: str = Field(
        default="",
        description=(
            "Where the browser goes after sign-in. Empty keeps it on the API's own origin (the "
            "hosted layout, where one proxy serves both). Set it when the web app runs on another "
            "port, for example http://127.0.0.1:5173. No trailing slash."
        ),
    )

    @property
    def osm_signin_uids(self) -> frozenset[int]:
        """The OSM user ids allowed to sign in; empty means every account is allowed."""
        parts = [p.strip() for p in self.osm_signin_allowed_uids.split(",")]
        return frozenset(int(p) for p in parts if p.isdigit())

    @property
    def bootstrap_admin_uids(self) -> frozenset[int]:
        """The OSM user ids allowed to claim an unclaimed workspace; empty means none."""
        parts = [p.strip() for p in self.bootstrap_admin_osm_uids.split(",")]
        return frozenset(int(p) for p in parts if p.isdigit())

    @property
    def osm_oauth_enabled(self) -> bool:
        """True when the client id, secret and redirect URL are all set."""
        return bool(
            self.osm_oauth_client_id
            and self.osm_oauth_client_secret is not None
            and self.osm_oauth_client_secret.get_secret_value()
            and self.osm_oauth_redirect_url
        )

    @property
    def user_agent_is_placeholder(self) -> bool:
        """True while the User-Agent still carries a placeholder instead of a real contact."""
        return any(token in self.user_agent for token in USER_AGENT_PLACEHOLDERS)

    def require_real_user_agent(self) -> None:
        """Raise SettingsError unless `CSO_USER_AGENT` names a real repository and contact.

        OpenStreetMap's usage policy asks clients to identify themselves; network commands call
        this before sending a request, and live mode calls it at startup.
        """
        if self.user_agent_is_placeholder:
            raise SettingsError(
                "CSO_USER_AGENT still contains a placeholder; set it in .env to "
                '"ChangesetSecondOpinion/0.1 (+<repository URL>; <contact email>)" with real values'
            )

    @model_validator(mode="after")
    def _live_mode_needs_real_user_agent(self) -> "Settings":
        if self.mode == "live":
            self.require_real_user_agent()
        return self

    @model_validator(mode="after")
    def _oauth_redirect_is_https_or_loopback(self) -> "Settings":
        url = self.osm_oauth_redirect_url
        if url:
            loopback = ("http://127.0.0.1", "http://localhost", "http://[::1]")
            if not (url.startswith("https://") or url.startswith(loopback)):
                raise SettingsError(
                    "CSO_OSM_OAUTH_REDIRECT_URL must be https, or http on a loopback address"
                )
        return self

    @model_validator(mode="after")
    def _signin_lists_are_well_formed(self) -> "Settings":
        # A typo in the allow-list must not silently open sign-in to everyone.
        raw = [p.strip() for p in self.osm_signin_allowed_uids.split(",") if p.strip()]
        if any(not p.isdigit() for p in raw):
            raise SettingsError("CSO_OSM_SIGNIN_ALLOWED_UIDS must be comma-separated numbers")
        boot = [p.strip() for p in self.bootstrap_admin_osm_uids.split(",") if p.strip()]
        if any(not p.isdigit() for p in boot):
            raise SettingsError("CSO_BOOTSTRAP_ADMIN_OSM_UIDS must be comma-separated numbers")
        base = self.web_base_url
        if base and (not base.startswith(("http://", "https://")) or base.endswith("/")):
            raise SettingsError("CSO_WEB_BASE_URL must be an http(s) origin without a trailing /")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def resolved_log_format(settings: Settings) -> Literal["json", "console"]:
    """`json` in live mode (or when asked for), `console` otherwise."""
    if settings.log_format == "auto":
        return "json" if settings.mode == "live" else "console"
    return settings.log_format
