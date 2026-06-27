"""
Tests for the Accessibility Filter Agent.

Verifies that accessibility rules are correctly applied for each profile.
These tests are safety-critical — a false PASS could strand a wheelchair user.
"""

import pytest

from agent.accessibility_filter import (
    AccessibilityFilterAgent,
    AccessibilityProfile,
    FilterVerdict,
)
from agent.route_planner import RouteOption, RouteSegment


@pytest.fixture
def filter_agent():
    return AccessibilityFilterAgent()


def make_route(segments: list[tuple]) -> RouteOption:
    """Helper: create a RouteOption from (mode, from, to, accessible) tuples."""
    route = RouteOption()
    for mode, from_s, to_s, accessible in segments:
        route.segments.append(RouteSegment(
            mode=mode,
            from_stop=from_s,
            to_stop=to_s,
            route_code="TEST",
            duration_min=5,
            is_accessible=accessible,
            instructions="Test segment",
        ))
        route.total_time_min += 5
    route.interchange_count = max(0, len(segments) - 1)
    return route


class TestWheelchairFiltering:
    """Wheelchair accessibility rules — the strictest profile."""

    @pytest.mark.asyncio
    async def test_mtr_with_lifts_passes(self, filter_agent):
        route = make_route([
            ("MTR", "Tai Po Market", "Admiralty", True),
        ])
        result = await filter_agent.evaluate_route(route, AccessibilityProfile.WHEELCHAIR)
        assert result.is_accessible

    @pytest.mark.asyncio
    async def test_mtr_without_lifts_fails(self, filter_agent):
        route = make_route([
            ("MTR", "Prince Edward", "Mong Kok", False),
        ])
        result = await filter_agent.evaluate_route(route, AccessibilityProfile.WHEELCHAIR)
        assert not result.is_accessible
        assert len(result.failures) > 0
        assert any(
            "verify lift availability" in f.reason.lower()
            for f in result.failures
        )

    @pytest.mark.asyncio
    async def test_tram_blocked_for_wheelchair(self, filter_agent):
        route = make_route([
            ("TRAM", "Central", "Causeway Bay", True),
        ])
        result = await filter_agent.evaluate_route(route, AccessibilityProfile.WHEELCHAIR)
        assert not result.is_accessible
        assert any(
            "not wheelchair accessible" in f.reason.lower()
            for f in result.failures
        )

    @pytest.mark.asyncio
    async def test_minibus_blocked_for_wheelchair(self, filter_agent):
        route = make_route([
            ("GMB", "Kowloon Tong", "Lok Fu", True),
        ])
        result = await filter_agent.evaluate_route(route, AccessibilityProfile.WHEELCHAIR)
        assert not result.is_accessible
        assert any(
            "not wheelchair accessible" in f.reason.lower()
            for f in result.failures
        )

    @pytest.mark.asyncio
    async def test_interchange_limit_enforced(self, filter_agent):
        # 4 segments = 3 interchanges (over the 2-max limit for wheelchair)
        route = make_route([
            ("MTR", "A", "B", True),
            ("MTR", "B", "C", True),
            ("MTR", "C", "D", True),
            ("MTR", "D", "E", True),
        ])
        result = await filter_agent.evaluate_route(route, AccessibilityProfile.WHEELCHAIR)
        assert any(
            "interchange" in w.lower()
            for w in result.warnings
        )

    @pytest.mark.asyncio
    async def test_bus_low_floor_required(self, filter_agent):
        route = make_route([
            ("KMB", "Sha Tin", "Tsim Sha Tsui", False),  # Not low-floor
        ])
        result = await filter_agent.evaluate_route(route, AccessibilityProfile.WHEELCHAIR)
        assert not result.is_accessible

    @pytest.mark.asyncio
    async def test_ferry_accessible_passes(self, filter_agent):
        route = make_route([
            ("FERRY", "Central", "Tsim Sha Tsui", True),
        ])
        result = await filter_agent.evaluate_route(route, AccessibilityProfile.WHEELCHAIR)
        assert result.is_accessible


class TestElderlyFiltering:
    """Elderly-friendly route rules."""

    @pytest.mark.asyncio
    async def test_long_walking_flagged(self, filter_agent):
        route = make_route([
            ("WALK", "Bus Stop A", "MTR Station B", False),
        ])
        route.segments[0].duration_min = 10  # ~800m walk — too long for elderly
        result = await filter_agent.evaluate_route(route, AccessibilityProfile.ELDERLY)
        assert any(
            "walking" in f.reason.lower()
            for f in result.failures
        )

    @pytest.mark.asyncio
    async def test_short_mtr_route_passes(self, filter_agent):
        route = make_route([
            ("MTR", "Sha Tin", "Admiralty", True),
        ])
        result = await filter_agent.evaluate_route(route, AccessibilityProfile.ELDERLY)
        assert result.is_accessible


class TestVisuallyImpairedFiltering:
    """Visually impaired route rules."""

    @pytest.mark.asyncio
    async def test_complex_interchange_flagged(self, filter_agent):
        route = make_route([
            ("MTR", "Admiralty", "Central", True),
        ])
        result = await filter_agent.evaluate_route(route, AccessibilityProfile.VISUALLY_IMPAIRED)
        # Admiralty is flagged as complex for visually impaired users
        assert len(result.failures) > 0 or len(result.warnings) > 0


class TestStrollerFiltering:
    """Stroller-friendly route rules."""

    @pytest.mark.asyncio
    async def test_tram_warns_for_stroller(self, filter_agent):
        route = make_route([
            ("TRAM", "Central", "Causeway Bay", True),
        ])
        result = await filter_agent.evaluate_route(route, AccessibilityProfile.STROLLER)
        # Trams get a warning for strollers (not a hard block like wheelchairs)
        assert any(
            "tram" in f.reason.lower()
            for f in result.failures + [
                type('obj', (object,), {'reason': w})() for w in result.warnings
            ]
        )

    @pytest.mark.asyncio
    async def test_mtr_with_lift_passes(self, filter_agent):
        route = make_route([
            ("MTR", "Kennedy Town", "Central", True),
        ])
        route.segments[0].instructions = "Lift at Exit B"
        result = await filter_agent.evaluate_route(route, AccessibilityProfile.STROLLER)
        assert result.is_accessible


class TestMixedProfiles:
    """Edge cases across profiles."""

    @pytest.mark.asyncio
    async def test_general_passes_everything(self, filter_agent):
        """General profile should pass even non-accessible routes (just flags them)."""
        route = make_route([
            ("TRAM", "Central", "Happy Valley", False),
        ])
        result = await filter_agent.evaluate_route(route, AccessibilityProfile.GENERAL)
        assert result.is_accessible  # General profile has no hard blocks

    @pytest.mark.asyncio
    async def test_accessibility_score_calculated(self, filter_agent):
        route = make_route([
            ("MTR", "Tai Po Market", "Admiralty", True),
        ])
        result = await filter_agent.evaluate_route(route, AccessibilityProfile.WHEELCHAIR)
        assert 0.0 <= result.accessibility_score <= 1.0
