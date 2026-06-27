"""
Orchestrator Agent — the main agent that coordinates the multi-agent system.

Implements the Orchestrator pattern from Day 1 Section 1.9:
- Receives natural language queries
- Classifies intent and accessibility profile
- Dispatches to sub-agents (Route Planner, Accessibility Filter, Alert Monitor)
- Synthesizes final response

Also implements the Agent loop pattern from Day 1 Section 1.2:
    Perceive goal → Plan steps → Execute via tools → Observe → Iterate
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from .config import (
    AgentConfig,
    AccessibilityProfile,
    ModelTier,
    SYSTEM_PROMPT,
    config,
)
from .llm_client import LLMClient, LLMConfig, get_config_from_env
from .mcp_connector import MCPConnectionPool
from .route_planner import RoutePlannerAgent, RouteOption
from .accessibility_filter import AccessibilityFilterAgent, FilterResult
from .alert_monitor import AlertMonitorAgent, Alert
from .transit_api import TransitAPIClient
from .mcp_tools import register_in_process_tools

logger = logging.getLogger(__name__)


@dataclass
class UserQuery:
    """Parsed user query with extracted intent and profile."""
    raw_text: str
    origin: str
    destination: str
    accessibility_profile: AccessibilityProfile = AccessibilityProfile.GENERAL
    prefer_cheapest: bool = False
    avoid_outdoor: bool = False
    time_constraint: Optional[str] = None  # e.g. "arrive by 10am"

    # Metadata for evaluation
    session_id: Optional[str] = None
    turn_number: int = 1


@dataclass
class AgentResponse:
    """Final synthesized response from the orchestrator."""
    routes: list[RouteOption] = field(default_factory=list)
    filter_results: list[FilterResult] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    natural_response: str = ""
    session_id: Optional[str] = None

    # Evaluation metadata
    tool_calls_made: list[str] = field(default_factory=list)
    tokens_used: int = 0
    latency_ms: float = 0.0


class OrchestratorAgent:
    """Main orchestrator that coordinates the multi-agent system.

    This is the entry point for all user interactions. It parses the query,
    dispatches to sub-agents, and synthesizes the final response.

    Architecture (Day 2 Section 2.3):
    Single orchestrator → Multiple specialist sub-agents via A2A-like dispatch.
    We use internal partitioning (shared runtime, logical isolation) rather
    than distributed multi-agent for latency reasons in this prototype.
    """

    def __init__(self, cfg: AgentConfig = config, llm: Optional[LLMClient] = None):
        self.config = cfg

        # Register in-process MCP tool handlers (no subprocess needed)
        register_in_process_tools()

        # Shared real-data infrastructure
        self.transit_api = TransitAPIClient()
        self.mcp_pool = MCPConnectionPool()

        # Sub-agents with real data access
        self.route_planner = RoutePlannerAgent(
            cfg, api=self.transit_api, mcp_pool=self.mcp_pool,
        )
        self.accessibility_filter = AccessibilityFilterAgent(cfg)
        self.alert_monitor = AlertMonitorAgent(cfg, api=self.transit_api)

        # LLM client for response synthesis (auto-detects provider from env)
        self.llm = llm or LLMClient()

        # Session memory (Day 1: Memory component of Agent = Model + Harness)
        self._session_history: dict[str, list[dict]] = {}

    # ------------------------------------------------------------------
    # Step 1: Intent parsing — classify the user's accessibility profile
    # and extract structured query parameters from natural language.
    # ------------------------------------------------------------------

    def parse_query(self, raw_text: str, session_id: Optional[str] = None) -> UserQuery:
        """Parse a natural language query into a structured UserQuery.

        Uses keyword matching + lightweight classification. In production, this
        would use the HEAVY model for robust intent parsing. For the prototype,
        we use a deterministic classifier (shift intelligence left — Day 3
        Section 3.7) to avoid LLM unpredictability for this critical step.
        """
        text_lower = raw_text.lower()

        # Classify accessibility profile
        profile = AccessibilityProfile.GENERAL
        wheelchair_keywords = [
            "wheelchair", "輪椅", "轮椅", "step-free", "barrier-free",
            "無障礙", "无障碍", "lift access",
        ]
        elderly_keywords = [
            "elderly", "old", "senior", "長者", "长者", "老人家",
            "aged", "退休", "difficult walking",
        ]
        visually_impaired_keywords = [
            "blind", "visually impaired", "視障", "视障", "看不到",
            "can't see", "cannot see",
        ]
        stroller_keywords = [
            "stroller", "pram", "baby", "toddler", "嬰兒車", "婴儿车",
            "bb車", "bb车", "with child", "with kid",
        ]

        for kw in wheelchair_keywords:
            if kw in text_lower:
                profile = AccessibilityProfile.WHEELCHAIR
                break
        for kw in elderly_keywords:
            if kw in text_lower:
                profile = AccessibilityProfile.ELDERLY
                break
        for kw in visually_impaired_keywords:
            if kw in text_lower:
                profile = AccessibilityProfile.VISUALLY_IMPAIRED
                break
        for kw in stroller_keywords:
            if kw in text_lower:
                profile = AccessibilityProfile.STROLLER
                break

        # Extract origin/destination. In production, this would use NER.
        # For prototype: simple pattern matching for "from X to Y" or
        # "X → Y" patterns. Supports both English and Chinese place names.
        origin, destination = self._extract_locations(text_lower)

        # Detect additional preferences
        avoid_outdoor = any(kw in text_lower for kw in [
            "raining", "rain", "typhoon", "下雨", "颱風", "台风",
            "outdoor", "戶外", "户外",
        ])

        prefer_cheapest = any(kw in text_lower for kw in [
            "cheapest", "cheap", "便宜", "平", "save money",
        ])

        return UserQuery(
            raw_text=raw_text,
            origin=origin,
            destination=destination,
            accessibility_profile=profile,
            avoid_outdoor=avoid_outdoor,
            prefer_cheapest=prefer_cheapest,
            session_id=session_id,
        )

    def _extract_locations(self, text: str) -> tuple[str, str]:
        """Extract origin and destination from query text.

        Simple pattern-based extraction. In production, use a geocoding MCP tool
        or NER model for robust extraction of Cantonese/English place names.
        """
        origin = "unknown"
        destination = "unknown"

        # Pattern: "from X to Y"
        import re

        from_to = re.search(r"from\s+(.+?)\s+to\s+(.+)", text)
        if from_to:
            origin = from_to.group(1).strip()
            destination = from_to.group(2).strip()
            return origin, destination

        # Pattern: "X to Y"
        to_pattern = re.search(r"(.+?)\s+to\s+(.+)", text)
        if to_pattern:
            origin = to_pattern.group(1).strip()
            destination = to_pattern.group(2).strip()
            return origin, destination

        # Pattern: Chinese "由X去Y"
        cn_pattern = re.search(r"由(.+?)[去到](.+)", text)
        if cn_pattern:
            origin = cn_pattern.group(1).strip()
            destination = cn_pattern.group(2).strip()
            return origin, destination

        return origin, destination

    # ------------------------------------------------------------------
    # Step 2: Orchestrate — dispatch to sub-agents and collect results.
    # This is the core Agent loop (Day 1 Section 1.2).
    # ------------------------------------------------------------------

    async def plan_route(self, query: UserQuery) -> AgentResponse:
        """Execute the full agent pipeline for a user query.

        Pipeline:
        1. Route Planner → generate candidate routes
        2. Accessibility Filter → score/filter each route by profile
        3. Alert Monitor → check real-time disruptions
        4. Synthesize → produce natural language response
        """
        response = AgentResponse(session_id=query.session_id)
        response.tool_calls_made = []

        # --- Phase 1: Route Planning ---
        logger.info(f"Planning routes: {query.origin} → {query.destination}")
        response.tool_calls_made.append("route_planner.search")
        routes = await self.route_planner.find_routes(
            origin=query.origin,
            destination=query.destination,
            max_options=self.config.max_route_options,
        )
        logger.info(f"Found {len(routes)} candidate routes")

        # --- Phase 2: Accessibility Filtering ---
        logger.info(f"Filtering routes for profile: {query.accessibility_profile.value}")
        response.tool_calls_made.append("accessibility_filter.evaluate")
        filter_results = []
        accessible_routes = []

        for route in routes:
            result = await self.accessibility_filter.evaluate_route(
                route=route,
                profile=query.accessibility_profile,
            )
            filter_results.append(result)
            if result.is_accessible:
                accessible_routes.append(route)
            else:
                logger.info(
                    f"Route {route.summary} filtered out: "
                    f"{[f.reason for f in result.failures]}"
                )

        # If all routes filtered out, include the least-bad option with warnings
        if not accessible_routes and routes:
            logger.warning("No fully accessible routes found; returning best effort")
            # Sort by number of failures (fewest = least bad)
            filter_results.sort(key=lambda r: len(r.failures))
            least_bad_idx = filter_results[0].route_index
            if least_bad_idx < len(routes):
                accessible_routes = [routes[least_bad_idx]]
                filter_results[0].warnings.append(
                    "No fully accessible route found. This is the best available option."
                )

        response.routes = accessible_routes
        response.filter_results = filter_results

        # --- Phase 3: Alert Monitoring ---
        logger.info("Checking real-time alerts")
        response.tool_calls_made.append("alert_monitor.check")
        if accessible_routes:
            response.alerts = await self.alert_monitor.check_alerts(
                routes=accessible_routes,
                weather_sensitive=query.avoid_outdoor,
            )

        # --- Phase 4: Synthesize Response ---
        response.natural_response = await self._synthesize_response(
            query=query,
            routes=accessible_routes,
            filter_results=filter_results,
            alerts=response.alerts,
        )

        return response

    # ------------------------------------------------------------------
    # Step 3: Synthesize — produce the natural language response.
    # Uses the HEAVY model when available, falls back to template.
    # ------------------------------------------------------------------

    async def _synthesize_response(
        self,
        query: UserQuery,
        routes: list[RouteOption],
        filter_results: list[FilterResult],
        alerts: list[Alert],
    ) -> str:
        """Synthesize the final user-facing response.

        Tries LLM-based synthesis first (more natural, empathetic).
        Falls back to template when no LLM API key is configured.
        """
        # If an LLM API key is set, use it for richer responses
        if self.llm.config.provider.value != "mock":
            return await self._synthesize_with_llm(
                query, routes, filter_results, alerts
            )
        # Otherwise use the deterministic template (shift intelligence left)
        return self._synthesize_with_template(
            query, routes, filter_results, alerts
        )

    def _synthesize_with_template(
        self,
        query: UserQuery,
        routes: list[RouteOption],
        filter_results: list[FilterResult],
        alerts: list[Alert],
    ) -> str:
        """Template-based response synthesis (no LLM required).

        Deterministic and fast. Used when no API key is set or in eval mode.
        """
        profile_label = {
            AccessibilityProfile.WHEELCHAIR: "wheelchair accessible",
            AccessibilityProfile.ELDERLY: "elderly-friendly",
            AccessibilityProfile.VISUALLY_IMPAIRED: "visually impaired friendly",
            AccessibilityProfile.STROLLER: "stroller-friendly",
            AccessibilityProfile.GENERAL: "general",
        }[query.accessibility_profile]

        parts = [
            f"I've planned a {profile_label} route from "
            f"**{query.origin}** to **{query.destination}**.\n",
        ]

        if not routes:
            parts.append(
                "❌ Unfortunately, I could not find any fully accessible route "
                "matching your requirements. Here are the issues I found:\n"
            )
            for fr in filter_results:
                for failure in fr.failures:
                    parts.append(f"  • {failure.segment}: {failure.reason}\n")
            parts.append(
                "\nYou may want to consider a point-to-point accessible transport "
                "service (e.g., Rehabus) or seek assistance from station staff.\n"
            )
            return "".join(parts)

        # List routes
        for i, route in enumerate(routes, 1):
            emoji = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, "→")
            parts.append(
                f"{emoji} **Option {i}:** {route.summary}\n"
                f"   Total time: ~{route.total_time_min} min | "
                f"Interchanges: {route.interchange_count}\n\n"
            )

            for seg in route.segments:
                access_icon = "♿" if seg.is_accessible else "⚠️"
                parts.append(
                    f"   {access_icon} {seg.mode}: {seg.from_stop} → {seg.to_stop}\n"
                    f"      ({seg.duration_min} min, {seg.instructions})\n"
                )
            parts.append("\n")

        # Add alerts
        if alerts:
            parts.append("⚠️ **Active Alerts:**\n")
            for alert in alerts:
                parts.append(f"  • [{alert.severity.value.upper()}] {alert.message}\n")
            parts.append("\n")

        # Add accessibility note
        if query.accessibility_profile == AccessibilityProfile.WHEELCHAIR:
            parts.append(
                "♿ All recommended routes are step-free. Look for the wheelchair "
                "symbol at MTR wide gates and low-floor bus boarding points.\n"
            )
        elif query.accessibility_profile == AccessibilityProfile.ELDERLY:
            parts.append(
                "👴 All routes minimise walking and prefer lifts over escalators. "
                "Take your time — there's no rush.\n"
            )

        return "".join(parts)

    async def _synthesize_with_llm(
        self,
        query: UserQuery,
        routes: list[RouteOption],
        filter_results: list[FilterResult],
        alerts: list[Alert],
    ) -> str:
        """LLM-based response synthesis.

        Uses the HEAVY model to produce a natural, empathetic, and context-aware
        response. The structured data is provided as context; the LLM handles
        natural language generation.
        """

        # Build structured context for the LLM
        route_data = []
        for i, route in enumerate(routes):
            segments_data = []
            for seg in route.segments:
                segments_data.append(
                    f"    {seg.mode}: {seg.from_stop} → {seg.to_stop} "
                    f"({seg.duration_min} min, {'accessible' if seg.is_accessible else 'NOT accessible'})"
                    f"\n      {seg.instructions}"
                )
            route_data.append(
                f"Option {i + 1}: {route.summary}\n"
                f"  Total: {route.total_time_min} min | "
                f"Interchanges: {route.interchange_count}\n"
                f"  Segments:\n{''.join(segments_data)}"
            )

        alert_data = "\n".join(
            f"  [{a.severity.value.upper()}] {a.message}" for a in alerts
        ) if alerts else "  None"

        filter_data = "\n".join(
            f"  Route {fr.route_index}: {'PASS' if fr.is_accessible else 'FAIL'} "
            f"(score: {fr.accessibility_score:.0%})"
            + (f"\n    Failures: {', '.join(f.reason for f in fr.failures)}"
               if fr.failures else "")
            for fr in filter_results
        )

        user_prompt = f"""Plan an accessible transit route based on the following data.

USER QUERY: {query.raw_text}
PROFILE: {query.accessibility_profile.value}
ORIGIN: {query.origin}
DESTINATION: {query.destination}

ROUTE OPTIONS:
{''.join(route_data) if route_data else 'No routes found.'}

FILTER RESULTS:
{filter_data}

ACTIVE ALERTS:
{alert_data}

Please provide a clear, empathetic response that:
1. Summarizes the best route option(s) for this user's needs
2. Mentions the total journey time and number of interchanges
3. Lists any accessibility concerns or alerts
4. Uses emojis for readability (♿ 🥇 👴 🌧️ ⚠️)
5. Includes practical tips specific to the user's accessibility profile
6. Is written in a supportive, helpful tone

Keep the response concise but thorough. If no route is fully accessible,
explain why and suggest alternatives like Rehabus or station staff assistance."""

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": user_prompt}],
                system_prompt=SYSTEM_PROMPT,
                tier="heavy",
            )
            return response
        except Exception as e:
            logger.error(f"LLM synthesis failed, using template: {e}")
            return self._synthesize_with_template(
                query, routes, filter_results, alerts
            )

    # ------------------------------------------------------------------
    # Session memory management (Day 1: Memory component)
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Clean up MCP connections gracefully."""
        await self.mcp_pool.stop_all()

    def start_session(self, session_id: str) -> None:
        """Initialize a new session for multi-turn conversation."""
        self._session_history[session_id] = []

    def remember(self, session_id: str, query: UserQuery, response: AgentResponse) -> None:
        """Store a query-response pair in session memory."""
        if session_id not in self._session_history:
            self._session_history[session_id] = []
        self._session_history[session_id].append({
            "query": query,
            "response": response,
        })


# ---------------------------------------------------------------------------
# CLI entry point for interactive use
# ---------------------------------------------------------------------------

async def main():
    """Interactive CLI for the HK Accessible Transit Navigator."""
    import asyncio

    orchestrator = OrchestratorAgent()

    print("=" * 60)
    print("HK Accessible Transit Navigator ♿")
    print("Multi-agent accessible route planner for Hong Kong")
    print("=" * 60)
    print()
    print("Describe your journey, e.g.:")
    print('  "I need to go from Tai Po to Central. I use a wheelchair."')
    print('  "從大埔去中環，我用輪椅"')
    print()
    print("Type 'quit' to exit, 'help' for more examples.")
    print()

    session_id = "cli-session-1"
    orchestrator.start_session(session_id)

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break
        if user_input.lower() == "help":
            print("Examples:")
            print("  from Sha Tin to Admiralty, wheelchair")
            print("  Diamond Hill to Tuen Mun, elderly, avoid outdoor")
            print("  Central to Kennedy Town, stroller")
            continue

        query = orchestrator.parse_query(user_input, session_id=session_id)
        print(f"  Profile: {query.accessibility_profile.value}")
        print(f"  Route: {query.origin} → {query.destination}")
        print()

        response = await orchestrator.plan_route(query)
        print(response.natural_response)
        print("-" * 60)

        orchestrator.remember(session_id, query, response)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
