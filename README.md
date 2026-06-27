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
- An LLM API key (optional — works without one in mock mode)

### Install

```bash
git clone https://github.com/vc2004/hk-accessible-transit.git
cd hk-accessible-transit
pip install -r requirements.txt
```

### Configure LLM

Tested and verified with both **DeepSeek** and **Gemini**. Copy `.env.template` to `.env` and fill in any ONE:

```bash
# DeepSeek (tested with deepseek-v4-flash)
DEEPSEEK_API_KEY=sk-your-key-here

# Gemini (tested with gemini-2.5-pro)
GEMINI_API_KEY=your-gemini-key-here

# Claude (supported, not yet tested)
# ANTHROPIC_API_KEY=your-anthropic-key-here
```

Without an API key, the agent runs in mock mode — all route planning,
accessibility filtering, MCP tools, and security features work fully.
Only the natural language response synthesis uses the LLM.

### Run Demo

```bash
# Quick demo (English + 繁體中文 + 简体中文)
python3.11 run_demo.py

# Interactive CLI
python3.11 -m agent.orchestrator

# Run evaluation suite (30 golden test cases)
python3.11 -m evals.evaluator --dataset evals/test_cases.json

# Run test suite (60 tests)
python3.11 -m pytest tests/ -v
```

### Example Output (English)

```
Q: Sha Tin to Central, wheelchair

♿ Accessible Route: Sha Tin → Central
Best option: MTR only ✅
Total time: ~35 minutes | Interchanges: 1 (Admiralty)

🚇 Segment-by-Segment:
  1. Sha Tin (EAL) → Admiralty – 15 min, lift available ✅
  2. Admiralty → Central (TWL) – 15 min, lift available ✅

💡 Practical Tips:
  • At Admiralty, follow wheelchair-accessible signs for the interchange
  • At Central, lifts available from platform to all exits
  • All stations and interchanges have lifts — no step-free gaps
  • Consider Rehabus as fallback: call 2817 8154
```

### Example Output (繁體中文)

```
Q: 我係輪椅使用者，想由大埔墟去金鐘，要lift唔要樓梯

♿ 無障礙路線：大埔墟 → 金鐘
最佳選擇：東鐵綫直達 ✅
總時間：約22分鐘 | 轉車次數：0

🚇 詳細路線：
  1. 大埔墟站（東鐵綫）→ 金鐘站 – 約22分鐘
     升降機：大埔墟站A出口或C出口有𨋢 ✅

⚠️ 注意：大埔墟站B出口升降機維修中（至2026年6月30日），請用A或C出口。
```

### Example Output (简体中文)

```
Q: 老人，从沙田去中环，走路不方便，请帮我找最轻松的路线

👴 长者友好路线：沙田 → 中环
最佳选择：东铁线换乘荃湾线
总时间：约35分钟 | 换乘次数：1（金钟站）

🚇 详细路线：
  1. 沙田站（东铁线）→ 金钟站 – 约18分钟
  2. 金钟站（荃湾线）→ 中环站 – 约5分钟

💡 贴心提示：
  • 所有车站都有升降机，全程无需上落楼梯
  • 建议避开繁忙时间（朝8-9:30、晚5:30-7）
  • 长者使用$2优惠计划，全程只需$2
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
