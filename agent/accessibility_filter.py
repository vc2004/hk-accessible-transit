"""
Accessibility Filter Agent — evaluates routes against accessibility profiles.

Implements the rules engine that determines whether each route segment is
accessible for a given user profile. This is the most safety-critical agent
in the system: a false PASS on a wheelchair route could strand a user.

Design principle (Day 4: Security Pillar 4):
    The filter agent is deterministic where possible and uses an LLM
    only for edge-case judgment. "Shift intelligence left" — rules are
    encoded as testable logic, not prompt engineering.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

from .config import AccessibilityProfile, AgentConfig, config
from .route_planner import RouteOption, RouteSegment

logger = logging.getLogger(__name__)


class FilterVerdict(Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"  # Pass with caveats


@dataclass
class SegmentFailure:
    """Reason a route segment failed accessibility check."""
    segment_index: int
    segment: str  # Human-readable segment description
    reason: str
    severity: str = "error"  # "error" (hard block) or "warning" (advisory)


@dataclass
class FilterResult:
    """Result of filtering one route against an accessibility profile."""
    route_index: int
    profile: AccessibilityProfile
    is_accessible: bool
    failures: list[SegmentFailure] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Scoring for LLM-as-Judge evaluation
    accessibility_score: float = 1.0  # 0.0 (worst) to 1.0 (best)
    score_explanation: str = ""


class AccessibilityFilterAgent:
    """Filters route options against accessibility requirements.

    Rules are based on:
    - MTR "Step-free Access" official guide
    - Transport Department accessibility standards
    - Lived experience of Hong Kong wheelchair users (community-sourced)

    All rules are deterministic — no LLM involved in safety-critical filtering.
    """

    # Transport modes that are NEVER wheelchair accessible in Hong Kong
    _WHEELCHAIR_BLOCKED_MODES = {"GMB", "TRAM", "MINIBUS_RED"}

    # Modes that require verification for wheelchair access
    _WHEELCHAIR_CONDITIONAL_MODES = {"BUS_KMB", "BUS_CTB", "BUS_LWB", "BUS_NLB", "FERRY"}

    # Walking distance limits per profile (in metres)
    _MAX_WALKING_DISTANCE: dict[AccessibilityProfile, int] = {
        AccessibilityProfile.WHEELCHAIR: 300,
        AccessibilityProfile.ELDERLY: 200,
        AccessibilityProfile.VISUALLY_IMPAIRED: 400,
        AccessibilityProfile.STROLLER: 300,
        AccessibilityProfile.GENERAL: 500,
    }

    # Maximum interchanges per profile
    _MAX_INTERCHANGES: dict[AccessibilityProfile, int] = {
        AccessibilityProfile.WHEELCHAIR: 2,
        AccessibilityProfile.ELDERLY: 1,
        AccessibilityProfile.VISUALLY_IMPAIRED: 1,
        AccessibilityProfile.STROLLER: 2,
        AccessibilityProfile.GENERAL: 3,
    }

    def __init__(self, cfg: AgentConfig = config):
        self.config = cfg

    # ------------------------------------------------------------------
    # Main API: evaluate a route against an accessibility profile
    # ------------------------------------------------------------------

    async def evaluate_route(
        self,
        route: RouteOption,
        profile: AccessibilityProfile,
    ) -> FilterResult:
        """Evaluate a complete route option against an accessibility profile.

        Each segment is checked individually. The route passes only if ALL
        segments pass. Failures are collected and returned for transparency.
        """
        result = FilterResult(
            route_index=0,
            profile=profile,
            is_accessible=True,
        )

        # Check 1: Interchange count
        if route.interchange_count > self._MAX_INTERCHANGES[profile]:
            result.warnings.append(
                f"Route has {route.interchange_count} interchanges "
                f"(max recommended: {self._MAX_INTERCHANGES[profile]}). "
                f"This may be difficult for {profile.value} users."
            )

        # Check 2: Each segment
        for i, segment in enumerate(route.segments):
            failures = self._check_segment(segment, profile, i)
            result.failures.extend(failures)

        # Check 3: Holistic checks
        if route.total_time_min > 90 and profile in (
            AccessibilityProfile.ELDERLY,
            AccessibilityProfile.WHEELCHAIR,
        ):
            result.warnings.append(
                f"Journey exceeds 90 minutes ({route.total_time_min} min). "
                f"Consider breaking the journey or arranging assisted transport."
            )

        # Determine overall accessibility
        hard_failures = [f for f in result.failures if f.severity == "error"]
        result.is_accessible = len(hard_failures) == 0

        # Calculate accessibility score (for evaluation)
        total_checks = max(len(route.segments) * 2, 1)  # ~2 checks per segment
        result.accessibility_score = max(
            0.0, 1.0 - (len(hard_failures) / total_checks)
        )

        return result

    # ------------------------------------------------------------------
    # Segment-level checks
    # ------------------------------------------------------------------

    def _check_segment(
        self,
        segment: RouteSegment,
        profile: AccessibilityProfile,
        index: int,
    ) -> list[SegmentFailure]:
        """Run all accessibility checks on a single route segment."""
        failures: list[SegmentFailure] = []

        seg_desc = f"{segment.mode}: {segment.from_stop} → {segment.to_stop}"

        # --- Wheelchair checks ---
        if profile == AccessibilityProfile.WHEELCHAIR:
            failures.extend(self._check_wheelchair(segment, index, seg_desc))

        # --- Elderly checks ---
        if profile == AccessibilityProfile.ELDERLY:
            failures.extend(self._check_elderly(segment, index, seg_desc))

        # --- Visually impaired checks ---
        if profile == AccessibilityProfile.VISUALLY_IMPAIRED:
            failures.extend(self._check_visually_impaired(segment, index, seg_desc))

        # --- Stroller checks ---
        if profile == AccessibilityProfile.STROLLER:
            failures.extend(self._check_stroller(segment, index, seg_desc))

        # --- Walking distance check (all profiles) ---
        if segment.mode == "WALK":
            max_dist = self._MAX_WALKING_DISTANCE[profile]
            # Walking segments typically encode distance in the duration
            if segment.duration_min > max_dist / 80:  # ~80m/min walking speed
                failures.append(SegmentFailure(
                    segment_index=index,
                    segment=seg_desc,
                    reason=(
                        f"Walking segment is ~{segment.duration_min * 80}m, "
                        f"exceeds {max_dist}m limit for {profile.value} users"
                    ),
                    severity="warning" if segment.duration_min * 80 < max_dist * 1.3 else "error",
                ))

        return failures

    def _check_wheelchair(
        self, segment: RouteSegment, index: int, desc: str
    ) -> list[SegmentFailure]:
        """Hard rules for wheelchair accessibility."""
        failures: list[SegmentFailure] = []

        # Blocked modes — hard fail
        for mode_prefix in self._WHEELCHAIR_BLOCKED_MODES:
            if segment.mode.upper().startswith(mode_prefix):
                failures.append(SegmentFailure(
                    segment_index=index,
                    segment=desc,
                    reason=f"{segment.mode} is not wheelchair accessible in Hong Kong",
                    severity="error",
                ))
                return failures

        # Tram — always blocked for wheelchairs
        if "TRAM" in segment.mode.upper():
            failures.append(SegmentFailure(
                segment_index=index,
                segment=desc,
                reason="Hong Kong Tramways has step-up entry only — not wheelchair accessible",
                severity="error",
            ))

        # Bus — must be low-floor
        if any(mode in segment.mode.upper() for mode in ("KMB", "CTB", "BUS", "LWB", "NLB")):
            if not segment.is_accessible:
                failures.append(SegmentFailure(
                    segment_index=index,
                    segment=desc,
                    reason=(
                        f"{segment.mode} route {segment.route_code}: verify low-floor "
                        f"bus availability on this route. Not all departures are wheelchair "
                        f"accessible."
                    ),
                    severity="error" if not segment.is_accessible else "warning",
                ))

        # MTR — must have lift at both stations
        if segment.mode == "MTR":
            if not segment.is_accessible:
                failures.append(SegmentFailure(
                    segment_index=index,
                    segment=desc,
                    reason=(
                        f"MTR segment: verify lift availability at {segment.from_stop} "
                        f"and {segment.to_stop}. Not all MTR exits have lifts."
                    ),
                    severity="error",
                ))

        return failures

    def _check_elderly(
        self, segment: RouteSegment, index: int, desc: str
    ) -> list[SegmentFailure]:
        """Rules for elderly-friendly routes."""
        failures: list[SegmentFailure] = []

        # Walking segments over 200m are flagged
        if segment.mode == "WALK" and segment.duration_min > 3:
            failures.append(SegmentFailure(
                segment_index=index,
                segment=desc,
                reason=f"Walking segment too long for elderly users (~{segment.duration_min * 80}m)",
                severity="warning",
            ))

        # Prefer lifts — flag escalator-only segments
        if segment.mode == "MTR" and "escalator" in segment.instructions.lower():
            if "lift" not in segment.instructions.lower():
                failures.append(SegmentFailure(
                    segment_index=index,
                    segment=desc,
                    reason="Segment relies on escalator — verify lift alternative is available",
                    severity="warning",
                ))

        return failures

    def _check_visually_impaired(
        self, segment: RouteSegment, index: int, desc: str
    ) -> list[SegmentFailure]:
        """Rules for visually impaired accessibility."""
        failures: list[SegmentFailure] = []

        # Complex interchanges are flagged
        if segment.mode == "MTR" and segment.from_stop != segment.to_stop:
            complex_stations = {"Admiralty", "Central", "Mong Kok", "Kowloon Tong", "Nam Cheong"}
            for station in complex_stations:
                if station.lower() in segment.from_stop.lower():
                    failures.append(SegmentFailure(
                        segment_index=index,
                        segment=desc,
                        reason=(
                            f"Interchange at {station} is complex. Tactile guide paths "
                            f"available but layout can be confusing. Allow extra time."
                        ),
                        severity="warning",
                    ))
                    break

        return failures

    def _check_stroller(
        self, segment: RouteSegment, index: int, desc: str
    ) -> list[SegmentFailure]:
        """Rules for stroller accessibility.

        Similar to wheelchair but slightly more permissive (strollers can
        use escalators in some cases, unlike wheelchairs).
        """
        failures: list[SegmentFailure] = []

        # Same blocked modes as wheelchair, but only for safety
        if "TRAM" in segment.mode.upper():
            failures.append(SegmentFailure(
                segment_index=index,
                segment=desc,
                reason="Trams are not stroller-friendly (step-up entry, narrow aisles)",
                severity="warning",  # Warning, not error — some parents manage
            ))

        if segment.mode == "MTR" and "lift" not in segment.instructions.lower():
            failures.append(SegmentFailure(
                segment_index=index,
                segment=desc,
                reason="No lift mentioned — strollers should use lifts where available",
                severity="warning",
            ))

        return failures

    # ------------------------------------------------------------------
    # Utility: check if two stations share the same line
    # ------------------------------------------------------------------

    @staticmethod
    def _same_line(station_a: str, station_b: str) -> bool:
        """Heuristic: check if two stations are likely on the same MTR line."""
        # In production, query the MTR route map via MCP
        # For prototype: known co-linear pairs
        same_line_pairs = {
            ("tai po market", "mong kok east"),
            ("tai po market", "sha tin"),
            ("sha tin", "admiralty"),
            ("tsim sha tsui", "central"),
            ("tuen mun", "tsuen wan west"),
            ("diamond hill", "kai tak"),
            ("central", "admiralty"),
            ("admiralty", "causeway bay"),
        }
        key = (station_a.lower().strip(), station_b.lower().strip())
        return key in same_line_pairs or tuple(reversed(key)) in same_line_pairs
