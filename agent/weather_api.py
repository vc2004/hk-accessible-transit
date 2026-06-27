"""
Hong Kong Observatory (HKO) real-time weather API client.

Data sources (free, no API key):
- Current weather: data.weather.gov.hk/weatherAPI/opendata/weather.php
- Weather warnings: dataType=warnsum (typhoon, rainstorm, thunderstorm, etc.)
- 9-day forecast: dataType=fnd

All endpoints are public JSON — no authentication required.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Optional
from urllib.request import urlopen, Request

logger = logging.getLogger(__name__)


@dataclass
class WeatherWarning:
    code: str  # e.g., "WTCSGNL" (tropical cyclone), "WRAIN" (rainstorm)
    name_en: str
    name_zh: str
    level: str  # e.g., "1", "3", "8", "AMBER", "RED", "BLACK"
    message: str = ""
    action_code: str = ""  # e.g., "CANCEL", "ISSUE", "EXTEND"


@dataclass
class CurrentWeather:
    temperature: float = 0
    humidity: int = 0
    rainfall: float = 0  # mm in past hour
    warning_message: str = ""
    icon: str = ""  # Weather icon code
    update_time: str = ""


class WeatherAPIClient:
    """Queries Hong Kong Observatory open data API."""

    HKO_BASE = "https://data.weather.gov.hk/weatherAPI/opendata/weather.php"

    # Warning code → severity mapping for accessibility
    WARNING_SEVERITY = {
        "WTCSGNL": {"1": "info", "3": "warning", "8": "critical", "9": "critical", "10": "critical"},
        "WRAIN": {"AMBER": "info", "RED": "warning", "BLACK": "critical"},
        "WTHUNDER": {"": "warning"},
        "WHOT": {"": "warning"},   # Very hot weather
        "WCOLD": {"": "info"},     # Cold weather
        "WFNTSA": {"": "warning"},  # Flooding (special announcement)
        "WL": {"": "warning"},      # Landslip warning
        "WTMW": {"": "info"},       # Tsunami warning
    }

    async def get_current_weather(self, lang: str = "en") -> CurrentWeather:
        """Get current weather conditions."""
        url = f"{self.HKO_BASE}?dataType=rhrread&lang={lang}"
        try:
            data = await self._fetch_json(url)
            temp_data = data.get("temperature", {})
            humidity_data = data.get("humidity", {})
            rainfall_data = data.get("rainfall", {})

            temp = temp_data.get("data", [{}])[0].get("value", 0) if temp_data.get("data") else 0
            humidity = humidity_data.get("data", [{}])[0].get("value", 0) if humidity_data.get("data") else 0
            rain = rainfall_data.get("data", [{}])[0].get("max", 0) if rainfall_data.get("data") else 0

            return CurrentWeather(
                temperature=float(temp),
                humidity=int(humidity),
                rainfall=float(rain),
                icon=data.get("icon", [""])[0] if data.get("icon") else "",
                update_time=data.get("updateTime", ""),
            )
        except Exception as e:
            logger.error(f"HKO current weather error: {e}")
            return CurrentWeather()

    async def get_warnings(self, lang: str = "en") -> list[WeatherWarning]:
        """Get active weather warnings (typhoon, rainstorm, etc.)."""
        url = f"{self.HKO_BASE}?dataType=warnsum&lang={lang}"
        try:
            data = await self._fetch_json(url)
            warnings = []
            for w in data.get("details", []):
                warnings.append(WeatherWarning(
                    code=w.get("code", ""),
                    name_en=w.get("name", ""),
                    name_zh=w.get("name_c", ""),
                    level=w.get("level", ""),
                    message=w.get("contents", [""])[0] if w.get("contents") else "",
                    action_code=w.get("actionCode", ""),
                ))
            return warnings
        except Exception as e:
            logger.error(f"HKO warnings error: {e}")
            return []

    async def get_warning_summary(self, lang: str = "en") -> str:
        """Get a human-readable summary of active warnings.

        Returns empty string if no warnings are active.
        """
        try:
            warnings = await self.get_warnings(lang)
            if not warnings:
                return ""

            lines = []
            for w in warnings:
                severity = "⚠️"
                code = w.code
                sev_map = self.WARNING_SEVERITY.get(code, {})
                sev = sev_map.get(w.level, sev_map.get("", "warning"))
                if sev == "critical":
                    severity = "🚨"
                elif sev == "warning":
                    severity = "⚠️"
                else:
                    severity = "ℹ️"

                name = w.name_en if lang == "en" else w.name_zh
                level_str = f" (Level: {w.level})" if w.level else ""
                lines.append(f"{severity} {name}{level_str}")

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"HKO warning summary error: {e}")
            return ""

    def get_accessibility_alerts(self, weather: CurrentWeather, warnings: list[WeatherWarning]) -> list[dict]:
        """Generate accessibility-specific alerts from weather data.

        Returns list of {message, severity} dicts for inclusion in route guidance.
        """
        alerts = []

        # Check for typhoon/rainstorm warnings
        for w in warnings:
            sev_map = self.WARNING_SEVERITY.get(w.code, {})
            sev = sev_map.get(w.level, sev_map.get("", ""))

            if w.code == "WTCSGNL" and w.level in ("8", "9", "10"):
                alerts.append({
                    "severity": "critical",
                    "message": (
                        f"🚨 Typhoon Signal {w.level} is hoisted. Most public transport "
                        f"is suspended or limited. ONLY travel if absolutely essential. "
                        f"MTR may run limited services above ground."
                    ),
                })
            elif w.code == "WTCSGNL" and w.level == "3":
                alerts.append({
                    "severity": "warning",
                    "message": (
                        f"⚠️ Typhoon Signal 3 is hoisted. Outdoor walking segments "
                        f"may be dangerous in strong winds. Prefer indoor routes."
                    ),
                })
            elif w.code == "WRAIN" and w.level in ("RED", "BLACK"):
                alerts.append({
                    "severity": "critical" if w.level == "BLACK" else "warning",
                    "message": (
                        f"{'🚨' if w.level == 'BLACK' else '⚠️'} {w.level} Rainstorm "
                        f"warning. Wet surfaces increase slip risk for wheelchair users. "
                        f"Avoid outdoor segments. Check MTR service status."
                    ),
                })
            elif w.code == "WTHUNDER":
                alerts.append({
                    "severity": "warning",
                    "message": (
                        "⚠️ Thunderstorm warning. Outdoor walking and ferry segments "
                        "may be affected. Prefer MTR."
                    ),
                })
            elif w.code == "WHOT":
                alerts.append({
                    "severity": "warning",
                    "message": (
                        f"☀️ Very Hot Weather Warning ({weather.temperature}°C). "
                        f"Elderly users: limit outdoor walking to 5 min or less. "
                        f"Stay hydrated. Use air-conditioned MTR where possible."
                    ),
                })

        # Rain check
        if weather.rainfall > 5:
            alerts.append({
                "severity": "warning",
                "message": (
                    f"🌧️ Recent rainfall: {weather.rainfall}mm. Outdoor surfaces "
                    f"may be slippery. Wheelchair users: reduce speed on ramps."
                ),
            })

        return alerts

    async def _fetch_json(self, url: str, timeout: int = 10) -> dict:
        """Fetch JSON from URL asynchronously."""
        def _sync_fetch():
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))

        return await asyncio.to_thread(_sync_fetch)


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

async def main():
    client = WeatherAPIClient()
    print("HKO Weather API Test\n")

    weather = await client.get_current_weather()
    print(f"Temperature: {weather.temperature}°C")
    print(f"Humidity: {weather.humidity}%")
    print(f"Rainfall (past hour): {weather.rainfall}mm")

    warnings = await client.get_warnings()
    print(f"\nActive warnings: {len(warnings)}")
    for w in warnings:
        print(f"  {w.code}: {w.name_en} ({w.level}) - {w.action_code}")

    alerts = client.get_accessibility_alerts(weather, warnings)
    print(f"\nAccessibility alerts: {len(alerts)}")
    for a in alerts:
        print(f"  [{a['severity']}] {a['message'][:80]}...")


if __name__ == "__main__":
    asyncio.run(main())
