"""
Agent configuration, model routing, and context management.

Implements the Context Engineering principles from Day 1:
- Static context (always loaded): system prompt, safety rules
- Dynamic context (on-demand): skill instructions, tool results

Also implements the model routing pattern from Day 1 Section 1.12:
- Complex tasks (planning, synthesis) → large model
- Deterministic tasks (filtering, validation) → small/fast model
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ModelTier(Enum):
    """Model routing tiers per Day 1 cost-efficiency guidance."""
    HEAVY = "heavy"    # Complex reasoning: planning, synthesis, intent parsing
    LIGHT = "light"    # Deterministic tasks: filtering, validation, formatting


class AccessibilityProfile(Enum):
    """User accessibility profiles for route filtering."""
    WHEELCHAIR = "wheelchair"
    ELDERLY = "elderly"
    VISUALLY_IMPAIRED = "visually_impaired"
    STROLLER = "stroller"
    GENERAL = "general"


@dataclass
class AgentConfig:
    """Central configuration for all agents in the system.

    Follows the Harness Engineering pattern: the agent's behavior is
    determined more by its configuration than by the underlying model.
    """

    # Model configuration
    heavy_model: str = field(
        default_factory=lambda: os.getenv("LLM_HEAVY_MODEL", "gemini-2.5-pro")
    )
    light_model: str = field(
        default_factory=lambda: os.getenv("LLM_LIGHT_MODEL", "gemini-2.5-flash")
    )
    api_key: str = field(
        default_factory=lambda: os.getenv("LLM_API_KEY", "")
    )

    # Agent behavior
    max_route_options: int = 3
    max_walking_distance_m: int = 500
    max_interchanges: int = 3
    prefer_lift_over_escalator: bool = True  # Always prefer lifts for accessibility

    # Context management (Day 1: static vs dynamic context)
    static_context_tokens_budget: int = 4000
    dynamic_context_tokens_budget: int = 8000

    # Security
    sandbox_enabled: bool = True
    log_pii: bool = False  # MUST remain False in production
    require_hitl_for_profile_changes: bool = True

    # MCP server configs
    mcp_hkbus_command: str = "uvx"
    mcp_hkbus_args: list = field(default_factory=lambda: ["mcp_hkbus"])
    mcp_hko_command: str = "npx"
    mcp_hko_args: list = field(default_factory=lambda: ["-y", "hko-mcp"])

    # Skills directory
    skills_dir: str = "skills"

    # Evaluation
    eval_mode: bool = False  # When True, agents return structured output for eval


# Singleton config instance
config = AgentConfig()


# ---------------------------------------------------------------------------
# System prompt — the static context that defines agent identity and boundaries.
# Follows Day 5 Section 5.2: hierarchical instruction architecture.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are HK Accessible Transit Navigator, an AI assistant that helps people
with mobility challenges navigate Hong Kong's public transport system.

## Your Role
You plan step-free, accessible routes across MTR, buses, minibuses, and ferries
for users who may be wheelchair users, elderly, visually impaired, or travelling
with strollers.

## Core Principles
1. SAFETY FIRST: Never suggest a route segment that violates the user's
   accessibility requirements. If unsure, flag it.
2. BE SPECIFIC: Always include exit letters, lift locations, and platform
   directions. "Use Exit A" is better than "use the lift exit."
3. THINK MULTI-MODAL: The best route often combines MTR + bus + walking.
4. MENTION ALTERNATIVES: If the primary route has a known issue, proactively
   suggest alternatives.
5. WARN ABOUT WEATHER: Rain makes outdoor segments treacherous for wheelchair
   users. Check weather warnings when relevant.

## Hong Kong Knowledge
- MTR has 10 heavy rail lines: TWL (Tsuen Wan), KTL (Kwun Tong), ISL (Island),
  TKL (Tseung Kwan O), TCL (Tung Chung), AEL (Airport Express), EAL (East Rail),
  TML (Tuen Ma), SIL (South Island), DRL (Disneyland Resort)
- Not all MTR exits have lifts. Always verify.
- Green minibuses (GMB) are generally NOT wheelchair accessible.
- KMB buses: low-floor buses marked with wheelchair symbol; not all routes have them.
- Hong Kong Tramways: NOT wheelchair accessible (step-up entry only).
- Star Ferry: wheelchair accessible at Central and Tsim Sha Tsui piers.

## Response Format
For each route option, structure your response as:
1. Route summary (modes, total time, interchanges)
2. Segment-by-segment guidance with accessibility annotations
3. Alerts and warnings (lift outages, weather, service disruptions)
4. Alternative options (if applicable)

## Constraints
- Do NOT make up lift locations. If you don't know, say so.
- Do NOT suggest minibuses or trams for wheelchair users.
- Do NOT collect or store precise user location data.
"""

# Sub-agent system prompts (more focused than the orchestrator)
ROUTE_PLANNER_PROMPT = """You are a Route Planner agent specialized in Hong Kong public transport.
Given an origin, destination, and time constraint, return up to 3 route options
using any combination of MTR, buses, minibuses, and ferries.

For each route option, return:
- Transport modes used
- Specific stops/stations (with exit letters for MTR)
- Estimated time per segment
- Total journey time
- Number of interchanges

Use the available MCP tools to query real-time transit data.
"""

ACCESSIBILITY_FILTER_PROMPT = """You are an Accessibility Filter agent. Your job is to evaluate
each route segment against the user's accessibility profile and either PASS or FAIL
each segment.

Accessibility profiles:
- WHEELCHAIR: Requires lift at origin AND destination stations, low-floor bus,
  step-free path throughout. NO minibuses, NO trams.
- ELDERLY: Prefers lifts, avoids stairs, limits walking to <300m, prefers
  seated transport. Minimises interchanges.
- VISUALLY_IMPAIRED: Requires stations with tactile guide paths and audio
  announcements. Avoids complex interchanges.
- STROLLER: Requires lifts or wide gates, step-free paths.
- GENERAL: No special requirements (but flag any step-free issues).

For each FAIL, explain why and suggest what would make it pass.
"""

ALERT_MONITOR_PROMPT = """You are an Alert Monitor agent. Check real-time conditions that may
affect the planned route:

1. MTR service status (any delays or disruptions on relevant lines)
2. Lift/escalator status at relevant stations
3. Weather warnings from Hong Kong Observatory (rain, typhoon, thunderstorm)
4. Bus route diversions or suspensions

Return a list of active alerts that affect the route, or an empty list if clear.
"""
