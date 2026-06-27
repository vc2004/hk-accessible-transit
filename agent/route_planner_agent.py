"""
Route Planner Agent — a TRUE agent with LLM reasoning + tool calling.

Finds accessible routes by:
1. Thinking about what tools to call
2. Searching MTR stations (MCP tool)
3. Getting real-time schedules (MTR API)
4. Building multi-modal route options
5. Returning structured results

This is NOT a simple function — it uses the BaseAgent loop:
  Think → Act (call tool) → Observe → Think → ... → Final Answer
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from .base_agent import BaseAgent
from .llm_client import LLMClient
from .transit_api import TransitAPIClient

logger = logging.getLogger(__name__)


@dataclass
class RouteSegment:
    mode: str
    from_stop: str
    to_stop: str
    route_code: str
    duration_min: int
    is_accessible: bool = True
    instructions: str = ""
    next_arrival_min: Optional[int] = None


@dataclass
class RouteOption:
    segments: list[RouteSegment] = field(default_factory=list)
    total_time_min: int = 0
    interchange_count: int = 0

    @property
    def summary(self) -> str:
        modes = " → ".join(s.mode for s in self.segments)
        return f"{modes} ({self.total_time_min} min)"


class RoutePlannerAgent(BaseAgent):
    """Finds accessible MTR/bus routes with LLM reasoning + tool calls.

    Tools available to this agent:
    - search_mtr_station: find MTR stations by name
    - get_mtr_schedule: real-time train arrivals
    - check_station_accessibility: lift/exit info
    - search_bus_routes: accessible bus options
    - check_mode_accessibility: can this transport mode be used?
    """

    def __init__(self, llm: LLMClient, transit_api: TransitAPIClient, weather_api=None):
        super().__init__(name="RoutePlanner", llm=llm, tier="light")
        self.api = transit_api
        from .weather_api import WeatherAPIClient
        self.weather = weather_api or WeatherAPIClient()

    @property
    def system_prompt(self) -> str:
        return f"""You are a Route Planner agent for Hong Kong public transport.
Your job: find accessible routes between two locations.

You have tools to search MTR stations, get real-time schedules, check
accessibility, and find bus routes. Think step by step:

1. First, search for MTR stations near the origin and destination
2. Check if they're on the same line (direct route) or need interchange
3. Get real-time train schedules
4. Check accessibility at both stations
5. Also check bus options as alternatives

IMPORTANT:
- Always search both the English AND Chinese names of places
- When you have enough info, provide your final answer with route options
- Format each route as: mode, stations, estimated time, accessibility notes
- If a station lacks lift access, say so clearly
- Minibuses and trams are NOT wheelchair accessible in Hong Kong

Current MTR lines: EAL (East Rail), TWL (Tsuen Wan), ISL (Island),
KTL (Kwun Tong), TML (Tuen Ma), TCL (Tung Chung), TKL (Tseung Kwan O),
SIL (South Island), AEL (Airport Express), DRL (Disneyland Resort)."""

    def get_tools(self) -> list[dict]:
        """OpenAI-style function definitions."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_mtr_station",
                    "description": "Search for an MTR station by English or Chinese name. Returns station code, name, lines, and step-free access info.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Station name (English or Chinese, e.g. 'Sha Tin' or '沙田')"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_mtr_schedule",
                    "description": "Get real-time train arrival times for an MTR line at a specific station. Returns minutes until next trains.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "line": {"type": "string", "description": "MTR line code (EAL, TWL, ISL, KTL, TML, TCL, TKL, SIL, AEL, DRL)"},
                            "station": {"type": "string", "description": "3-letter station code (e.g. SHT, ADM, CEN)"},
                        },
                        "required": ["line", "station"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "check_station_accessibility",
                    "description": "Get detailed accessibility info for an MTR station: lifts, wide gates, accessible toilets, tactile paths.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "station_code": {"type": "string", "description": "3-letter station code"},
                        },
                        "required": ["station_code"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_bus_routes",
                    "description": "Search for wheelchair-accessible bus routes between two areas in Hong Kong.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "from_area": {"type": "string"},
                            "to_area": {"type": "string"},
                        },
                        "required": ["from_area", "to_area"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_bus_eta",
                    "description": "Get real-time KMB bus arrival times at a stop. Returns minutes until next buses and wheelchair accessibility status.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "route": {"type": "string", "description": "Bus route number (e.g. '74X', '271')"},
                            "stop_id": {"type": "string", "description": "KMB stop ID (16-char hex). Use 'search_bus_routes' first to find routes, then look up stops."},
                        },
                        "required": ["route", "stop_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_weather_warnings",
                    "description": "Get active Hong Kong weather warnings that may affect travel (typhoon, rainstorm, thunderstorm, heat). Returns alerts relevant for accessibility.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "check_mode_accessibility",
                    "description": "Check whether a transport mode is wheelchair accessible.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mode": {"type": "string", "enum": ["MTR", "KMB", "CTB", "GMB", "FERRY", "TRAM", "NLB"]},
                        },
                        "required": ["mode"],
                    },
                },
            },
        ]

    async def handle_tool(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool call and return the result."""
        if tool_name == "search_mtr_station":
            return await self._search_station(arguments["query"])

        elif tool_name == "get_mtr_schedule":
            sched = await self.api.get_mtr_schedule(
                arguments["line"], arguments["station"]
            )
            return json.dumps({
                "line": sched.line,
                "station": sched.station,
                "arrivals_up_min": sched.arrivals_up,
                "arrivals_down_min": sched.arrivals_down,
                "is_delayed": sched.is_delayed,
            }, ensure_ascii=False)

        elif tool_name == "check_station_accessibility":
            return await self._check_accessibility(arguments["station_code"])

        elif tool_name == "search_bus_routes":
            return await self._search_buses(
                arguments.get("from_area", ""),
                arguments.get("to_area", ""),
            )

        elif tool_name == "get_bus_eta":
            eta = await self.api.get_kmb_eta(
                arguments.get("stop_id", ""),
                arguments.get("route", ""),
            )
            return json.dumps({
                "route": eta.route,
                "destination": eta.destination,
                "arrivals_min": eta.arrivals,
                "wheelchair_accessible": eta.wheelchair_accessible,
            }, ensure_ascii=False)

        elif tool_name == "get_weather_warnings":
            weather = await self.weather.get_current_weather()
            warnings = await self.weather.get_warnings()
            alerts = self.weather.get_accessibility_alerts(weather, warnings)
            summary = await self.weather.get_warning_summary()
            return json.dumps({
                "temperature": weather.temperature,
                "rainfall_mm": weather.rainfall,
                "humidity": weather.humidity,
                "active_warnings": summary if summary else "No active weather warnings",
                "accessibility_alerts": alerts,
            }, ensure_ascii=False)

        elif tool_name == "check_mode_accessibility":
            return await self._check_mode(arguments["mode"])

        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _search_station(self, query: str) -> str:
        """Search MTR stations by name."""
        from .route_planner import RoutePlannerAgent as RP

        rp = RP()
        stns = await rp._find_mtr_station(query)

        if not stns:
            return json.dumps({"matches": [], "hint": "Try the full English or Chinese station name."})

        return json.dumps({"matches": stns}, ensure_ascii=False, indent=2)

    async def _check_accessibility(self, code: str) -> str:
        """Get accessibility info from MCP tools."""
        from .mcp_tools import mtr_accessibility_call_tool
        return mtr_accessibility_call_tool("get_station_accessibility", {"station_code": code})

    async def _search_buses(self, from_area: str, to_area: str) -> str:
        """Search accessible bus routes."""
        from .mcp_tools import hk_transit_call_tool
        return hk_transit_call_tool("search_accessible_bus_routes", {
            "area_from": from_area, "area_to": to_area,
        })

    async def _check_mode(self, mode: str) -> str:
        """Check transport mode accessibility."""
        from .mcp_tools import hk_transit_call_tool
        return hk_transit_call_tool("check_transit_mode_accessibility", {"mode": mode})

    # ------------------------------------------------------------------
    # High-level API: plan a route (single agent.run call)
    # ------------------------------------------------------------------

    async def plan_route(self, origin: str, destination: str) -> str:
        """Plan a route from origin to destination. Returns LLM's final answer."""
        prompt = (
            f"Find accessible public transport routes from '{origin}' to '{destination}' "
            f"in Hong Kong.\n\n"
            f"Steps:\n"
            f"1. Search for MTR stations near '{origin}' and '{destination}'\n"
            f"2. Get real-time train schedules\n"
            f"3. Check accessibility at both stations\n"
            f"4. Also check if there are accessible bus routes\n"
            f"5. Provide the best route option(s) with accessibility notes\n\n"
            f"Call tools as needed. Provide your final answer when you have all the information."
        )
        return await self.run(prompt)
