# HK Accessible Transit Navigator

> **Track:** Agents for Good
> **Kaggle 5-Day AI Agents: Intensive Vibe Coding Capstone Project**

An AI-powered multi-agent system that helps people with mobility challenges
navigate Hong Kong's public transport system with step-free, accessible routes.

---

## Problem

Hong Kong's public transport system is one of the world's most complex: 10 MTR
lines, 700+ bus routes, green minibuses, ferries, and trams carrying 12 million
passenger trips daily. For the **elderly, wheelchair users, visually impaired,
and parents with strollers**, navigating this system presents daily barriers:

- Only ~60% of MTR exits have step-free lift access
- Lift/escalator outage information is scattered across operator websites
- No single service combines accessibility data across all transport modes
- Hong Kong's rapidly aging population (20%+ aged 65+) makes this an urgent need

## Solution

A **multi-agent AI system** that accepts natural language queries about journeys
and returns accessible, step-free routes with real-time disruption alerts.

**Example:** "I need to go from Tai Po Market to Queen Mary Hospital. I use a
wheelchair and it's raining."

→ Agent plans a route using MTR (Tai Po Market → Admiralty → Central → bus) with
step-free exits at both ends, real-time lift status, and weather-aware outdoor
segment warnings.

## Architecture

```
User Query (Natural Language)
        │
┌───────▼──────────┐
│  Orchestrator    │  Intent routing + response synthesis
│  Agent           │
└──┬──────┬────────┘
   │      │
┌──▼──┐ ┌─▼──────────────┐
│Route│ │Accessibility     │
│Plan │ │Filter Agent      │
│Agent│ │                  │
│     │ │• Step-free rules │
│     │ │• Profile matching│
└──┬──┘ └─┬───────────────┘
   │      │
┌──▼──────▼──────────┐
│   MCP Gateway       │
└─┬──────┬────────┬───┘
  │      │        │
┌─▼──┐ ┌─▼───┐ ┌─▼──────┐
│KMB │ │MTR  │ │Weather │
│MCP │ │MCP  │ │MCP     │
└────┘ └─────┘ └────────┘
```

### Multi-Agent System

| Agent | Responsibility |
|-------|---------------|
| **Orchestrator** | Parses user intent, dispatches sub-agents, synthesizes response |
| **Route Planner** | Multi-modal pathfinding across MTR, buses, minibuses |
| **Accessibility Filter** | Enforces step-free rules per accessibility profile |
| **Alert Monitor** | Real-time disruption checks (lifts, weather, service status) |

### MCP Servers

| MCP Server | Source | Purpose |
|-----------|--------|---------|
| `mcp_hkbus` | Community | KMB/LWB bus routes, stops, real-time ETA |
| `hk-transit-mcp` | **Custom-built** | MTR lines, stations, Citybus, minibus data |
| `mtr-accessibility-mcp` | **Custom-built** | MTR lift locations, exit accessibility, facilities |
| `hko-mcp` | Community | Hong Kong Observatory weather and warnings |

### Agent Skills

| Skill | Trigger | Purpose |
|-------|---------|---------|
| `accessibility-filter` | wheelchair, step-free, blind, stroller | Filters routes by accessibility rules |
| `elderly-friendly` | elderly, senior, 長者 | Extra constraints for elderly passengers |

### Security

| Feature | Description |
|---------|-------------|
| **PII Masking** | Location data hashed before logging; pseudonymous user profiles |
| **Policy Server** | Structural (deterministic) + Semantic (LLM-based) gating |
| **Input Sanitization** | Injection prevention, location name validation |

## Key Course Concepts Applied

| # | Concept | Where Demonstrated |
|---|---------|-------------------|
| 1 | **Agent / Multi-agent System** | `agent/` — Orchestrator + Route Planner + Accessibility Filter + Alert Monitor |
| 2 | **MCP Server** | `mcp_servers/` — Custom MCP servers for HK transit & MTR accessibility |
| 3 | **Security Features** | `security/` — PII masking, Policy Server (structural + semantic), input sanitization |
| 4 | **Agent Skills** | `skills/` — accessibility-filter, elderly-friendly with SKILL.md |
| 5 | **Evaluation** | `evals/` — Golden dataset, LLM-as-Judge, pass^k metric |

## Quick Start

### Prerequisites

- Python 3.11+
- MCP SDK (`pip install mcp`)
- Access to an LLM (Gemini API key or Claude API key)

### Install

```bash
git clone https://github.com/vc2004/hk-accessible-transit.git
cd hk-accessible-transit
pip install -r requirements.txt
```

### Configure LLM (optional — works without API key)

```bash
# For Gemini (Google AI Studio)
export GEMINI_API_KEY="your-gemini-api-key"

# Or for Claude (Anthropic Console)
export ANTHROPIC_API_KEY="your-anthropic-api-key"

# Without either, the agent runs in mock mode with template-based responses.
# All route planning, accessibility filtering, and security features work
# without an LLM — only the natural language synthesis is affected.
```

### Run

```bash
# Interactive CLI
python3.11 -m agent.orchestrator

# Run evaluation suite (30 golden test cases)
python3.11 -m evals.evaluator --dataset evals/test_cases.json

# Run test suite (60 tests)
python3.11 -m pytest tests/ -v
```

### Example Usage

```
> I need to go from Tai Po to Central. I use a wheelchair.

Agent: I'll plan an accessible route from Tai Po to Central for you.

Route options found:

Option 1 (Recommended): MTR East Rail Line
  • Board at Tai Po Market Station (lift available at Exit A)
  • Alight at Admiralty Station (lift to concourse, then Exit E for
    wheelchairs)
  • 2 interchanges, all step-free
  • ETA: 32 minutes
  ⚠️ Note: Tai Po Market lift at Exit B is under maintenance until June 30.
    Use Exit A instead.

Would you like me to check real-time lift status or weather conditions?
```

## Project Structure

```
hk-accessible-transit/
├── README.md                    # This file
├── requirements.txt             # Python dependencies
├── specs/
│   └── design.md               # Full technical design document
├── agent/
│   ├── __init__.py
│   ├── orchestrator.py         # Main orchestrator agent
│   ├── route_planner.py        # Multi-modal route planning agent
│   ├── accessibility_filter.py # Accessibility rules engine
│   ├── alert_monitor.py        # Real-time disruption monitor
│   └── config.py               # Agent configuration + model routing
├── mcp_servers/
│   ├── __init__.py
│   ├── hk_transit_mcp/
│   │   ├── __init__.py
│   │   └── server.py           # HK transit data MCP server
│   └── mtr_accessibility_mcp/
│       ├── __init__.py
│       └── server.py           # MTR accessibility data MCP server
├── skills/
│   ├── accessibility-filter/
│   │   ├── SKILL.md            # Accessibility filtering skill
│   │   └── calc_accessibility_score.py
│   └── elderly-friendly/
│       └── SKILL.md            # Elderly-specific constraints skill
├── security/
│   ├── __init__.py
│   ├── pii_masking.py          # PII anonymization
│   ├── policy_server.py        # Structural + semantic gating
│   └── input_sanitizer.py      # Injection prevention
├── evals/
│   ├── __init__.py
│   ├── test_cases.json         # 30 golden dataset queries
│   └── evaluator.py            # Eval runner with LLM-as-Judge
└── tests/
    ├── __init__.py
    ├── test_orchestrator.py
    ├── test_accessibility.py
    └── test_security.py
```

## Evaluation

The project includes a comprehensive evaluation framework following the course's
Evaluation-Driven Development (EDD) methodology:

- **30 golden dataset queries** covering all accessibility profiles and HK regions
- **LLM-as-Judge** scoring on route validity, accessibility compliance, and clarity
- **pass^k metric** (k=5) for production-readiness assessment
- **Trajectory scoring** for tool call sequence validation

## License

MIT

---

*Built for the Kaggle AI Agents: Intensive Vibe Coding Capstone Project (2026)*
