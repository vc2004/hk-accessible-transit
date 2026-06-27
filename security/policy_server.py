"""
Policy Server — enforces security policies on agent actions.

Implements the two-tier Policy Server from Day 5 Section 5.6:
    Structural Gating ("traffic lights"): Deterministic, role-based rules
    Semantic Gating ("intelligent referee"): LLM-based content inspection

Also implements the HITL (Human-in-the-Loop) protocol for high-risk operations
(Day 4 Pillar 5 and Day 5 Section 5.6).

Every tool call goes through:
    1. Structural Check → Is this tool allowed for this role/environment?
    2. Semantic Check → Are the parameters safe? (PII, injection, etc.)
    3. Execution → Both passed → proceed; otherwise return policy violation.
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class ToolRisk(Enum):
    """Risk classification for agent tools."""
    READ_ONLY = "read_only"        # Query transit data, check weather
    USER_PROFILE = "user_profile"  # Read/write user preferences
    LOCATION = "location"          # Involves precise user location
    EXTERNAL = "external"          # Sends data to external service
    HIGH_RISK = "high_risk"        # Modifies user data, sends notifications


class PolicyVerdict(Enum):
    ALLOW = "allow"
    DENY = "deny"
    HITL_REQUIRED = "hitl_required"  # Needs human approval


@dataclass
class PolicyRule:
    """A single policy rule for structural gating."""
    tool_name: str
    risk_level: ToolRisk
    allowed_roles: list[str] = field(default_factory=lambda: ["user", "admin"])
    allowed_environments: list[str] = field(default_factory=lambda: ["dev", "prod"])
    require_hitl: bool = False
    description: str = ""


@dataclass
class PolicyCheckResult:
    """Result of a policy check."""
    verdict: PolicyVerdict
    reason: str
    hitl_prompt: Optional[str] = None  # What to show the human if HITL required


class PolicyServer:
    """Two-tier policy enforcement for agent tool calls.

    Structural Gating: Fast, deterministic rules (no LLM).
    Semantic Gating: LLM-based content inspection for PII and injection.
    """

    # ------------------------------------------------------------------
    # Structural rules — deterministic, no LLM needed.
    # These define the "red lines" the agent can never cross.
    # ------------------------------------------------------------------

    STRUCTURAL_RULES: list[PolicyRule] = [
        PolicyRule(
            tool_name="send_email",
            risk_level=ToolRisk.EXTERNAL,
            allowed_roles=["admin"],
            require_hitl=True,
            description="Sending emails requires admin role + HITL approval",
        ),
        PolicyRule(
            tool_name="store_user_location",
            risk_level=ToolRisk.LOCATION,
            allowed_roles=["user", "admin"],
            allowed_environments=["dev"],
            description="Precise location storage allowed only in dev environment",
        ),
        PolicyRule(
            tool_name="query_transit_data",
            risk_level=ToolRisk.READ_ONLY,
            allowed_roles=["user", "admin"],
            allowed_environments=["dev", "prod"],
            description="Transit data queries are always allowed (read-only)",
        ),
        PolicyRule(
            tool_name="check_weather",
            risk_level=ToolRisk.READ_ONLY,
            allowed_roles=["user", "admin"],
            allowed_environments=["dev", "prod"],
            description="Weather queries are always allowed (read-only)",
        ),
        PolicyRule(
            tool_name="save_user_preferences",
            risk_level=ToolRisk.USER_PROFILE,
            allowed_roles=["user", "admin"],
            require_hitl=True,
            description="User preference changes require HITL confirmation",
        ),
        PolicyRule(
            tool_name="share_route",
            risk_level=ToolRisk.EXTERNAL,
            allowed_roles=["user", "admin"],
            require_hitl=True,
            description="Sharing route data externally requires HITL",
        ),
    ]

    # Risk level → default policy (for tools not explicitly listed)
    DEFAULT_POLICIES: dict[ToolRisk, PolicyRule] = {
        ToolRisk.READ_ONLY: PolicyRule(
            tool_name="*",
            risk_level=ToolRisk.READ_ONLY,
            description="Default: read-only tools are allowed",
        ),
        ToolRisk.LOCATION: PolicyRule(
            tool_name="*",
            risk_level=ToolRisk.LOCATION,
            require_hitl=True,
            description="Default: location tools require HITL",
        ),
        ToolRisk.EXTERNAL: PolicyRule(
            tool_name="*",
            risk_level=ToolRisk.EXTERNAL,
            require_hitl=True,
            description="Default: external tools require HITL",
        ),
    }

    def __init__(
        self,
        role: str = "user",
        environment: str = "dev",
        semantic_checker: Optional[Callable] = None,
    ):
        self.role = role
        self.environment = environment
        # Semantic checker is an optional LLM-based function for content inspection.
        # In production, this is a Gemini/Claude call. For the prototype, we use
        # deterministic regex patterns (shift intelligence left).
        self._semantic_checker = semantic_checker or self._default_semantic_check

    # ------------------------------------------------------------------
    # Structural Gating (Tier 1)
    # ------------------------------------------------------------------

    def structural_check(
        self,
        tool_name: str,
        risk_level: ToolRisk,
    ) -> PolicyCheckResult:
        """Deterministic check: is this tool allowed for this role + environment?

        Matches the tool against STRUCTURAL_RULES. If no explicit rule exists,
        falls back to the DEFAULT_POLICIES for the risk level.

        This is the "traffic light" — fast, binary, no LLM needed.
        """
        # Find the matching rule
        rule = None
        for r in self.STRUCTURAL_RULES:
            if r.tool_name == tool_name:
                rule = r
                break

        if rule is None:
            rule = self.DEFAULT_POLICIES.get(risk_level)
            if rule is None:
                return PolicyCheckResult(
                    verdict=PolicyVerdict.DENY,
                    reason=f"No policy defined for risk level {risk_level.value}",
                )

        # Check role
        if self.role not in rule.allowed_roles:
            return PolicyCheckResult(
                verdict=PolicyVerdict.DENY,
                reason=(
                    f"Tool '{tool_name}' requires role in {rule.allowed_roles}, "
                    f"but current role is '{self.role}'"
                ),
            )

        # Check environment
        if self.environment not in rule.allowed_environments:
            return PolicyCheckResult(
                verdict=PolicyVerdict.DENY,
                reason=(
                    f"Tool '{tool_name}' is not allowed in '{self.environment}' "
                    f"environment. Allowed: {rule.allowed_environments}"
                ),
            )

        # Check HITL requirement
        if rule.require_hitl:
            return PolicyCheckResult(
                verdict=PolicyVerdict.HITL_REQUIRED,
                reason=f"Tool '{tool_name}' requires human approval",
                hitl_prompt=(
                    f"🔐 **Human Approval Required**\n\n"
                    f"Tool: {tool_name}\n"
                    f"Risk Level: {risk_level.value}\n"
                    f"Description: {rule.description}\n\n"
                    f"Do you approve this action? (yes/no)"
                ),
            )

        return PolicyCheckResult(
            verdict=PolicyVerdict.ALLOW,
            reason="Structural check passed",
        )

    # ------------------------------------------------------------------
    # Semantic Gating (Tier 2)
    # ------------------------------------------------------------------

    async def semantic_check(
        self,
        tool_name: str,
        arguments: dict,
    ) -> PolicyCheckResult:
        """LLM-based content inspection for PII and injection patterns.

        Only runs if structural check passed. Examines the tool arguments
        for sensitive data that shouldn't be sent to external services.

        Implements Day 5 Section 5.6:
            "You can't catch every possible PII leak with regex."
            But we start with deterministic checks and escalate to LLM
            only when needed.
        """
        issues = self._default_semantic_check(tool_name, arguments)

        if issues:
            return PolicyCheckResult(
                verdict=PolicyVerdict.DENY,
                reason=f"Semantic check failed: {'; '.join(issues)}",
            )

        return PolicyCheckResult(
            verdict=PolicyVerdict.ALLOW,
            reason="Semantic check passed",
        )

    def _default_semantic_check(
        self, tool_name: str, arguments: dict
    ) -> list[str]:
        """Default semantic checker using deterministic patterns.

        In production, this is supplemented by an LLM call for nuanced
        PII detection. The deterministic layer catches the obvious cases
        without burning LLM tokens.
        """
        import re
        issues: list[str] = []

        args_str = json.dumps(arguments, ensure_ascii=False)

        # Check for HKID numbers
        if re.search(r'[A-Z]{1,2}\d{6,7}\(\d\)', args_str):
            issues.append("HKID number detected in tool arguments")

        # Check for raw email addresses
        if re.search(r'[\w\.-]+@[\w\.-]+\.\w+', args_str):
            issues.append("Email address detected in tool arguments")

        # Check for phone numbers
        if re.search(r'\d{4}[-\s]?\d{4}', args_str):
            issues.append("Phone number pattern detected in tool arguments")

        # Check for potential prompt injection patterns
        injection_patterns = [
            r'ignore\s+(all\s+)?(previous|above)\s+instructions',
            r'system\s*prompt\s*:',
            r'<\|im_start\|>',
            r'\[INST\]',
            r'<\s*script',
            r'DAN\s*mode',
        ]
        for pattern in injection_patterns:
            if re.search(pattern, args_str, re.IGNORECASE):
                issues.append(f"Potential prompt injection detected: {pattern}")

        return issues

    # ------------------------------------------------------------------
    # Full check pipeline
    # ------------------------------------------------------------------

    async def check(
        self,
        tool_name: str,
        risk_level: ToolRisk,
        arguments: dict,
    ) -> PolicyCheckResult:
        """Run the full policy check pipeline.

        1. Structural → role + environment + HITL
        2. Semantic → content inspection
        """
        # Step 1: Structural
        structural_result = self.structural_check(tool_name, risk_level)
        if structural_result.verdict != PolicyVerdict.ALLOW:
            return structural_result

        # Step 2: Semantic (only if structural passed)
        semantic_result = await self.semantic_check(tool_name, arguments)
        return semantic_result

    # ------------------------------------------------------------------
    # HITL simulation (for demo purposes)
    # ------------------------------------------------------------------

    def simulate_hitl_approval(self, hitl_prompt: str, user_response: str) -> bool:
        """Simulate a human-in-the-loop approval.

        In production, this would trigger a real approval workflow
        (push notification, email, IDE prompt). For the prototype,
        we accept a simple yes/no response.
        """
        return user_response.lower().strip() in (
            "yes", "y", "approve", "ok", "confirm", "是", "同意"
        )
