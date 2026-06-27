"""
In-process MCP tool handlers — called directly without subprocess overhead.

When MCP servers are unavailable as subprocesses, these handlers provide
the same functionality via direct Python imports. Each returns data from the
same source (static DB + live APIs) as the MCP server would.

Registered automatically with MCPConnector._IN_PROCESS_REGISTRY.
"""

import json

# ---------------------------------------------------------------------------
# hk-transit tools
# ---------------------------------------------------------------------------

# Pull in the static data from the MCP server module
from mcp_servers.hk_transit_mcp.server import (
    MTR_LINES,
    MTR_STATIONS,
    STATION_ACCESSIBILITY,
    CITYBUS_ROUTES,
    GMB_ROUTES,
)


def hk_transit_tools() -> dict[str, dict]:
    """Return tool schemas for hk-transit-mcp."""
    return {
        "list_mtr_lines": {
            "name": "list_mtr_lines",
            "description": "List all MTR heavy rail lines with station codes and colors.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "language": {"type": "string", "enum": ["en", "zh"]},
                },
            },
        },
        "get_mtr_station_info": {
            "name": "get_mtr_station_info",
            "description": "Get detailed information about an MTR station.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "station_code": {"type": "string"},
                },
                "required": ["station_code"],
            },
        },
        "search_station_by_name": {
            "name": "search_station_by_name",
            "description": "Search MTR station by English or Chinese name.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        },
        "get_station_accessibility": {
            "name": "get_station_accessibility",
            "description": "Get accessibility info for an MTR station.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "station_code": {"type": "string"},
                },
                "required": ["station_code"],
            },
        },
        "search_accessible_bus_routes": {
            "name": "search_accessible_bus_routes",
            "description": "Search wheelchair-accessible bus routes between areas.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "area_from": {"type": "string"},
                    "area_to": {"type": "string"},
                },
                "required": ["area_from", "area_to"],
            },
        },
        "check_transit_mode_accessibility": {
            "name": "check_transit_mode_accessibility",
            "description": "Check if a transport mode is wheelchair accessible.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["MTR", "KMB", "CTB", "GMB", "FERRY", "TRAM", "NLB"],
                    },
                },
                "required": ["mode"],
            },
        },
    }


def hk_transit_call_tool(tool_name: str, arguments: dict) -> str:
    """Handle tool calls for hk-transit-mcp in-process."""
    if tool_name == "list_mtr_lines":
        lang = arguments.get("language", "en")
        lines = []
        for code, info in MTR_LINES.items():
            lines.append({
                "code": code,
                "name": info["name_en"] if lang == "en" else info["name_zh"],
                "color": info["color"],
                "station_count": len(info["stations"]),
            })
        return json.dumps({"lines": lines}, ensure_ascii=False, indent=2)

    elif tool_name == "get_mtr_station_info":
        code = arguments["station_code"].upper()
        station = MTR_STATIONS.get(code)
        if not station:
            return json.dumps({"error": f"Unknown station code: {code}"})
        serving_lines = [
            info["name_en"]
            for line_code, info in MTR_LINES.items()
            if code in info["stations"]
        ]
        access = STATION_ACCESSIBILITY.get(code, {})
        return json.dumps({
            "code": code,
            "name_en": station["name_en"],
            "name_zh": station.get("name_zh", ""),
            "lines": serving_lines,
            "step_free": access.get("step_free", False),
            "lift_exits": access.get("lift_exits", []),
            "wide_gate_location": access.get("wide_gate_location", "Unknown"),
            "accessible_toilet": access.get("accessible_toilet", False),
            "tactile_guide_path": access.get("tactile_guide_path", False),
        }, ensure_ascii=False, indent=2)

    elif tool_name == "search_station_by_name":
        query = arguments["query"].lower()
        matches = []
        for code, station in MTR_STATIONS.items():
            if query in station["name_en"].lower() or query in station.get("name_zh", ""):
                access = STATION_ACCESSIBILITY.get(code, {})
                matches.append({
                    "code": code,
                    "name_en": station["name_en"],
                    "name_zh": station.get("name_zh", ""),
                    "step_free": access.get("step_free", False),
                    "lift_exits": access.get("lift_exits", []),
                })
        return json.dumps({"matches": matches}, ensure_ascii=False, indent=2)

    elif tool_name == "get_station_accessibility":
        code = arguments["station_code"].upper()
        access = STATION_ACCESSIBILITY.get(code)
        station = MTR_STATIONS.get(code, {})
        if not access:
            return json.dumps({
                "error": f"No accessibility data for {code}. Check mtr.com.hk."
            })
        return json.dumps({
            "station_code": code,
            "station_name": station.get("name_en", code),
            **access,
        }, ensure_ascii=False, indent=2)

    elif tool_name == "search_accessible_bus_routes":
        area_from = arguments["area_from"].lower()
        area_to = arguments["area_to"].lower()
        matches = [
            r for r in CITYBUS_ROUTES
            if area_from in r["origin"].lower() and area_to in r["dest"].lower()
            and r["wheelchair_accessible"]
        ]
        return json.dumps({"routes": matches}, ensure_ascii=False, indent=2)

    elif tool_name == "check_transit_mode_accessibility":
        mode = arguments["mode"].upper()
        accessibility = {
            "MTR": {"wheelchair_accessible": True,
                    "caveats": "Not all exits have lifts. Check step-free access guide."},
            "KMB": {"wheelchair_accessible": True,
                    "caveats": "Low-floor buses on most routes. Check ETA app for accessible icon."},
            "CTB": {"wheelchair_accessible": True,
                    "caveats": "All Citybus routes are low-floor. One wheelchair space per bus."},
            "GMB": {"wheelchair_accessible": False,
                    "caveats": "Green minibuses are NOT wheelchair accessible in Hong Kong."},
            "TRAM": {"wheelchair_accessible": False,
                     "caveats": "Trams have step-up entry only — not wheelchair accessible."},
            "FERRY": {"wheelchair_accessible": True,
                      "caveats": "Star Ferry accessible; other operators vary."},
            "NLB": {"wheelchair_accessible": True,
                    "caveats": "Low-floor buses on trunk routes. Rural routes: check ahead."},
        }
        info = accessibility.get(mode, {"wheelchair_accessible": False, "caveats": "Unknown"})
        return json.dumps({"mode": mode, **info}, ensure_ascii=False, indent=2)

    return json.dumps({"error": f"Unknown tool: {tool_name}"})


# ---------------------------------------------------------------------------
# mtr-accessibility tools
# ---------------------------------------------------------------------------

from mcp_servers.mtr_accessibility_mcp.server import (
    STATION_ACCESS as MTR_ACCESS_DB,
    STATIONS_WITHOUT_STEP_FREE,
)


def mtr_accessibility_tools() -> dict[str, dict]:
    """Return tool schemas for mtr-accessibility-mcp."""
    return {
        "get_station_accessibility": {
            "name": "get_station_accessibility",
            "description": "Get comprehensive accessibility info for an MTR station.",
            "inputSchema": {
                "type": "object",
                "properties": {"station_code": {"type": "string"}},
                "required": ["station_code"],
            },
        },
        "check_lift_status": {
            "name": "check_lift_status",
            "description": "Check real-time lift status at an MTR station exit.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "station_code": {"type": "string"},
                    "exit": {"type": "string"},
                },
                "required": ["station_code"],
            },
        },
        "list_stations_without_step_free": {
            "name": "list_stations_without_step_free",
            "description": "List MTR stations without step-free access.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        "search_step_free_station": {
            "name": "search_step_free_station",
            "description": "Search nearest step-free MTR station to a location.",
            "inputSchema": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        },
        "get_interchange_accessibility": {
            "name": "get_interchange_accessibility",
            "description": "Get accessibility info for interchanging at a station.",
            "inputSchema": {
                "type": "object",
                "properties": {"station_code": {"type": "string"}},
                "required": ["station_code"],
            },
        },
    }


def mtr_accessibility_call_tool(tool_name: str, arguments: dict) -> str:
    """Handle tool calls for mtr-accessibility-mcp in-process."""
    if tool_name == "get_station_accessibility":
        code = arguments["station_code"].upper()
        data = MTR_ACCESS_DB.get(code)
        if not data:
            no_access = STATIONS_WITHOUT_STEP_FREE.get(code)
            if no_access:
                return json.dumps({
                    "station_code": code, "step_free": False,
                    "warning": no_access["reason"],
                    "alternative": no_access["alternative"],
                }, ensure_ascii=False, indent=2)
            return json.dumps({
                "station_code": code, "step_free": False,
                "warning": f"No data for {code}. Check mtr.com.hk.",
            })
        return json.dumps(data, ensure_ascii=False, indent=2)

    elif tool_name == "check_lift_status":
        code = arguments["station_code"].upper()
        exit_filter = arguments.get("exit", "").upper()
        data = MTR_ACCESS_DB.get(code, {})
        lifts = data.get("lift_exits", [])
        results = [
            {
                "station_code": code,
                "station_name": data.get("station_name_en", code),
                "exit": lift["exit"],
                "location": lift["location"],
                "status": lift.get("status", "unknown"),
                "maintenance_until": lift.get("maintenance_until"),
                "maintenance_note": lift.get("maintenance_note", ""),
            }
            for lift in lifts
            if not exit_filter or exit_filter in lift["exit"].upper()
        ]
        if not lifts:
            return json.dumps({
                "station_code": code,
                "error": f"No lift exit data for {code}",
            })
        return json.dumps({"lifts": results}, ensure_ascii=False, indent=2)

    elif tool_name == "list_stations_without_step_free":
        return json.dumps({
            "stations_without_step_free": [
                {
                    "code": code,
                    "name_en": info["station_name_en"],
                    "name_zh": info["station_name_zh"],
                    "reason": info["reason"],
                    "nearest_alternative": info["alternative"],
                }
                for code, info in STATIONS_WITHOUT_STEP_FREE.items()
            ],
        }, ensure_ascii=False, indent=2)

    elif tool_name == "search_step_free_station":
        location = arguments["location"].lower()
        matches = []
        for code, data in MTR_ACCESS_DB.items():
            if location in data["station_name_en"].lower() or location in data.get("station_name_zh", ""):
                matches.append({
                    "code": code,
                    "name_en": data["station_name_en"],
                    "name_zh": data.get("station_name_zh", ""),
                    "step_free": True,
                    "lift_exits": [e["exit"] for e in data.get("lift_exits", [])
                                   if e.get("status") == "normal"],
                })
        for code, data in STATIONS_WITHOUT_STEP_FREE.items():
            if location in data["station_name_en"].lower() or location in data.get("station_name_zh", ""):
                matches.append({
                    "code": code,
                    "name_en": data["station_name_en"],
                    "name_zh": data.get("station_name_zh", ""),
                    "step_free": False,
                    "warning": data["reason"],
                    "alternative": data["alternative"],
                })
        return json.dumps(
            {"matches": matches} if matches else {"matches": [], "suggestion": "Try full station name."},
            ensure_ascii=False, indent=2,
        )

    elif tool_name == "get_interchange_accessibility":
        code = arguments["station_code"].upper()
        data = MTR_ACCESS_DB.get(code, {})
        return json.dumps({
            "station_code": code,
            "station_name": data.get("station_name_en", code),
            "interchange_complexity": data.get("interchange_complexity", "unknown"),
            "notes": data.get("notes", ""),
            "step_free_interchange": data.get("step_free", False),
        }, ensure_ascii=False, indent=2)

    return json.dumps({"error": f"Unknown tool: {tool_name}"})


# ---------------------------------------------------------------------------
# Register with MCPConnector
# ---------------------------------------------------------------------------

def register_in_process_tools():
    """Register all in-process tool handlers with MCPConnector."""
    from agent.mcp_connector import MCPConnector

    MCPConnector._IN_PROCESS_REGISTRY["hk-transit"] = hk_transit_tools
    MCPConnector._IN_PROCESS_REGISTRY["mtr-accessibility"] = mtr_accessibility_tools

    # Patch the connector to route calls to in-process handlers
    original_call = MCPConnector.call_tool

    async def patched_call_tool(self, tool_name: str, arguments: dict) -> str:
        if self.server_name == "hk-transit":
            return hk_transit_call_tool(tool_name, arguments)
        elif self.server_name == "mtr-accessibility":
            return mtr_accessibility_call_tool(tool_name, arguments)
        return await original_call(self, tool_name, arguments)

    MCPConnector.call_tool = patched_call_tool
