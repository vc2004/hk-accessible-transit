"""
Tests for the Orchestrator Agent.

Verifies intent parsing, accessibility profile classification,
and the core orchestration pipeline.
"""

import pytest

from agent.config import AccessibilityProfile
from agent.orchestrator import OrchestratorAgent, UserQuery


@pytest.fixture
def orchestrator():
    """Create an orchestrator for testing."""
    agent = OrchestratorAgent()
    agent.config.eval_mode = True
    return agent


class TestQueryParsing:
    """Test natural language query parsing and profile classification."""

    def test_parse_wheelchair_english(self, orchestrator):
        query = orchestrator.parse_query(
            "I need to go from Tai Po to Central, I use a wheelchair"
        )
        assert query.accessibility_profile == AccessibilityProfile.WHEELCHAIR
        assert "tai po" in query.origin.lower()
        assert "central" in query.destination.lower()

    def test_parse_wheelchair_chinese(self, orchestrator):
        query = orchestrator.parse_query(
            "由大埔去中環，我用輪椅"
        )
        assert query.accessibility_profile == AccessibilityProfile.WHEELCHAIR

    def test_parse_elderly(self, orchestrator):
        query = orchestrator.parse_query(
            "My elderly father, 75 years old, needs to go from Sha Tin to Admiralty"
        )
        assert query.accessibility_profile == AccessibilityProfile.ELDERLY

    def test_parse_stroller(self, orchestrator):
        query = orchestrator.parse_query(
            "Going from Central to Kennedy Town with a baby stroller"
        )
        assert query.accessibility_profile == AccessibilityProfile.STROLLER

    def test_parse_visually_impaired(self, orchestrator):
        query = orchestrator.parse_query(
            "I'm blind, how do I get from Central to Admiralty?"
        )
        assert query.accessibility_profile == AccessibilityProfile.VISUALLY_IMPAIRED

    def test_parse_general(self, orchestrator):
        query = orchestrator.parse_query(
            "What's the fastest way from Central to Tsim Sha Tsui?"
        )
        assert query.accessibility_profile == AccessibilityProfile.GENERAL

    def test_parse_avoid_outdoor(self, orchestrator):
        query = orchestrator.parse_query(
            "from Sha Tin to Admiralty, wheelchair, it's raining"
        )
        assert query.avoid_outdoor is True

    def test_parse_prefer_cheapest(self, orchestrator):
        query = orchestrator.parse_query(
            "Cheapest way from Tuen Mun to Central, wheelchair"
        )
        assert query.prefer_cheapest is True

    def test_parse_unknown_origin_destination(self, orchestrator):
        """Gracefully handle queries without clear locations."""
        query = orchestrator.parse_query(
            "I need help with transport, I use a wheelchair"
        )
        assert query.accessibility_profile == AccessibilityProfile.WHEELCHAIR
        assert query.origin == "unknown"
        assert query.destination == "unknown"


class TestOrchestration:
    """Test the core orchestration pipeline."""

    @pytest.mark.asyncio
    async def test_plan_route_wheelchair(self, orchestrator):
        """End-to-end wheelchair route planning."""
        query = UserQuery(
            raw_text="Tai Po Market to Central, wheelchair",
            origin="Tai Po Market",
            destination="Central",
            accessibility_profile=AccessibilityProfile.WHEELCHAIR,
        )
        response = await orchestrator.plan_route(query)
        assert response.routes is not None
        # At minimum, the agent should return routes or a clear explanation
        assert len(response.routes) > 0 or len(response.natural_response) > 50

    @pytest.mark.asyncio
    async def test_plan_route_no_result(self, orchestrator):
        """Graceful handling when no accessible route exists."""
        query = UserQuery(
            raw_text="Prince Edward to Sham Shui Po, wheelchair",
            origin="Prince Edward",
            destination="Sham Shui Po",
            accessibility_profile=AccessibilityProfile.WHEELCHAIR,
        )
        response = await orchestrator.plan_route(query)
        # Should not crash — should return some guidance
        assert response.natural_response is not None
        assert len(response.natural_response) > 0

    @pytest.mark.asyncio
    async def test_plan_route_elderly(self, orchestrator):
        """Elderly route planning with extra constraints."""
        query = UserQuery(
            raw_text="Sha Tin to Central, elderly",
            origin="Sha Tin",
            destination="Central",
            accessibility_profile=AccessibilityProfile.ELDERLY,
        )
        response = await orchestrator.plan_route(query)
        assert response.routes is not None
        assert len(response.natural_response) > 0

    @pytest.mark.asyncio
    async def test_plan_route_tool_calls_tracked(self, orchestrator):
        """Verify tool call tracking for trajectory evaluation."""
        query = UserQuery(
            raw_text="Tai Po to Central, wheelchair",
            origin="Tai Po",
            destination="Central",
            accessibility_profile=AccessibilityProfile.WHEELCHAIR,
        )
        response = await orchestrator.plan_route(query)
        # Should have called at least route_planner and accessibility_filter
        assert len(response.tool_calls_made) >= 2
        assert "route_planner.search" in response.tool_calls_made
        assert "accessibility_filter.evaluate" in response.tool_calls_made


class TestSessionMemory:
    """Test session memory management."""

    def test_start_session(self, orchestrator):
        orchestrator.start_session("test-session-1")
        assert "test-session-1" in orchestrator._session_history

    def test_remember(self, orchestrator):
        orchestrator.start_session("test-session-2")
        query = UserQuery(
            raw_text="test", origin="A", destination="B",
            session_id="test-session-2",
        )
        from agent.orchestrator import AgentResponse
        response = AgentResponse(session_id="test-session-2")
        orchestrator.remember("test-session-2", query, response)
        assert len(orchestrator._session_history["test-session-2"]) == 1
