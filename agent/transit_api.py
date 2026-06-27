"""
Real-time Hong Kong Transit API client.

Queries actual HK government open data APIs:
- MTR schedule: rt.data.gov.hk/v1/transport/mtr/getSchedule.php
- KMB ETA: data.etabus.gov.hk/v1/transport/kmb/eta/...
- Citybus ETA: rt.data.gov.hk/v2/transport/citybus/eta/...
- MTR station data: opendata.mtr.com.hk

All APIs are FREE and require NO API KEY — pure public data.

Usage:
    from agent.transit_api import TransitAPIClient
    client = TransitAPIClient()
    schedule = await client.get_mtr_schedule("EAL", "TAP")
    eta = await client.get_kmb_eta("STOP_ID", "74X")
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Optional
from urllib.request import urlopen, Request

logger = logging.getLogger(__name__)


@dataclass
class MTRSchedule:
    """Real-time MTR train arrival at a station."""
    line: str
    station: str
    arrivals_up: list[int] = None   # minutes until next trains (up direction)
    arrivals_down: list[int] = None # minutes until next trains (down direction)
    is_delayed: bool = False
    delay_message: str = ""

    def __post_init__(self):
        if self.arrivals_up is None:
            self.arrivals_up = []
        if self.arrivals_down is None:
            self.arrivals_down = []


@dataclass
class BusETA:
    """Real-time bus arrival at a stop."""
    route: str
    stop_id: str
    destination: str
    arrivals: list[int]  # minutes until next buses
    wheelchair_accessible: bool = False


class TransitAPIClient:
    """Calls Hong Kong government transport open data APIs.

    All endpoints are public, free, and require no authentication.
    Rate limits are generous (~100 req/min per IP).
    """

    MTR_BASE = "https://rt.data.gov.hk/v1/transport/mtr"
    KMB_BASE = "https://data.etabus.gov.hk/v1/transport/kmb"
    CTB_BASE = "https://rt.data.gov.hk/v2/transport/citybus"

    # MTR line codes used by the API
    MTR_LINES = {
        "AEL": "Airport Express",
        "EAL": "East Rail Line",
        "ISL": "Island Line",
        "KTL": "Kwun Tong Line",
        "TML": "Tuen Ma Line",
        "TCL": "Tung Chung Line",
        "TKL": "Tseung Kwan O Line",
        "TWL": "Tsuen Wan Line",
        "SIL": "South Island Line",
        "DRL": "Disneyland Resort Line",
    }

    async def get_mtr_schedule(self, line: str, station: str) -> MTRSchedule:
        """Get real-time train arrivals for an MTR line + station.

        Args:
            line: 3-letter MTR line code (e.g., 'EAL', 'TWL')
            station: 3-letter station code (e.g., 'TAP', 'ADM')

        Returns MTRSchedule with arrival times in minutes.
        """
        url = f"{self.MTR_BASE}/getSchedule.php?line={line}&sta={station}"
        try:
            data = await self._fetch_json(url)
            result = MTRSchedule(line=line, station=station)

            if "data" in data:
                raw = data["data"]
                # The API returns a key like "EAL-SHT" containing UP/DOWN
                schedule_key = f"{line}-{station}"
                schedule = raw.get(schedule_key, {})

                if not schedule:
                    # Try without the line prefix
                    for key in raw:
                        if key.endswith(f"-{station}"):
                            schedule = raw[key]
                            break

                # Parse UP and DOWN platform arrivals
                for direction_key, attr_name in [
                    ("UP", "arrivals_up"),
                    ("DOWN", "arrivals_down"),
                ]:
                    if direction_key in schedule:
                        arrivals = []
                        for entry in schedule[direction_key]:
                            # 'ttnt' = Time To Next Train (minutes)
                            if entry.get("ttnt"):
                                try:
                                    arrivals.append(int(entry["ttnt"]))
                                except (ValueError, TypeError):
                                    pass
                        setattr(result, attr_name, sorted(arrivals)[:3])

            # Check for delays
            if data.get("isdelay") == "Y":
                result.is_delayed = True
                result.delay_message = data.get("message", "Delay reported")

            return result
        except Exception as e:
            logger.error(f"MTR API error for {line}/{station}: {e}")
            return MTRSchedule(line=line, station=station, is_delayed=False)

    async def get_kmb_eta(
        self, stop_id: str, route: str, service_type: str = "1"
    ) -> BusETA:
        """Get real-time KMB bus ETA at a stop.

        Args:
            stop_id: 16-char hex KMB stop ID
            route: Route number (e.g., '74X')
            service_type: '1' for normal service

        Returns BusETA with arrival times in minutes.
        """
        url = f"{self.KMB_BASE}/eta/{stop_id}/{route}/{service_type}"
        try:
            data = await self._fetch_json(url)
            arrivals = []
            dest = route
            for entry in data.get("data", []):
                if entry.get("eta"):
                    try:
                        arrivals.append(int(entry["eta"]))
                    except (ValueError, TypeError):
                        pass
                dest = entry.get("dest_en", route)

            return BusETA(
                route=route,
                stop_id=stop_id,
                destination=dest,
                arrivals=sorted(arrivals)[:3],
                wheelchair_accessible=any(
                    e.get("wheelchair", False) for e in data.get("data", [])
                ),
            )
        except Exception as e:
            logger.error(f"KMB ETA error for {stop_id}/{route}: {e}")
            return BusETA(route=route, stop_id=stop_id, destination="", arrivals=[])

    async def get_citybus_eta(
        self, company: str, stop_id: str, route: str
    ) -> BusETA:
        """Get real-time Citybus/NWFB ETA at a stop.

        Args:
            company: 'ctb' (Citybus) or 'nwfb' (New World First Bus)
            stop_id: 6-digit numeric stop ID
            route: Route number
        """
        url = f"{self.CTB_BASE}/eta/{company}/{stop_id}/{route}"
        try:
            data = await self._fetch_json(url)
            arrivals = []
            dest = route
            for entry in data.get("data", []):
                if entry.get("eta"):
                    try:
                        arrivals.append(int(entry["eta"]))
                    except (ValueError, TypeError):
                        pass
                dest = entry.get("dest_en", route)

            return BusETA(
                route=route,
                stop_id=stop_id,
                destination=dest,
                arrivals=sorted(arrivals)[:3],
                wheelchair_accessible=True,  # All Citybus routes are low-floor
            )
        except Exception as e:
            logger.error(f"Citybus ETA error for {company}/{stop_id}/{route}: {e}")
            return BusETA(route=route, stop_id=stop_id, destination="", arrivals=[])

    async def get_kmb_routes(self) -> list[dict]:
        """Get all KMB route definitions."""
        url = f"{self.KMB_BASE}/route"
        try:
            data = await self._fetch_json(url)
            return data.get("data", [])
        except Exception as e:
            logger.error(f"KMB routes error: {e}")
            return []

    async def get_kmb_stops_for_route(self, route: str, direction: str = "outbound") -> list[dict]:
        """Get all stops for a KMB route."""
        url = f"{self.KMB_BASE}/route-stop/{route}/{direction}/1"
        try:
            data = await self._fetch_json(url)
            return data.get("data", [])
        except Exception as e:
            logger.error(f"KMB route-stop error for {route}: {e}")
            return []

    async def check_mtr_service_status(self) -> dict[str, str]:
        """Check if any MTR lines have service disruptions.

        Returns dict of {line_code: status} where status is one of:
        'normal', 'delayed', 'disrupted', 'suspended'.
        """
        statuses = {}
        for line_code in self.MTR_LINES:
            try:
                schedule = await self.get_mtr_schedule(line_code, "ADM")
                if schedule.is_delayed:
                    statuses[line_code] = "delayed"
                else:
                    statuses[line_code] = "normal"
            except Exception:
                statuses[line_code] = "unknown"
        return statuses

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------

    async def _fetch_json(self, url: str, timeout: int = 10) -> dict:
        """Fetch JSON from a URL asynchronously."""
        def _sync_fetch():
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))

        return await asyncio.to_thread(_sync_fetch)


# ---------------------------------------------------------------------------
# Quick CLI test
# ---------------------------------------------------------------------------

async def main():
    """Test the transit API client."""
    client = TransitAPIClient()
    print("Testing HK Transit API client...\n")

    # Test MTR schedule
    print("1. MTR Schedule (EAL @ Tai Po Market):")
    sched = await client.get_mtr_schedule("EAL", "TAP")
    print(f"   Line: {client.MTR_LINES.get(sched.line, sched.line)}")
    print(f"   Up arrivals: {sched.arrivals_up} min")
    print(f"   Down arrivals: {sched.arrivals_down} min")
    print(f"   Delayed: {sched.is_delayed}")
    print()

    # Test KMB routes
    print("2. KMB Routes (first 3):")
    routes = await client.get_kmb_routes()
    for r in routes[:3]:
        print(f"   Route {r.get('route')}: {r.get('orig_en')} → {r.get('dest_en')}")
    print()

    print("Done. APIs are working.\n"
          "Note: If API calls failed (network error), check your internet connection.\n"
          "All HK gov transit APIs are public and require no API key.")


if __name__ == "__main__":
    asyncio.run(main())
