# HK Accessible Transit Navigator — Technical Design

## Problem Statement

Hong Kong's public transport system carries 12+ million passenger trips daily across
10 MTR lines, 700+ bus routes, green minibuses, ferries, and trams. For people with
mobility challenges — wheelchair users, elderly with limited mobility, visually
impaired persons, and parents with strollers — navigating this system is a daily
struggle:

- Only ~60% of MTR exits have step-free lift access
- Lift/escalator outages are posted as PDF notices, not real-time data
- No single service combines accessibility data across MTR, buses, and minibuses
- Elderly users often cannot read English station names or complex route maps

## Solution Overview

A multi-agent AI system that takes an origin, destination, and accessibility
profile, then returns a step-free, disruption-aware route with turn-by-turn
guidance and real-time alerts.

## Architecture

```
                          ┌─────────────────────┐
                          │   User (Natural      │
                          │   Language Query)     │
                          └──────────┬──────────┘
                                     │
                          ┌──────────▼──────────┐
                          │  Orchestrator Agent  │
                          │  (Intent Routing +   │
                          │   Response Synthesis)│
                          └──┬────────┬─────────┘
                             │        │
              ┌──────────────▼─┐  ┌──▼──────────────────┐
              │ Route Planner   │  │ Accessibility Filter │
              │ Agent           │  │ Agent                │
              │                 │  │                      │
              │ • Multi-modal   │  │ • Step-free rules    │
              │   pathfinding   │  │ • Lift/escalator db  │
              │ • Real-time ETA │  │ • Profile matching   │
              └──────┬──────────┘  └──────┬───────────────┘
                     │                    │
              ┌──────▼────────────────────▼──────┐
              │        MCP Gateway                │
              │  (Tool discovery + execution)      │
              └──┬──────────┬──────────┬──────────┘
                 │          │          │
    ┌────────────▼─┐ ┌──────▼───┐ ┌───▼────────────┐
    │ mcp_hkbus     │ │ mcp-mtr- │ │ hko-mcp         │
    │ (KMB routes,  │ │ access   │ │ (weather/warn)  │
    │  stops, ETA)  │ │ (MTR     │ │                  │
    │               │ │ lifts,   │ │                  │
    │               │ │ exits)   │ │                  │
    └───────────────┘ └──────────┘ └──────────────────┘
```

## Agent Descriptions

### 1. Orchestrator Agent (Main)
- Receives natural language queries ("I need to go from Tai Po to Queen Mary
  Hospital, I use a wheelchair")
- Classifies accessibility profile (wheelchair / elderly / visually impaired /
  stroller / general)
- Dispatches to Route Planner and Accessibility Filter sub-agents
- Synthesizes results into a user-friendly response
- Invokes Alert Monitor for real-time disruption checks

### 2. Route Planner Agent
- Queries mcp_hkbus for bus routes, stops, and ETAs
- Queries MTR API for rail schedules
- Returns up to 3 route options ranked by total time
- Annotates each segment with transport mode and stop IDs

### 3. Accessibility Filter Agent
- Maintains a rules engine for step-free requirements:
  - Wheelchair: requires lift at BOTH origin and destination stations
  - Elderly: prefers lifts, avoids long walks (>500m), prefers seated transport
  - Visually impaired: requires audio-announcement-equipped stations
  - Stroller: requires wide gates and lifts
- Filters route options based on accessibility profile
- Flags segments that violate accessibility constraints

### 4. Alert Monitor Agent
- Checks real-time lift/escalator outage data
- Checks hko-mcp for weather warnings (rain affects outdoor segments)
- Checks MTR service status for disruptions
- Adds alerts to route guidance

## Data Sources & MCP Servers

### Existing MCP Servers (consumed directly)
| Server | Data | Transport |
|--------|------|-----------|
| `mcp_hkbus` (kennyckk) | KMB/LWB routes, stops, real-time ETA | stdio |
| `hko-mcp` (louiscklaw) | HKO weather, warnings, typhoon alerts | stdio |

### Custom MCP Servers (built for this project)
| Server | Data | Purpose |
|--------|------|---------|
| `hk-transit-mcp` | MTR lines/stations, Citybus routes, minibus data | Unified transit queries |
| `mtr-accessibility-mcp` | MTR lift locations, exit accessibility, facilities | Step-free routing |

## Agent Skills

### Skill: `accessibility-filter`
- Trigger: user mentions wheelchair, elderly, step-free, blind, stroller
- Body: rules for filtering routes by accessibility type
- Script: `calc_accessibility_score.py` — scores each route segment

### Skill: `elderly-friendly`
- Trigger: user mentions elderly, senior, aged, 老人家, 長者
- Body: additional constraints for elderly users (minimise walking, prefer
  seated transport, simpler interchange patterns)

## Security Architecture

### 1. PII Masking (pii_masking.py)
- User location data (origin/destination) is hashed before logging
- User profiles stored with pseudonymous IDs
- Location precision reduced to district-level in logs

### 2. Policy Server (policy_server.py)
- Structural gating: deterministic allow/deny based on role + environment
- Semantic gating: LLM-based check for PII in outputs
- All agent actions pass through Policy Server before execution

### 3. Input Sanitization (input_sanitizer.py)
- Strips potential injection patterns from user queries
- Validates location names against known Hong Kong gazetteer
- Rejects queries containing executable code patterns

## Evaluation Framework

### Golden Dataset (test_cases.json)
- 30 representative queries covering:
  - All accessibility profiles (wheelchair, elderly, visually impaired, stroller)
  - All Hong Kong regions (HK Island, Kowloon, NT East, NT West, Islands)
  - Edge cases (cross-harbour, late night, typhoon warning)

### Evaluation Metrics
- Route existence: does the agent return at least 1 valid route?
- Accessibility compliance: does the route respect the user profile?
- Response quality: LLM-as-Judge scoring on clarity, completeness, safety

### pass^k Implementation
- Each test case run 5 times; requires 5/5 passes for Action-Allowed graduation

## Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.11+ | Rich MCP ecosystem, ADK SDK support |
| Agent Framework | Custom loop (ADK-compatible) | Demonstrates understanding of agent internals |
| MCP SDK | `mcp` (official Python SDK) | Standard, well-documented |
| Transport | stdio (local), SSE (future remote) | stdio for dev/prototype |
| LLM | Gemini / Claude (configurable) | Multi-model support |
| Testing | pytest | Standard, fixtures for agent tests |
| Eval | Custom runner + LLM-as-Judge | Matches course EDD methodology |

## Project Conventions

- All code comments in English
- Hong Kong place names use official English romanisation
- Accessibility terminology follows MTR "Step-free Access" standard
- Commit messages reference spec sections
