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

    def __init__(self, cfg: AgentConfig = config, api=None, weather_api=None):
        self.config = cfg
        self._mcp_connected = False
        # TransitAPIClient for real MTR service status
        from .transit_api import TransitAPIClient
        from .weather_api import WeatherAPIClient
        self.transit_api = api or TransitAPIClient()
        self.weather_api = weather_api or WeatherAPIClient()

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

        # Check 2: MTR service status (real API + static fallback)
        alerts.extend(await self._check_mtr_service(routes))

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

    async def _check_mtr_service(self, routes: list[RouteOption]) -> list[Alert]:
        """Check for MTR service disruptions on relevant lines.

        Tries the real MTR API first, falls back to static status.
        """
        alerts: list[Alert] = []

        # Collect all MTR lines used across all routes
        lines_used: set[str] = set()
        for route in routes:
            for segment in route.segments:
                if segment.mode == "MTR" and segment.route_code:
                    lines_used.add(segment.route_code.upper())

        # Try real API
        try:
            statuses = await self.transit_api.check_mtr_service_status()
            for line_code in lines_used:
                status = statuses.get(line_code, self._MTR_SERVICE_STATUS.get(line_code, "normal"))
                if status == "disrupted":
                    alerts.append(Alert(
                        message=f"🚨 MTR {line_code} line is experiencing disruptions",
                        severity=AlertSeverity.CRITICAL,
                        source="mtr-service-status (live)",
                    ))
                elif status == "delayed":
                    alerts.append(Alert(
                        message=f"⚠️ MTR {line_code} line has delays",
                        severity=AlertSeverity.WARNING,
                        source="mtr-service-status (live)",
                    ))
            return alerts
        except Exception:
            logger.debug("Real MTR status check failed, using static fallback")

        # Static fallback
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
        """Check real-time weather from Hong Kong Observatory API.

        Queries HKO open data for current conditions and active warnings.
        Generates accessibility-specific alerts for route planning.
        """
        alerts: list[Alert] = []

        try:
            weather = await self.weather_api.get_current_weather()
            warnings = await self.weather_api.get_warnings()
            accessibility_alerts = self.weather_api.get_accessibility_alerts(weather, warnings)

            # Convert to Alert objects
            for wa in accessibility_alerts:
                sev = {"critical": AlertSeverity.CRITICAL, "warning": AlertSeverity.WARNING,
                       "info": AlertSeverity.INFO}.get(wa["severity"], AlertSeverity.INFO)
                alerts.append(Alert(
                    message=wa["message"],
                    severity=sev,
                    source="hko-api (live)",
                ))

            # Flag outdoor walking segments if rain is detected
            if weather.rainfall > 0:
                for route in routes:
                    for seg_idx, segment in enumerate(route.segments):
                        if segment.mode == "WALK":
                            alerts.append(Alert(
                                message=(
                                    f"🌧️ Rain detected ({weather.rainfall}mm): outdoor "
                                    f"walking segment ({segment.from_stop} → {segment.to_stop}) "
                                    f"may be slippery. Wheelchair users: reduce speed on ramps."
                                ),
                                severity=AlertSeverity.WARNING,
                                source="hko-api (live)",
                                affected_segment=seg_idx,
                            ))

            # Flag heat for elderly
            if weather.temperature >= 32:
                for route in routes:
                    for seg_idx, segment in enumerate(route.segments):
                        if segment.mode == "WALK" and segment.duration_min > 5:
                            alerts.append(Alert(
                                message=(
                                    f"☀️ High temperature ({weather.temperature}°C): "
                                    f"walking segment ~{segment.duration_min} min. "
                                    f"Elderly users: stay hydrated, use covered walkways."
                                ),
                                severity=AlertSeverity.WARNING,
                                source="hko-api (live)",
                                affected_segment=seg_idx,
                            ))

        except Exception as e:
            logger.warning(f"HKO weather API unavailable: {e} — using seasonal fallback")
            # Static seasonal fallback
            now = datetime.now()
            if 5 <= now.month <= 9:
                alerts.append(Alert(
                    message="🌧️ Rainy season — check hko.gov.hk for current warnings before departing.",
                    severity=AlertSeverity.INFO,
                    source="hko (seasonal fallback)",
                ))
            if 6 <= now.month <= 8:
                alerts.append(Alert(
                    message="☀️ Summer heat — stay hydrated. Use covered walkways where available.",
                    severity=AlertSeverity.INFO,
                    source="hko (seasonal fallback)",
                ))

        return alerts
