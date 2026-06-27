"""
Route Planner Agent — multi-modal pathfinding across HK public transport.

Finds routes using any combination of MTR, buses (KMB/Citybus/LWB/NLB),
green minibuses, and ferries. Queries MCP servers for real-time data.

Implements the tool-use pattern from Day 2:
- MCP tools for transit data (standardized O(N+M) integration)
- Falls back to static route data when MCP servers are unavailable
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from .config import AgentConfig, ROUTE_PLANNER_PROMPT, config
from .transit_api import TransitAPIClient
from .mcp_connector import MCPConnectionPool
from .mcp_tools import register_in_process_tools

# Register MCP tools at import time so all agent instances benefit
register_in_process_tools()

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

    def __init__(
        self,
        cfg: AgentConfig = config,
        api: Optional[TransitAPIClient] = None,
        mcp_pool: Optional[MCPConnectionPool] = None,
    ):
        self.config = cfg
        self.api = api or TransitAPIClient()
        self.mcp = mcp_pool or MCPConnectionPool()
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

        Tries three layers in order:
        1. Real-time MTR API + MCP tools (live data)
        2. Static knowledge base (known HK routes)
        3. MTR-only fallback (best guess with caveats)
        """
        origin_key = origin.lower().strip()
        dest_key = destination.lower().strip()

        # Layer 1: Try real APIs
        routes = await self._query_live_data(origin_key, dest_key)
        if routes:
            logger.info(f"Live data routes for {origin_key} → {dest_key}: {len(routes)}")
            return routes[:max_options]

        # Layer 2: Static knowledge base
        query_key = (origin_key, dest_key)
        routes = self._query_static_routes(query_key)
        if routes:
            logger.info(f"Static routes found for {origin_key} → {dest_key}")
            return routes[:max_options]

        # Layer 3: MTR-only fallback
        logger.warning(f"No routes found for {origin_key} → {dest_key}, using MTR fallback")
        return [self._generate_mtr_only_route(origin, destination)]

    async def _query_live_data(
        self, origin: str, destination: str
    ) -> list[RouteOption]:
        """Query real transit APIs + MCP tools for live route data.

        Step 1: Search MTR stations via MCP (mtr-accessibility)
        Step 2: Get MTR schedule via HK gov API
        Step 3: Check bus routes via MCP (hk-transit)
        """
        routes: list[RouteOption] = []

        try:
            # Step 1: Find MTR stations matching origin/destination
            origin_stns = await self._find_mtr_station(origin)
            dest_stns = await self._find_mtr_station(destination)

            if origin_stns and dest_stns:
                origin_stn = origin_stns[0]
                dest_stn = dest_stns[0]
                origin_code = origin_stn["code"]
                dest_code = dest_stn["code"]

                # Step 2: Try direct MTR connection
                # Check if they're on the same line
                common_lines = set(origin_stn.get("lines", [])) & set(dest_stn.get("lines", []))
                if common_lines:
                    line = list(common_lines)[0]
                    # Map line name → API code
                    line_map = {v: k for k, v in self.api.MTR_LINES.items()}
                    line_code = line_map.get(line, "")

                    if line_code:
                        # Get real-time schedule
                        schedule = await self.api.get_mtr_schedule(line_code, origin_code)
                        arrival_min = schedule.arrivals_up[0] if schedule.arrivals_up else 5

                        # Build route
                        segment = RouteSegment(
                            mode="MTR",
                            from_stop=f"{origin_stn['name_en']} ({origin_code})",
                            to_stop=f"{dest_stn['name_en']} ({dest_code})",
                            route_code=line_code,
                            duration_min=arrival_min + self._estimate_mtr_time(origin_code, dest_code, line_code),
                            is_accessible=origin_stn.get("step_free", False) and dest_stn.get("step_free", False),
                            instructions=(
                                "Live MTR data. "
                                f"Next train: {arrival_min} min. "
                                f"Lift: {'Yes' if origin_stn.get('step_free') else 'Check mtr.com.hk'}"
                            ),
                            next_arrival_min=arrival_min,
                        )

                        route = RouteOption(
                            segments=[segment],
                            total_time_min=segment.duration_min,
                            interchange_count=0,
                        )
                        routes.append(route)

            # Step 3: Also check bus options via MCP
            try:
                bus_result = await self.mcp.call_tool(
                    "hk-transit",
                    "search_accessible_bus_routes",
                    {"area_from": origin, "area_to": destination},
                )
                bus_data = json.loads(bus_result) if isinstance(bus_result, str) else bus_result
                for bus_route in bus_data.get("routes", [])[:1]:
                    if bus_route.get("wheelchair_accessible"):
                        routes.append(RouteOption(
                            segments=[RouteSegment(
                                mode="CTB" if "ctb" in str(bus_route).lower() else "KMB",
                                from_stop=bus_route.get("origin", origin),
                                to_stop=bus_route.get("dest", destination),
                                route_code=bus_route.get("route", ""),
                                duration_min=25,
                                is_accessible=True,
                                instructions=f"Bus route {bus_route.get('route')} — low-floor vehicles",
                            )],
                            total_time_min=25,
                            interchange_count=0,
                        ))
            except Exception as e:
                logger.debug(f"Bus MCP query skipped: {e}")

        except Exception as e:
            logger.warning(f"Live data query failed: {e} — will use static fallback")

        return routes

    # ------------------------------------------------------------------
    # Live data helpers
    # ------------------------------------------------------------------

    async def _find_mtr_station(self, place_name: str) -> list[dict]:
        """Find MTR stations matching a place name using MCP tools.

        Tries multiple approaches:
        1. MCP tool 'search_station_by_name'
        2. Direct match against known station list
        3. MCP tool 'search_step_free_station'
        """
        matches = []

        # Try MCP tool
        try:
            result = await self.mcp.call_tool(
                "mtr-accessibility",
                "search_station_by_name",
                {"query": place_name},
            )
            data = json.loads(result) if isinstance(result, str) else result
            matches = data.get("matches", [])
            if matches:
                return matches
        except Exception:
            pass

        # Try hk-transit MCP
        try:
            result = await self.mcp.call_tool(
                "hk-transit",
                "search_station_by_name",
                {"query": place_name},
            )
            data = json.loads(result) if isinstance(result, str) else result
            matches = data.get("matches", [])
            if matches:
                return matches
        except Exception:
            pass

        # Fallback: match against static station data
        # Maps common place names → 3-letter station codes + metadata
        STATIC_STATIONS = {
            "tai po market": ("TAP", "Tai Po Market", "大埔墟", ["East Rail Line"], self.get_lift_locations("tai po market")),
            "tai po": ("TAP", "Tai Po Market", "大埔墟", ["East Rail Line"], self.get_lift_locations("tai po market")),
            "sha tin": ("SHT", "Sha Tin", "沙田", ["East Rail Line"], self.get_lift_locations("sha tin")),
            "central": ("CEN", "Central", "中環", ["Tsuen Wan Line", "Island Line"], self.get_lift_locations("central")),
            "admiralty": ("ADM", "Admiralty", "金鐘", ["East Rail Line", "Tsuen Wan Line", "Island Line", "South Island Line"], self.get_lift_locations("admiralty")),
            "tsim sha tsui": ("TST", "Tsim Sha Tsui", "尖沙咀", ["Tsuen Wan Line"], self.get_lift_locations("tsim sha tsui")),
            "mong kok": ("MOK", "Mong Kok", "旺角", ["Tsuen Wan Line", "Kwun Tong Line"], self.get_lift_locations("mong kok")),
            "mong kok east": ("MKK", "Mong Kok East", "旺角東", ["East Rail Line"], self.get_lift_locations("mong kok")),
            "causeway bay": ("CAB", "Causeway Bay", "銅鑼灣", ["Island Line"], self.get_lift_locations("causeway bay")),
            "tuen mun": ("TUM", "Tuen Mun", "屯門", ["Tuen Ma Line"], self.get_lift_locations("tuen mun")),
            "yuen long": ("YUL", "Yuen Long", "元朗", ["Tuen Ma Line"], self.get_lift_locations("yuen long")),
            "diamond hill": ("DIH", "Diamond Hill", "鑽石山", ["Kwun Tong Line", "Tuen Ma Line"], self.get_lift_locations("diamond hill")),
            "kwun tong": ("KWT", "Kwun Tong", "觀塘", ["Kwun Tong Line"], self.get_lift_locations("kwun tong")),
            "kennedy town": ("KET", "Kennedy Town", "堅尼地城", ["Island Line"], self.get_lift_locations("kennedy town")),
            "tsuen wan": ("TSW", "Tsuen Wan", "荃灣", ["Tsuen Wan Line"], self.get_lift_locations("tsuen wan")),
        }

        for key, (code, name_en, name_zh, lines, lifts) in STATIC_STATIONS.items():
            if key in place_name or place_name in key:
                matches.append({
                    "code": code,
                    "name_en": name_en,
                    "name_zh": name_zh,
                    "step_free": len(lifts) > 0,
                    "lift_exits": lifts,
                    "lines": lines,
                })

        return matches

    def _estimate_mtr_time(
        self, from_code: str, to_code: str, line_code: str
    ) -> int:
        """Estimate MTR travel time between two stations on the same line.

        Approximation: ~2-3 min per station on the same line.
        """
        # Simple distance-based heuristic based on known station pairs
        # Format: (from, to) → estimated minutes
        known_times = {
            ("tap", "adn"): 22, ("tap", "mkk"): 22, ("tap", "sht"): 6,
            ("sht", "adn"): 18, ("sht", "mkk"): 12,
            ("cen", "adn"): 3, ("cen", "tst"): 5, ("cen", "cab"): 8,
            ("tst", "adn"): 3, ("tst", "cen"): 5,
            ("mok", "adn"): 10, ("mok", "tst"): 7, ("mok", "cab"): 17,
            ("tum", "tsw"): 15, ("tum", "yul"): 10,
            ("dih", "kwt"): 7, ("dih", "mok"): 8,
        }
        key = (from_code.lower(), to_code.lower())
        if key in known_times:
            return known_times[key]
        rev_key = (to_code.lower(), from_code.lower())
        if rev_key in known_times:
            return known_times[rev_key]
        return 15  # Default estimate

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
