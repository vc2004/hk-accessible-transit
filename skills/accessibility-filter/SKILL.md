---
name: accessibility-filter
description: |
  Filters public transport routes by accessibility requirements. Use when the
  user mentions wheelchair, step-free, barrier-free, blind, visually impaired,
  stroller, pram, baby, or any mobility aid. Evaluates each route segment
  against the user's accessibility profile and flags violations.
  Triggers: wheelchair, step-free, barrier-free, 輪椅, 無障礙, blind, visually
  impaired, 視障, stroller, pram, 嬰兒車, elderly mobility, 行動不便.
  Do NOT use for general route planning without accessibility constraints.
---

# Accessibility Filter Skill

## Purpose
Evaluate public transport routes against accessibility requirements for
different user profiles. This skill ensures that routes recommended to
users with mobility challenges are actually usable for them.

## When to Activate
Activate when the user's query or profile indicates ANY of:
- Wheelchair user
- Visually impaired / blind
- Travelling with stroller / pram / baby
- Elderly with limited mobility
- Using a walking aid (cane, walker, crutches)

## Accessibility Profiles

### Wheelchair (♿)
**Hard requirements — route is unusable if ANY of these fail:**
1. All MTR stations must have lift-equipped exits (not just escalators)
2. Buses must be low-floor with wheelchair ramp
3. NO minibuses (GMB/red minibus) — none are wheelchair accessible in HK
4. NO trams — step-up entry only
5. Ferry: Star Ferry only (Central ↔ TST), verify other operators
6. Walking segments ≤ 300m
7. Maximum 2 interchanges

**Soft preferences (warn but don't block):**
- Prefer stations with accessible toilets
- Avoid peak-hour crowded stations (lift wait times can be 10+ min)

### Elderly (👴)
**Hard requirements:**
1. Walking segments ≤ 200m
2. Maximum 1 interchange
3. Total journey ≤ 90 minutes

**Soft preferences:**
- Prefer lifts over escalators at all stations
- Prefer seated transport (bus/rail over walking)
- Avoid complex interchanges (Admiralty, Central, Mong Kok, Kowloon Tong)
- Flag outdoor segments during rain/heat

### Visually Impaired (🦯)
**Hard requirements:**
1. Stations must have tactile guide paths
2. Stations must have audio announcements
3. Maximum 1 interchange
4. Avoid stations with complex layouts

**Soft preferences:**
- Prefer MTR over buses (more predictable layout)
- Flag stations without platform screen doors

### Stroller (👶)
**Hard requirements:**
1. All MTR stations must have lifts (wide gates preferred)
2. Buses: low-floor preferred
3. NO trams (difficult with stroller)
4. Walking segments ≤ 300m

**Soft preferences:**
- Prefer stations with accessible toilets (nappy changing)
- Avoid peak-hour MTR (stroller space limited)

## How to Use

1. Receive a route from the Route Planner agent
2. Identify the user's accessibility profile from the query context
3. For each route segment, check against the profile's requirements
4. Output: PASS (accessible), FAIL with reason, or WARN with caveats
5. If ALL routes fail, return the least-bad option with explicit warnings

## Script: calc_accessibility_score.py
Located in this skill's directory. Run it to score a route against a profile:
```
python skills/accessibility-filter/calc_accessibility_score.py \
  --route 'MTR:TAP→ADM→CAB' --profile wheelchair
```

## Important Rules
- **Safety first**: When in doubt, FAIL. A false PASS can strand a wheelchair user.
- **Be specific**: "No lift at Prince Edward Exit A" is better than "Station not accessible".
- **Suggest alternatives**: For every FAIL, suggest what would make it pass.
- **MTR step-free guide**: https://www.mtr.com.hk/en/customer/services/stepfree.html

## Hong Kong-Specific Knowledge
- Green minibuses (GMB, 綠色小巴): NOT wheelchair accessible. Period.
- Red minibuses (紅色小巴): NOT wheelchair accessible. Also no fixed schedule.
- Trams (電車): Step-up entry. Narrow aisle. NOT accessible.
- Star Ferry: Wheelchair accessible at Central Pier 7 and TST Star Ferry Pier.
- KMB/Citybus: Low-floor buses on most trunk routes. Check ETA apps for
  wheelchair-accessible departure icons.
- MTR: ~60% of exits have step-free access. Always verify at mtr.com.hk.
- Rehabus (復康巴士): Door-to-door accessible transport service. Suggest as
  fallback if no public transport route works.
