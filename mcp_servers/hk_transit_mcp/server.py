"""
MCP Server: hk-transit-mcp

A Model Context Protocol server that provides unified access to Hong Kong
public transport data. Wraps multiple HK government open data APIs behind
a single MCP interface.

Data sources:
- MTR lines, stations, schedules (rt.data.gov.hk + opendata.mtr.com.hk)
- Citybus/NWFB routes and ETAs (rt.data.gov.hk/v2/transport/citybus)
- Green minibus routes (data.etagmb.gov.hk)
- NLB (New Lantao Bus) routes (rt.data.gov.hk/v2/transport/nlb)

Implements the MCP consumer pattern from Day 2 Section 2.2:
    Discovery → Configuration → Connection

Usage:
    # As a local stdio MCP server (for Claude Code, Cursor, etc.)
    python -m mcp_servers.hk_transit_mcp.server

    # Or register in your MCP client config:
    {
        "mcpServers": {
            "hk-transit": {
                "command": "python",
                "args": ["-m", "mcp_servers.hk_transit_mcp.server"]
            }
        }
    }
"""

import json
import logging
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Static transit data — in production, this would be a database populated
# from the HK government open data APIs.
# ---------------------------------------------------------------------------

# MTR lines with station codes
MTR_LINES = {
    "EAL": {
        "name_en": "East Rail Line",
        "name_zh": "東鐵綫",
        "stations": ["ADM", "EXC", "HUH", "MKK", "KOT", "TAW", "SHT", "FOT",
                      "RAC", "UNI", "TAP", "TWO", "FAN", "SHS", "LOW", "LMC"],
        "color": "#53B7E8",
    },
    "TWL": {
        "name_en": "Tsuen Wan Line",
        "name_zh": "荃灣綫",
        "stations": ["CEN", "ADM", "TST", "JOR", "YMT", "MOK", "PRE", "SSP",
                      "CSW", "LCK", "MEA", "LAK", "KWF", "KWH", "TWW", "TSW"],
        "color": "#EF3E3E",
    },
    "ISL": {
        "name_en": "Island Line",
        "name_zh": "港島綫",
        "stations": ["KET", "HKU", "SYP", "SHW", "CEN", "ADM", "WAC", "CAB",
                      "TIH", "FOH", "NOP", "QUB", "TAK"],
        "color": "#007DC5",
    },
    "TML": {
        "name_en": "Tuen Ma Line",
        "name_zh": "屯馬綫",
        "stations": ["TUM", "SIH", "TIS", "LOP", "YUL", "KSR", "MEF", "TWW",
                      "TSW", "HUH", "ETS", "HOM", "DIH", "KTA", "SUW", "TKW"],
        "color": "#923011",
    },
    "KTL": {
        "name_en": "Kwun Tong Line",
        "name_zh": "觀塘綫",
        "stations": ["WHA", "HOM", "YMT", "MOK", "PRE", "SKM", "LOF", "KOT",
                      "DIH", "CHH", "KOB", "NTK", "KWT", "LAT", "YAT", "TIK"],
        "color": "#00AB4E",
    },
}

# Station code → English name + Chinese name
MTR_STATIONS: dict[str, dict] = {
    "ADM": {"name_en": "Admiralty", "name_zh": "金鐘"},
    "CEN": {"name_en": "Central", "name_zh": "中環"},
    "TST": {"name_en": "Tsim Sha Tsui", "name_zh": "尖沙咀"},
    "MOK": {"name_en": "Mong Kok", "name_zh": "旺角"},
    "TAP": {"name_en": "Tai Po Market", "name_zh": "大埔墟"},
    "SHT": {"name_en": "Sha Tin", "name_zh": "沙田"},
    "TUM": {"name_en": "Tuen Mun", "name_zh": "屯門"},
    "TSW": {"name_en": "Tsuen Wan", "name_zh": "荃灣"},
    "YUL": {"name_en": "Yuen Long", "name_zh": "元朗"},
    "CAB": {"name_en": "Causeway Bay", "name_zh": "銅鑼灣"},
    "DIH": {"name_en": "Diamond Hill", "name_zh": "鑽石山"},
    "KWT": {"name_en": "Kwun Tong", "name_zh": "觀塘"},
    "HUH": {"name_en": "Hung Hom", "name_zh": "紅磡"},
    "KOT": {"name_en": "Kowloon Tong", "name_zh": "九龍塘"},
    "EXC": {"name_en": "Exhibition Centre", "name_zh": "會展"},
    "WAC": {"name_en": "Wan Chai", "name_zh": "灣仔"},
    "KET": {"name_en": "Kennedy Town", "name_zh": "堅尼地城"},
    "TKW": {"name_en": "To Kwa Wan", "name_zh": "土瓜灣"},
    "ETS": {"name_en": "East Tsim Sha Tsui", "name_zh": "尖東"},
    "MKK": {"name_en": "Mong Kok East", "name_zh": "旺角東"},
}

# Station accessibility data: which exits have lifts
STATION_ACCESSIBILITY: dict[str, dict] = {
    "TAP": {  # Tai Po Market
        "step_free": True,
        "lift_exits": ["Exit A (Nga Wan Road)", "Exit B (Bus Terminus)"],
        "wide_gate_location": "Concourse level, near Customer Service Centre",
        "accessible_toilet": True,
        "tactile_guide_path": True,
    },
    "SHT": {  # Sha Tin
        "step_free": True,
        "lift_exits": ["Exit B (Bus Terminus)", "Exit A1 (New Town Plaza)"],
        "wide_gate_location": "Concourse level",
        "accessible_toilet": True,
        "tactile_guide_path": True,
    },
    "ADM": {  # Admiralty
        "step_free": True,
        "lift_exits": ["Exit E (Queensway)", "Exit F (Tamar Park)"],
        "wide_gate_location": "All concourse levels",
        "accessible_toilet": True,
        "tactile_guide_path": True,
    },
    "CEN": {  # Central
        "step_free": True,
        "lift_exits": ["Exit A (Connaught Road)", "Exit J (Chater Garden)"],
        "wide_gate_location": "Concourse level",
        "accessible_toilet": True,
        "tactile_guide_path": True,
    },
}

# Citybus/NWFB route data (sample)
CITYBUS_ROUTES: list[dict] = [
    {"route": "1", "origin": "Central (Exchange Square)", "dest": "Happy Valley",
     "low_floor": True, "wheelchair_accessible": True},
    {"route": "5B", "origin": "Kennedy Town", "dest": "Causeway Bay",
     "low_floor": True, "wheelchair_accessible": True},
    {"route": "10", "origin": "Kennedy Town", "dest": "North Point",
     "low_floor": True, "wheelchair_accessible": True},
    {"route": "77", "origin": "Shau Kei Wan", "dest": "Aberdeen",
     "low_floor": True, "wheelchair_accessible": True},
    {"route": "99", "origin": "Shau Kei Wan", "dest": "Aberdeen",
     "low_floor": True, "wheelchair_accessible": True},
]

# Green minibus route data (sample — for reference, most are NOT wheelchair accessible)
GMB_ROUTES: list[dict] = [
    {"route": "1", "origin": "Central", "dest": "The Peak",
     "wheelchair_accessible": False},
    {"route": "25M", "origin": "Kowloon Tong", "dest": "Lok Fu",
     "wheelchair_accessible": False},
]


# ---------------------------------------------------------------------------
# MCP Server implementation
# ---------------------------------------------------------------------------

# Create the MCP server instance
server = Server("hk-transit-mcp")


# Tool: list MTR lines
@server.list_tools()
async def list_tools() -> list[Tool]:
    """Return the list of tools this MCP server provides.

    Each tool definition includes a name, description, and JSON Schema for
    its input parameters. The LLM uses these definitions to decide when and
    how to call each tool.
    """
    return [
        Tool(
            name="list_mtr_lines",
            description="List all MTR heavy rail lines with their station codes and colors.",
            inputSchema={
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "enum": ["en", "zh"],
                        "description": "Language for line names (default: en)",
                    },
                },
            },
        ),
        Tool(
            name="get_mtr_station_info",
            description=(
                "Get detailed information about an MTR station, including "
                "accessibility features, lift locations, and connecting lines."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "station_code": {
                        "type": "string",
                        "description": "3-letter MTR station code (e.g., ADM, CEN, TST)",
                    },
                },
                "required": ["station_code"],
            },
        ),
        Tool(
            name="search_station_by_name",
            description=(
                "Search for an MTR station by its English or Chinese name. "
                "Returns matching stations with their codes and accessibility info."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Station name or partial name (English or Chinese)",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_station_accessibility",
            description=(
                "Get detailed accessibility information for an MTR station: "
                "lift-equipped exits, wide gate locations, accessible toilets, "
                "and tactile guide paths."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "station_code": {
                        "type": "string",
                        "description": "3-letter MTR station code",
                    },
                },
                "required": ["station_code"],
            },
        ),
        Tool(
            name="search_accessible_bus_routes",
            description=(
                "Search for wheelchair-accessible bus routes between two areas "
                "in Hong Kong. Returns Citybus/KMB routes with low-floor bus info."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "area_from": {
                        "type": "string",
                        "description": "Starting area (e.g., 'Central', 'Sha Tin')",
                    },
                    "area_to": {
                        "type": "string",
                        "description": "Destination area",
                    },
                },
                "required": ["area_from", "area_to"],
            },
        ),
        Tool(
            name="check_transit_mode_accessibility",
            description=(
                "Check whether a specific transport mode is wheelchair accessible "
                "in Hong Kong. Returns accessibility status and any caveats."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["MTR", "KMB", "CTB", "GMB", "FERRY", "TRAM", "NLB"],
                        "description": "Transport mode to check",
                    },
                },
                "required": ["mode"],
            },
        ),
    ]


# Tool handlers
@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls from the LLM.

    Each tool call is dispatched to the appropriate handler function.
    Results are returned as TextContent (JSON strings) that the LLM can
    incorporate into its response.
    """

    if name == "list_mtr_lines":
        lang = arguments.get("language", "en")
        lines = []
        for code, info in MTR_LINES.items():
            line = {
                "code": code,
                "name": info["name_en"] if lang == "en" else info["name_zh"],
                "color": info["color"],
                "station_count": len(info["stations"]),
            }
            lines.append(line)
        return [TextContent(
            type="text",
            text=json.dumps({"lines": lines}, ensure_ascii=False, indent=2),
        )]

    elif name == "get_mtr_station_info":
        code = arguments["station_code"].upper()
        station = MTR_STATIONS.get(code)
        if not station:
            return [TextContent(
                type="text",
                text=json.dumps({"error": f"Unknown station code: {code}"}),
            )]

        # Find which lines serve this station
        serving_lines = []
        for line_code, line_info in MTR_LINES.items():
            if code in line_info["stations"]:
                serving_lines.append(line_info["name_en"])

        access = STATION_ACCESSIBILITY.get(code, {})
        return [TextContent(
            type="text",
            text=json.dumps({
                "code": code,
                "name_en": station["name_en"],
                "name_zh": station["name_zh"],
                "lines": serving_lines,
                "step_free": access.get("step_free", False),
                "lift_exits": access.get("lift_exits", []),
                "wide_gate_location": access.get("wide_gate_location", "Unknown"),
                "accessible_toilet": access.get("accessible_toilet", False),
                "tactile_guide_path": access.get("tactile_guide_path", False),
            }, ensure_ascii=False, indent=2),
        )]

    elif name == "search_station_by_name":
        query = arguments["query"].lower()
        matches = []
        for code, station in MTR_STATIONS.items():
            if (query in station["name_en"].lower() or
                    query in station["name_zh"]):
                access = STATION_ACCESSIBILITY.get(code, {})
                matches.append({
                    "code": code,
                    "name_en": station["name_en"],
                    "name_zh": station["name_zh"],
                    "step_free": access.get("step_free", False),
                    "lift_exits": access.get("lift_exits", []),
                })
        return [TextContent(
            type="text",
            text=json.dumps({"matches": matches}, ensure_ascii=False, indent=2),
        )]

    elif name == "get_station_accessibility":
        code = arguments["station_code"].upper()
        access = STATION_ACCESSIBILITY.get(code)
        if not access:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": (
                        f"No accessibility data for station {code}. "
                        f"Check mtr.com.hk for step-free access information."
                    ),
                }),
            )]
        station = MTR_STATIONS.get(code, {})
        return [TextContent(
            type="text",
            text=json.dumps({
                "station_code": code,
                "station_name": station.get("name_en", code),
                **access,
            }, ensure_ascii=False, indent=2),
        )]

    elif name == "search_accessible_bus_routes":
        area_from = arguments["area_from"].lower()
        area_to = arguments["area_to"].lower()
        matches = []
        for route in CITYBUS_ROUTES:
            if (area_from in route["origin"].lower() and
                    area_to in route["dest"].lower()):
                if route["wheelchair_accessible"]:
                    matches.append(route)
        return [TextContent(
            type="text",
            text=json.dumps({
                "routes": matches,
                "note": (
                    "Data from Citybus/KMB public timetables. "
                    "Low-floor bus availability varies by departure. "
                    "Check operator apps for real-time accessible bus ETAs."
                ),
            }, ensure_ascii=False, indent=2),
        )]

    elif name == "check_transit_mode_accessibility":
        mode = arguments["mode"].upper()
        accessibility = {
            "MTR": {
                "wheelchair_accessible": True,
                "caveats": (
                    "Not all exits have lifts. Use step-free access guide. "
                    "Wide gates available at all stations."
                ),
            },
            "KMB": {
                "wheelchair_accessible": True,
                "caveats": (
                    "Low-floor buses available on most routes, but not all "
                    "departures. Look for wheelchair symbol on bus."
                ),
            },
            "CTB": {
                "wheelchair_accessible": True,
                "caveats": (
                    "All Citybus routes use low-floor buses. Wheelchair ramp "
                    "at rear door. One wheelchair space per bus."
                ),
            },
            "GMB": {
                "wheelchair_accessible": False,
                "caveats": (
                    "Green minibuses are NOT wheelchair accessible. "
                    "No low-floor GMB routes exist in Hong Kong."
                ),
            },
            "TRAM": {
                "wheelchair_accessible": False,
                "caveats": (
                    "Hong Kong Tramways have step-up entry only. "
                    "Not accessible for wheelchair users."
                ),
            },
            "FERRY": {
                "wheelchair_accessible": True,
                "caveats": (
                    "Star Ferry: wheelchair accessible at Central and TST piers. "
                    "Other ferry operators vary — check before travelling."
                ),
            },
            "NLB": {
                "wheelchair_accessible": True,
                "caveats": (
                    "New Lantao Bus: low-floor buses on most trunk routes. "
                    "Some rural routes use smaller buses — check ahead."
                ),
            },
        }
        info = accessibility.get(mode, {"wheelchair_accessible": False,
                                         "caveats": "Unknown mode"})
        return [TextContent(
            type="text",
            text=json.dumps({"mode": mode, **info}, ensure_ascii=False, indent=2),
        )]

    else:
        return [TextContent(
            type="text",
            text=json.dumps({"error": f"Unknown tool: {name}"}),
        )]


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

async def main():
    """Run the MCP server over stdio.

    This is the standard way to run an MCP server for local use.
    The host client (Claude Code, Cursor, etc.) spawns this process
    and communicates via stdin/stdout using JSON-RPC 2.0.
    """
    logger.info("Starting hk-transit-mcp server...")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
