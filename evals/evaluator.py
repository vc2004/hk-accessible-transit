"""
Evaluation framework for the HK Accessible Transit Navigator.

Implements Evaluation-Driven Development (EDD) from Day 3 Section 3.4:
    "Write three JSON eval cases BEFORE drafting the SKILL.md."

Eval dimensions (Day 4 Section 4.9):
    1. Intent Satisfaction — did the agent build what the user wanted?
    2. Functional Correctness — does the route exist and is it correct?
    3. Accessibility Compliance — does the route respect the user's profile?
    4. Trajectory Quality — did the agent take reasonable steps?
    5. Response Quality — is the output clear, complete, and safe?

Metrics:
    - pass@1: single-run success rate
    - pass^k: k-run consistency (k=5 for Action-Allowed graduation)
    - LLM-as-Judge: rubric-based scoring by a peer model
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    """Result of evaluating one test case."""
    case_id: str
    passed: bool
    profile_matched: bool
    route_exists: bool
    constraints_met: list[str] = field(default_factory=list)
    constraints_failed: list[str] = field(default_factory=list)
    rubric_scores: dict[str, float] = field(default_factory=dict)
    trajectory_valid: bool = True
    error_message: str = ""
    latency_ms: float = 0.0


@dataclass
class EvalReport:
    """Aggregate evaluation report."""
    total_cases: int
    passed: int
    failed: int
    pass_rate: float
    results: list[EvalResult] = field(default_factory=list)
    by_profile: dict[str, dict] = field(default_factory=dict)
    trajectory_issues: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "EVALUATION REPORT",
            "=" * 60,
            f"Total cases: {self.total_cases}",
            f"Passed: {self.passed}",
            f"Failed: {self.failed}",
            f"Pass rate: {self.pass_rate:.1%}",
            "",
            "By Profile:",
        ]
        for profile, stats in self.by_profile.items():
            lines.append(
                f"  {profile}: {stats['passed']}/{stats['total']} "
                f"({stats['rate']:.0%})"
            )
        if self.trajectory_issues:
            lines.append("")
            lines.append("Trajectory Issues:")
            for issue in self.trajectory_issues:
                lines.append(f"  ⚠️ {issue}")
        return "\n".join(lines)


class Evaluator:
    """Runs the golden dataset against the agent and scores results.

    Implements the eval framework from Day 3 Section 3.4 and Day 4 Section 4.9.
    """

    def __init__(self, dataset_path: str = "evals/test_cases.json"):
        self.dataset_path = Path(dataset_path)
        self.test_cases = self._load_dataset()
        self._orchestrator = None  # Lazy import to avoid circular deps

    def _load_dataset(self) -> list[dict]:
        """Load the golden dataset."""
        with open(self.dataset_path) as f:
            data = json.load(f)
        return data["test_cases"]

    # ------------------------------------------------------------------
    # Main evaluation loop
    # ------------------------------------------------------------------

    async def evaluate(self, runs_per_case: int = 1) -> EvalReport:
        """Run all test cases and produce an evaluation report.

        Args:
            runs_per_case: Number of runs per case for pass^k metric.
                           Use 5 for Action-Allowed graduation assessment.
        """
        from agent.orchestrator import OrchestratorAgent

        self._orchestrator = OrchestratorAgent()
        self._orchestrator.config.eval_mode = True

        results: list[EvalResult] = []
        trajectory_issues: list[str] = []

        for case in self.test_cases:
            case_results = []
            for run in range(runs_per_case):
                start = time.time()
                result = await self._evaluate_one(case, run)
                result.latency_ms = (time.time() - start) * 1000
                case_results.append(result)

            # pass^k: must pass ALL runs
            best_result = case_results[0]  # Use first run for detailed metrics
            best_result.passed = all(r.passed for r in case_results)

            if not best_result.passed:
                # Collect trajectory issues from failed runs
                for r in case_results:
                    if not r.trajectory_valid:
                        trajectory_issues.append(
                            f"{case['case_id']}: invalid trajectory — {r.error_message}"
                        )

            results.append(best_result)
            logger.info(
                f"{case['case_id']}: {'PASS' if best_result.passed else 'FAIL'} "
                f"(pass^{runs_per_case}={sum(1 for r in case_results if r.passed)}/{runs_per_case})"
            )

        # Aggregate by profile
        by_profile = {}
        for case in self.test_cases:
            profile = case.get("profile", "general")
            if profile not in by_profile:
                by_profile[profile] = {"total": 0, "passed": 0}
            by_profile[profile]["total"] += 1

        for result in results:
            for case in self.test_cases:
                if case["case_id"] == result.case_id:
                    profile = case.get("profile", "general")
                    if result.passed:
                        by_profile[profile]["passed"] += 1
                    break

        for profile in by_profile:
            stats = by_profile[profile]
            stats["rate"] = stats["passed"] / stats["total"] if stats["total"] > 0 else 0

        passed_count = sum(1 for r in results if r.passed)
        report = EvalReport(
            total_cases=len(self.test_cases),
            passed=passed_count,
            failed=len(self.test_cases) - passed_count,
            pass_rate=passed_count / len(self.test_cases) if self.test_cases else 0,
            results=results,
            by_profile=by_profile,
            trajectory_issues=trajectory_issues,
        )

        return report

    async def _evaluate_one(self, case: dict, run: int) -> EvalResult:
        """Evaluate a single test case."""
        result = EvalResult(
            case_id=case["case_id"],
            passed=False,
            profile_matched=False,
            route_exists=False,
        )

        try:
            # Parse query
            query = self._orchestrator.parse_query(case["input"])
            result.profile_matched = (
                query.accessibility_profile.value == case.get("profile", "general")
            )

            # Plan route
            response = await self._orchestrator.plan_route(query)
            result.route_exists = len(response.routes) > 0
            result.trajectory_valid = len(response.tool_calls_made) >= 2  # At least planner + filter

            # Check constraints
            expected_constraints = case.get("expected_constraints", [])
            for constraint in expected_constraints:
                if self._check_constraint(constraint, response):
                    result.constraints_met.append(constraint)
                else:
                    result.constraints_failed.append(constraint)

            # Score against rubric
            if case.get("rubric"):
                result.rubric_scores = self._llm_as_judge(
                    case["input"],
                    response.natural_response,
                    case["rubric"],
                )

            # Determine pass/fail
            route_check = result.route_exists == case.get("expected_route_exists", True)
            profile_check = result.profile_matched
            constraint_check = len(result.constraints_failed) == 0

            result.passed = route_check and profile_check and constraint_check

        except Exception as e:
            result.error_message = str(e)
            result.passed = False
            logger.error(f"Eval error for {case['case_id']}: {e}")

        return result

    # ------------------------------------------------------------------
    # Constraint checking
    # ------------------------------------------------------------------

    def _check_constraint(self, constraint: str, response) -> bool:
        """Check if a constraint is satisfied in the agent's response.

        This is a simplified check. In production, this would use an
        LLM-as-Judge for nuanced constraint validation.
        """
        text = response.natural_response.lower()

        checks = {
            "step-free": "step-free" in text or "step free" in text,
            "lift_at_both_stations": "lift" in text,
            "minimal_walking": "min" in text or "walk" in text,
            "tram_not_accessible": (
                "tram" in text and ("not accessible" in text or "not wheelchair" in text)
            ),
            "minibus_not_accessible": (
                "minibus" in text and ("not accessible" in text or "not wheelchair" in text)
            ),
        }

        return checks.get(constraint, True)  # Default True for unknown constraints

    # ------------------------------------------------------------------
    # LLM-as-Judge (Day 3 Section 3.4 and Day 4 Section 4.9)
    # ------------------------------------------------------------------

    def _llm_as_judge(
        self,
        user_input: str,
        agent_output: str,
        rubric: list[str],
    ) -> dict[str, float]:
        """Score the agent's output against a rubric using LLM-as-Judge.

        In production, this calls the LIGHT model with a structured scoring
        prompt. For the prototype, we use keyword-based heuristics to
        approximate the LLM-as-Judge scoring (shift intelligence left).

        Day 4 Section 4.9 rule:
            Swap reference and actual output positions to eliminate order bias.
        """
        scores = {}
        for criterion in rubric:
            # Simplified scoring — production uses actual LLM call
            score = self._heuristic_rubric_score(criterion, agent_output)
            scores[criterion] = score
        return scores

    def _heuristic_rubric_score(
        self, criterion: str, output: str
    ) -> float:
        """Heuristic rubric scoring based on keyword presence.

        In production, replaced by LLM-as-Judge call with the rubric as prompt.
        """
        output_lower = output.lower()

        patterns = {
            "identifies_step_free_route": ["step-free", "step free", "lift", "accessible route"],
            "checks_lift_status": ["lift", "exit"],
            "mentions_mtr_wide_gate": ["wide gate", "wide gate"],
            "checks_lift_at_both_stations": ["lift"],
            "mentions_interchange_accessibility": ["interchange", "transfer", "change"],
            "warns_prince_edward_no_lift": ["prince edward", "太子"],
            "suggests_mong_kok_alternative": ["mong kok", "旺角"],
            "blocks_tram_route": ["not accessible", "not wheelchair", "can't"],
            "blocks_minibus_route": ["minibus", "not accessible"],
            "handles_chinese_input": [],  # Always true if we got here
            "minimises_walking": ["min", "walk"],
            "limits_interchanges": ["change", "interchange"],
            "mentions_lift_preference": ["lift"],
            "flags_rain_hazard": ["rain", "wet", "slippery"],
            "minimises_outdoor_segments": ["outdoor", "covered"],
            "checks_weather_warning": ["weather", "typhoon", "rainstorm"],
            "mentions_tactile_guide_paths": ["tactile", "guide path"],
            "notes_audio_announcements": ["audio", "announce"],
            "warns_about_complex_interchange": ["complex", "interchange"],
            "mentions_elderly_fare": ["$2", "fare", "concession", "elderly"],
        }

        keywords = patterns.get(criterion, [])
        if not keywords:
            return 0.5  # Can't evaluate heuristically

        matches = sum(1 for kw in keywords if kw in output_lower)
        return min(1.0, matches / len(keywords))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def main():
    """Run the evaluation framework."""
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(
        description="Evaluate HK Accessible Transit Navigator"
    )
    parser.add_argument(
        "--dataset", "-d",
        default="evals/test_cases.json",
        help="Path to golden dataset JSON",
    )
    parser.add_argument(
        "--runs", "-k",
        type=int, default=1,
        help="Number of runs per test case (use 5 for pass^5)",
    )
    parser.add_argument(
        "--output", "-o",
        help="Path to write JSON evaluation report",
    )
    args = parser.parse_args()

    evaluator = Evaluator(dataset_path=args.dataset)
    print(f"Running {len(evaluator.test_cases)} test cases "
          f"(pass^{args.runs})...\n")

    report = await evaluator.evaluate(runs_per_case=args.runs)
    print(report.summary())

    if args.output:
        with open(args.output, "w") as f:
            json.dump({
                "summary": {
                    "total": report.total_cases,
                    "passed": report.passed,
                    "failed": report.failed,
                    "pass_rate": report.pass_rate,
                    "pass_k": args.runs,
                },
                "by_profile": report.by_profile,
                "results": [
                    {
                        "case_id": r.case_id,
                        "passed": r.passed,
                        "profile_matched": r.profile_matched,
                        "route_exists": r.route_exists,
                        "constraints_met": r.constraints_met,
                        "constraints_failed": r.constraints_failed,
                        "rubric_scores": r.rubric_scores,
                        "trajectory_valid": r.trajectory_valid,
                        "error": r.error_message,
                        "latency_ms": r.latency_ms,
                    }
                    for r in report.results
                ],
            }, f, indent=2)
        print(f"\nReport written to {args.output}")

    # Exit code: 0 if all pass, 1 if any failures
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    import asyncio
    import sys
    sys.exit(asyncio.run(main()))
