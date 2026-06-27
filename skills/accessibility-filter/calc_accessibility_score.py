#!/usr/bin/env python3
"""
Calculate an accessibility score for a route against a user profile.

Part of the accessibility-filter Agent Skill. Called by the Accessibility
Filter Agent to produce a quantifiable score for evaluation purposes.

Usage:
    python calc_accessibility_score.py --route "MTR:TAP→ADM→CAB" --profile wheelchair
    python calc_accessibility_score.py --route "KMB:74X:TaiPo→MongKok" --profile elderly
"""

import argparse
import json
import sys


# Profile-specific scoring weights
WEIGHTS = {
    "wheelchair": {
        "lift_available": 30,      # Most important for wheelchair users
        "step_free_path": 25,
        "low_floor_vehicle": 20,
        "no_blocked_mode": 15,      # e.g., no minibus/tram
        "walking_distance_ok": 5,
        "interchange_count_ok": 5,
    },
    "elderly": {
        "walking_distance_ok": 30,
        "interchange_count_ok": 25,
        "lift_available": 20,
        "seated_transport": 15,
        "total_time_ok": 10,
    },
    "visually_impaired": {
        "tactile_paths": 30,
        "audio_announcements": 25,
        "interchange_count_ok": 20,
        "simple_layout": 15,
        "platform_doors": 10,
    },
    "stroller": {
        "lift_available": 30,
        "step_free_path": 25,
        "wide_gate": 15,
        "no_tram": 10,
        "walking_distance_ok": 10,
        "accessible_toilet": 10,
    },
}


def parse_route(route_str: str) -> list[dict]:
    """Parse a route string like 'MTR:TAP→ADM→CAB' into segments."""
    segments = []
    # Mode: origin→interchange1→...→destination
    mode, path = route_str.split(":", 1)
    stops = path.split("→")
    for i in range(len(stops) - 1):
        segments.append({
            "mode": mode.strip(),
            "from": stops[i].strip(),
            "to": stops[i + 1].strip(),
        })
    return segments


def score_segment(segment: dict, profile: str) -> dict:
    """Score a single segment against a profile. Returns {criterion: score}."""
    scores = {}
    weights = WEIGHTS.get(profile, {})

    # Simplified scoring — in production, queries MCP servers for real data
    mode = segment["mode"].upper()

    if profile == "wheelchair":
        scores["no_blocked_mode"] = 0 if mode in ("GMB", "TRAM", "MINIBUS") else weights["no_blocked_mode"]
        scores["low_floor_vehicle"] = weights["low_floor_vehicle"] if mode in ("MTR", "KMB", "CTB") else 0
        scores["lift_available"] = weights["lift_available"]  # Assume yes, verified by MCP
        scores["step_free_path"] = weights["step_free_path"]
        scores["walking_distance_ok"] = weights["walking_distance_ok"]
        scores["interchange_count_ok"] = weights["interchange_count_ok"]

    elif profile == "elderly":
        scores["walking_distance_ok"] = weights["walking_distance_ok"]
        scores["interchange_count_ok"] = weights["interchange_count_ok"]
        scores["lift_available"] = weights["lift_available"]
        scores["seated_transport"] = weights["seated_transport"] if mode in ("MTR", "KMB", "CTB") else 0
        scores["total_time_ok"] = weights["total_time_ok"]

    elif profile == "visually_impaired":
        scores["tactile_paths"] = weights["tactile_paths"] if mode == "MTR" else weights["tactile_paths"] // 2
        scores["audio_announcements"] = weights["audio_announcements"] if mode == "MTR" else 0
        scores["interchange_count_ok"] = weights["interchange_count_ok"]
        scores["simple_layout"] = weights["simple_layout"]
        scores["platform_doors"] = weights["platform_doors"] if mode == "MTR" else 0

    elif profile == "stroller":
        scores["lift_available"] = weights["lift_available"]
        scores["step_free_path"] = weights["step_free_path"]
        scores["wide_gate"] = weights["wide_gate"] if mode == "MTR" else 0
        scores["no_tram"] = 0 if mode == "TRAM" else weights["no_tram"]
        scores["walking_distance_ok"] = weights["walking_distance_ok"]
        scores["accessible_toilet"] = weights["accessible_toilet"] if mode == "MTR" else 0

    return scores


def main():
    parser = argparse.ArgumentParser(
        description="Score a transit route for accessibility"
    )
    parser.add_argument(
        "--route", "-r", required=True,
        help="Route string, e.g., 'MTR:TAP→ADM→CAB'",
    )
    parser.add_argument(
        "--profile", "-p", required=True,
        choices=["wheelchair", "elderly", "visually_impaired", "stroller"],
        help="Accessibility profile to score against",
    )
    args = parser.parse_args()

    segments = parse_route(args.route)
    weights = WEIGHTS[args.profile]
    max_score = sum(weights.values()) * len(segments)

    total = 0
    detail = []
    for seg in segments:
        seg_scores = score_segment(seg, args.profile)
        seg_total = sum(seg_scores.values())
        total += seg_total
        detail.append({
            "segment": f"{seg['from']} → {seg['to']}",
            "mode": seg["mode"],
            "score": seg_total,
            "max": sum(weights.values()),
            "breakdown": seg_scores,
        })

    result = {
        "route": args.route,
        "profile": args.profile,
        "segments": detail,
        "total_score": total,
        "max_score": max_score,
        "percentage": round(total / max_score * 100, 1) if max_score > 0 else 0,
        "verdict": "PASS" if total / max_score >= 0.7 else "FAIL",
    }

    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
