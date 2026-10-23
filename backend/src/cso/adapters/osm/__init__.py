"""Read-only OpenStreetMap evidence access: live client, replay client, parser, flags."""

from cso.adapters.osm.client import OSM_API_BASE, OsmClient, SafeGetClient
from cso.adapters.osm.collect import CollectBudget, PriorVersionCache, collect
from cso.adapters.osm.errors import (
    BandwidthLimitError,
    ElementCapExceededError,
    NotAllowedError,
    NotFoundError,
    OsmError,
    OsmTimeoutError,
    ParseError,
    RateLimitedError,
    Redacted403,
    TooLargeError,
    UpstreamError,
    XmlSafetyError,
)
from cso.adapters.osm.flags import FlagsUnavailableError, compute_flags
from cso.adapters.osm.maproulette import MapRouletteClient, RouletteTask
from cso.adapters.osm.parse import (
    GroupedElement,
    OscElement,
    OscMember,
    ParsedOsmChange,
    parse_osm_change,
)
from cso.adapters.osm.protocol import MAX_MULTIFETCH_IDS, OsmSource
from cso.adapters.osm.replay import ReplayClient

__all__ = [
    "MAX_MULTIFETCH_IDS",
    "OSM_API_BASE",
    "BandwidthLimitError",
    "CollectBudget",
    "ElementCapExceededError",
    "FlagsUnavailableError",
    "GroupedElement",
    "MapRouletteClient",
    "NotAllowedError",
    "NotFoundError",
    "OscElement",
    "OscMember",
    "OsmClient",
    "OsmError",
    "OsmSource",
    "OsmTimeoutError",
    "ParseError",
    "ParsedOsmChange",
    "PriorVersionCache",
    "RateLimitedError",
    "Redacted403",
    "ReplayClient",
    "RouletteTask",
    "SafeGetClient",
    "TooLargeError",
    "UpstreamError",
    "XmlSafetyError",
    "collect",
    "compute_flags",
    "parse_osm_change",
]
