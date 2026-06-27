"""
Alert Monitor Agent — real-time disruption and hazard detection.

Checks for conditions that may affect an accessible journey:
1. MTR lift/escalator outages (from mtr-accessibility-mcp)
2. Weather warnings from Hong Kong Observatory (via hko-mcp)
3. MTR service disruptions
4. Bus route diversions or suspensions

Implements the "Red Team thinking" pattern from Day 4 Section 4.6:
    Proactively look for what could go wrong, not just confirm what works.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .config import AgentConfig, config
from .route_planner import RouteOption

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    """A real-time alert affecting a planned route."""
    message: str
    severity: AlertSeverity
    source: str  # e.g., "hko-mcp", "mtr-accessibility-mcp"
    affected_segment: Optional[int] = None  # segment index in the route
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class AlertMonitorAgent:
    """Monitors real-time conditions that affect accessible journey planning.

    Queries:
    - hko-mcp for weather warnings (rain, typhoon, thunderstorm, heat)
    - mtr-accessibility-mcp for lift/escalator status
    - MTR service status API for line disruptions
    """

    # Known lift outage patterns (static fallback when MCP unavailable).
    # In production, this is entirely replaced by real-time MCP queries.
    _KNOWN_LIFT_OUTAGES: list[dict] = [
        {
            "station": "Tai Po Market",
            "exit": "Exit B",
            "status": "under maintenance",
            "until": "2026-06-30",
            "source": "MTR Corporation",
        },
        {
            "station": "Sheung Shui",
            "exit": "Exit A",
            "status": "under maintenance",
            "until": "2026-07-15",
            "source": "MTR Corporation",
        },
    ]

    # Simulated MTR service status (in production, queried via API)
    _MTR_SERVICE_STATUS: dict[str, str] = {
        "EAL": "normal",
        "TWL": "normal",
        "ISL": "normal",
        "KTL": "normal",
        "TKL": "normal",
        "TCL": "normal",
        "TML": "normal",
        "SIL": "normal",
        "AEL": "normal",
        "DRL": "normal",
    }

    def __init__(self, cfg: AgentConfig = config):
        self.config = cfg
        self._mcp_connected = False

    # ------------------------------------------------------------------
    # Main API: check for alerts affecting a set of routes
    # ------------------------------------------------------------------

    async def check_alerts(
        self,
        routes: list[RouteOption],
        weather_sensitive: bool = False,
    ) -> list[Alert]:
        """Check for real-time alerts affecting the given routes.

        Args:
            routes: Planned route options to check
            weather_sensitive: If True, add weather-related alerts even for
                               normal conditions (e.g., user specified rain)
        """
        alerts: list[Alert] = []

        # Check 1: Lift/escalator outages (MTR accessibility)
        alerts.extend(self._check_lift_outages(routes))

        # Check 2: MTR service status
        alerts.extend(self._check_mtr_service(routes))

        # Check 3: Weather (via hko-mcp or static fallback)
        alerts.extend(await self._check_weather(routes, weather_sensitive))

        # Deduplicate by message
        seen = set()
        unique = []
        for alert in alerts:
            if alert.message not in seen:
                seen.add(alert.message)
                unique.append(alert)

        return unique

    # ------------------------------------------------------------------
    # Individual alert checks
    # ------------------------------------------------------------------

    def _check_lift_outages(self, routes: list[RouteOption]) -> list[Alert]:
        """Check if any MTR stations on the route have lift outages."""
        alerts: list[Alert] = []

        for route_idx, route in enumerate(routes):
            for seg_idx, segment in enumerate(route.segments):
                if segment.mode != "MTR":
                    continue

                for outage in self._KNOWN_LIFT_OUTAGES:
                    station = outage["station"].lower()
                    from_stop = segment.from_stop.lower()
                    to_stop = segment.to_stop.lower()

                    if station in from_stop or station in to_stop:
                        alerts.append(Alert(
                            message=(
                                f"⚠️ Lift at {outage['station']} {outage['exit']} "
                                f"is {outage['status']} until {outage['until']}. "
                                f"Use an alternative exit."
                            ),
                            severity=AlertSeverity.WARNING,
                            source="mtr-accessibility-mcp",
                            affected_segment=seg_idx,
                        ))

        return alerts

    def _check_mtr_service(self, routes: list[RouteOption]) -> list[Alert]:
        """Check for MTR service disruptions on relevant lines."""
        alerts: list[Alert] = []

        # Collect all MTR lines used across all routes
        lines_used: set[str] = set()
        for route in routes:
            for segment in route.segments:
                if segment.mode == "MTR" and segment.route_code:
                    lines_used.add(segment.route_code.upper())

        for line_code in lines_used:
            status = self._MTR_SERVICE_STATUS.get(line_code, "unknown")
            if status == "disrupted":
                alerts.append(Alert(
                    message=f"🚨 MTR {line_code} line is experiencing disruptions",
                    severity=AlertSeverity.CRITICAL,
                    source="mtr-service-status",
                ))
            elif status == "minor_delay":
                alerts.append(Alert(
                    message=f"⚠️ MTR {line_code} line has minor delays (~3-5 min)",
                    severity=AlertSeverity.WARNING,
                    source="mtr-service-status",
                ))

        return alerts

    async def _check_weather(
        self,
        routes: list[RouteOption],
        weather_sensitive: bool,
    ) -> list[Alert]:
        """Check weather conditions from HKO via hko-mcp.

        In production, this queries the hko-mcp server:
            from mcp import ClientSession
            async with stdio_client(hko_params) as (read, write):
                async with ClientSession(read, write) as session:
                    result = await session.call_tool("get_weather_warning", {})
        """
        alerts: list[Alert] = []

        # Static fallback: Hong Kong seasonal weather patterns
        # In production, replaced entirely by hko-mcp real-time data
        now = datetime.now()

        # Rainy season (May-September): always flag outdoor segments
        if 5 <= now.month <= 9:
            for route in routes:
                for seg_idx, segment in enumerate(route.segments):
                    if segment.mode == "WALK":
                        alerts.append(Alert(
                            message=(
                                f"🌧️ Rainy season (May-Sep): outdoor walking segment "
                                f"({segment.from_stop} → {segment.to_stop}) may be wet. "
                                f"Wheelchair users: wet surfaces increase slip risk."
                            ),
                            severity=AlertSeverity.WARNING,
                            source="hko-mcp (seasonal)",
                            affected_segment=seg_idx,
                        ))

            # Also flag the need for weather check
            alerts.append(Alert(
                message=(
                    "🌧️ Hong Kong rainy season. Check hko.gov.hk for current "
                    "rainstorm or thunderstorm warnings before departing."
                ),
                severity=AlertSeverity.INFO,
                source="hko-mcp",
            ))

        # Heat warning (June-August)
        if 6 <= now.month <= 8:
            for route in routes:
                for seg_idx, segment in enumerate(route.segments):
                    if segment.mode == "WALK" and segment.duration_min > 5:
                        alerts.append(Alert(
                            message=(
                                f"☀️ Summer heat: walking segment is "
                                f"~{segment.duration_min} min. Stay hydrated. "
                                f"Consider covered walkways where available."
                            ),
                            severity=AlertSeverity.INFO,
                            source="hko-mcp (seasonal)",
                            affected_segment=seg_idx,
                        ))

        return alerts
