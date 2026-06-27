"""
Route Planner Agent — multi-modal pathfinding across HK public transport.

Finds routes using any combination of MTR, buses (KMB/Citybus/LWB/NLB),
green minibuses, and ferries. Queries MCP servers for real-time data.

Implements the tool-use pattern from Day 2:
- MCP tools for transit data (standardized O(N+M) integration)
- Falls back to static route data when MCP servers are unavailable
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from .config import AgentConfig, ROUTE_PLANNER_PROMPT, config

logger = logging.getLogger(__name__)


@dataclass
class RouteSegment:
    """A single segment of a multi-modal journey."""
    mode: str  # "MTR", "KMB", "CTB", "GMB", "FERRY", "WALK"
    from_stop: str
    to_stop: str
    route_code: str  # e.g., "EAL" for East Rail Line, "74X" for KMB route
    duration_min: int
    is_accessible: bool = True
    instructions: str = ""  # e.g., "Board at Exit A, lift available"

    # Real-time data (populated from MCP)
    next_arrival_min: Optional[int] = None
    occupancy: Optional[str] = None  # "low", "medium", "high"


@dataclass
class RouteOption:
    """A complete route from origin to destination."""
    segments: list[RouteSegment] = field(default_factory=list)
    total_time_min: int = 0
    interchange_count: int = 0
    total_cost_hkd: float = 0.0

    @property
    def summary(self) -> str:
        """One-line route summary."""
        modes = " → ".join(s.mode for s in self.segments)
        return f"{modes} ({self.total_time_min} min)"

    @property
    def is_fully_accessible(self) -> bool:
        """Check if every segment is accessible."""
        return all(s.is_accessible for s in self.segments)


class RoutePlannerAgent:
    """Finds multi-modal routes across Hong Kong's public transport network.

    Queries MCP servers for real-time transit data. Falls back to a static
    knowledge base of common HK routes when MCP servers are offline.
    """

    # Static knowledge base of common HK accessible routes.
    # In production, this is replaced entirely by MCP queries.
    # This fallback ensures the agent degrades gracefully (Day 5 zero-trust).
    _STATIC_ROUTES: dict[tuple[str, str], list[RouteOption]] = {
        # HK Island ↔ Kowloon
        ("central", "tsim sha tsui"): [
            RouteOption(
                segments=[
                    RouteSegment(
                        mode="MTR", from_stop="Central (ISL/TWL)",
                        to_stop="Tsim Sha Tsui (TWL)", route_code="TWL",
                        duration_min=5, is_accessible=True,
                        instructions="Lift at Central Exit A, lift at TST Exit B1",
                    )
                ],
                total_time_min=5, interchange_count=0, total_cost_hkd=10.3,
            ),
            RouteOption(
                segments=[
                    RouteSegment(
                        mode="FERRY", from_stop="Central Pier 7",
                        to_stop="Tsim Sha Tsui Star Ferry Pier", route_code="STAR",
                        duration_min=9, is_accessible=True,
                        instructions="Wheelchair accessible at both piers",
                    )
                ],
                total_time_min=9, interchange_count=0, total_cost_hkd=4.0,
            ),
        ],
        # New Territories ↔ Kowloon
        ("tai po market", "mong kok"): [
            RouteOption(
                segments=[
                    RouteSegment(
                        mode="MTR", from_stop="Tai Po Market (EAL)",
                        to_stop="Mong Kok East (EAL)", route_code="EAL",
                        duration_min=22, is_accessible=True,
                        instructions="Lift at Tai Po Market Exit A",
                    )
                ],
                total_time_min=22, interchange_count=0, total_cost_hkd=12.5,
            ),
        ],
        ("sha tin", "admiralty"): [
            RouteOption(
                segments=[
                    RouteSegment(
                        mode="MTR", from_stop="Sha Tin (EAL)",
                        to_stop="Admiralty (EAL/TWL/ISL/SIL)", route_code="EAL",
                        duration_min=18, is_accessible=True,
                        instructions="Lift available at Sha Tin Exit B and Admiralty Exit E",
                    )
                ],
                total_time_min=18, interchange_count=0, total_cost_hkd=15.2,
            ),
        ],
        # Cross-harbour (Kowloon → HK Island)
        ("mong kok", "causeway bay"): [
            RouteOption(
                segments=[
                    RouteSegment(
                        mode="MTR", from_stop="Mong Kok (TWL)",
                        to_stop="Admiralty (TWL/ISL)", route_code="TWL",
                        duration_min=10, is_accessible=True,
                        instructions="Lift at Mong Kok Exit A",
                    ),
                    RouteSegment(
                        mode="MTR", from_stop="Admiralty (ISL)",
                        to_stop="Causeway Bay (ISL)", route_code="ISL",
                        duration_min=4, is_accessible=True,
                        instructions="Lift at Causeway Bay Exit F (Times Square)",
                    ),
                ],
                total_time_min=17, interchange_count=1, total_cost_hkd=12.5,
            ),
        ],
        # New Territories West
        ("tuen mun", "tsuen wan"): [
            RouteOption(
                segments=[
                    RouteSegment(
                        mode="MTR", from_stop="Tuen Mun (TML)",
                        to_stop="Tsuen Wan West (TML)", route_code="TML",
                        duration_min=15, is_accessible=True,
                        instructions="Lift at both stations",
                    )
                ],
                total_time_min=15, interchange_count=0, total_cost_hkd=10.8,
            ),
        ],
    }

    # Known MTR station accessibility data (static fallback).
    # In production, queried via mtr-accessibility-mcp server.
    _MTR_LIFT_LOCATIONS: dict[str, list[str]] = {
        "central": ["Exit A (lift to Connaught Rd)", "Exit J (lift to Chater Garden)"],
        "admiralty": ["Exit E (lift to Queensway)", "Exit F (lift to Tamar Park)"],
        "tsim sha tsui": ["Exit B1 (lift to Nathan Rd)", "Exit E (lift to Peking Rd)"],
        "tai po market": ["Exit A (lift to Nga Wan Rd)", "Exit B (lift to bus terminus)"],
        "sha tin": ["Exit B (lift to bus terminus)", "Exit A1 (lift to New Town Plaza)"],
        "mong kok": ["Exit A (lift to Argyle St)", "Exit E1 (lift to Nathan Rd)"],
        "causeway bay": ["Exit F (lift to Times Square)"],
        "tuen mun": ["Exit B (lift to Tuen Mun Town Plaza)"],
        "tsuen wan west": ["Exit A (lift to Tsuen Wan Plaza)"],
        "kennedy town": ["Exit B (lift to Belcher's St)"],
        "diamond hill": ["Exit A1 (lift to Plaza Hollywood)", "Exit C (lift to bus terminus)"],
        "kwun tong": ["Exit A (lift to APM mall)"],
        "yuen long": ["Exit B (lift to Castle Peak Rd)"],
        "tseung kwan o": ["Exit A (lift to Popcorn mall)"],
        "airport": ["Arrivals Hall (lift to Terminal 2)"],
    }

    def __init__(self, cfg: AgentConfig = config):
        self.config = cfg
        self._mcp_connected = False

    # ------------------------------------------------------------------
    # Main API: find routes for an origin-destination pair.
    # ------------------------------------------------------------------

    async def find_routes(
        self,
        origin: str,
        destination: str,
        max_options: int = 3,
    ) -> list[RouteOption]:
        """Find accessible routes from origin to destination.

        First attempts to query MCP servers for real-time data.
        Falls back to the static knowledge base if MCP is unavailable.
        """
        origin_key = origin.lower().strip()
        dest_key = destination.lower().strip()
        query_key = (origin_key, dest_key)

        # Try MCP servers first (the "goto" path for production)
        if self._mcp_connected:
            routes = await self._query_mcp_routes(origin_key, dest_key)
            if routes:
                return routes[:max_options]

        # Fallback: static knowledge base
        routes = self._query_static_routes(query_key)
        if routes:
            logger.info(f"Static routes found for {origin_key} → {dest_key}")
            return routes[:max_options]

        # Last resort: generate a best-guess route using MTR only
        logger.warning(f"No routes found for {origin_key} → {dest_key}, using MTR fallback")
        return [self._generate_mtr_only_route(origin, destination)]

    # ------------------------------------------------------------------
    # MCP queries (Day 2: standardized tool integration)
    # ------------------------------------------------------------------

    async def _query_mcp_routes(
        self, origin: str, destination: str
    ) -> list[RouteOption]:
        """Query MCP servers for real-time transit routes.

        In production, this calls:
        1. mcp_hkbus for KMB/Citybus routes and ETAs
        2. hk-transit-mcp for MTR schedules
        3. Combines results into multi-modal routes

        For the prototype, this demonstrates the MCP call pattern.
        """
        # TODO: Integrate with actual MCP servers via the official MCP Python SDK.
        # Pattern:
        #   from mcp import ClientSession
        #   async with stdio_client(server_params) as (read, write):
        #       async with ClientSession(read, write) as session:
        #           tools = await session.list_tools()
        #           result = await session.call_tool("search_routes", {
        #               "origin": origin,
        #               "destination": destination,
        #           })
        logger.info(f"MCP route query: {origin} → {destination}")
        return []  # Returns empty → triggers static fallback

    # ------------------------------------------------------------------
    # Static route knowledge base (fallback when MCP is offline)
    # ------------------------------------------------------------------

    def _query_static_routes(
        self, query_key: tuple[str, str]
    ) -> list[RouteOption]:
        """Query the static route knowledge base.

        Does fuzzy matching on place names to handle variations.
        """
        # Exact match
        if query_key in self._STATIC_ROUTES:
            return self._STATIC_ROUTES[query_key]

        # Fuzzy match: check if either key contains the other
        for (known_origin, known_dest), routes in self._STATIC_ROUTES.items():
            if (known_origin in query_key[0] or query_key[0] in known_origin) and \
               (known_dest in query_key[1] or query_key[1] in known_dest):
                return routes

        return []

    def _generate_mtr_only_route(
        self, origin: str, destination: str
    ) -> RouteOption:
        """Generate a best-guess MTR-only route.

        When no specific route data is available, we provide an MTR-based
        suggestion with clear caveats. This avoids the "no route found" dead
        end that frustrates users (Day 4: graceful degradation).
        """
        return RouteOption(
            segments=[
                RouteSegment(
                    mode="MTR",
                    from_stop=f"{origin} (nearest MTR)",
                    to_stop=f"{destination} (nearest MTR)",
                    route_code="MTR",
                    duration_min=30,
                    is_accessible=False,  # Unknown — be conservative
                    instructions=(
                        f"⚠️ I don't have detailed accessibility data for this route. "
                        f"Please check MTR's step-free access guide at "
                        f"mtr.com.hk for lift locations at {origin} and {destination}."
                    ),
                )
            ],
            total_time_min=30,
            interchange_count=0,
            total_cost_hkd=15.0,
        )

    # ------------------------------------------------------------------
    # Utility: find MTR lift locations (static fallback)
    # ------------------------------------------------------------------

    def get_lift_locations(self, station_name: str) -> list[str]:
        """Return known lift-equipped exits for an MTR station."""
        key = station_name.lower().strip()
        return self._MTR_LIFT_LOCATIONS.get(key, [])

    def has_lift(self, station_name: str) -> bool:
        """Check if an MTR station has at least one lift-equipped exit."""
        return len(self.get_lift_locations(station_name)) > 0
