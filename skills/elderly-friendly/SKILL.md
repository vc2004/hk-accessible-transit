---
name: elderly-friendly
description: |
  Extra constraints for elderly passengers planning public transport journeys in
  Hong Kong. Adds rules for minimising walking, preferring seated transport,
  avoiding peak hours, and flagging heat/rain hazards. Use when the user mentions
  elderly, senior, 長者, 老人家, aged, retired, or has limited walking ability.
  Triggers: elderly, senior, old, aged, 長者, 老人家, 退休, difficult walking,
  walking aid, 拐杖, 助行架.
  Do NOT use for general accessibility queries without age/mobility context.
---

# Elderly-Friendly Transit Skill

## Purpose
Add extra safety and comfort constraints for elderly passengers. While the
accessibility-filter skill handles wheelchair-specific rules, this skill
addresses the subtler needs of older passengers who may not use wheelchairs
but still face mobility challenges.

## When to Activate
Activate when ANY of these are true:
- User self-identifies as elderly, senior, old, retired, 長者, 老人家
- User mentions walking difficulty, walking aid, cane, 拐杖, 助行架
- Query is about a journey for someone aged 65+

## Elderly-Specific Constraints

### Hard Constraints
1. **Walking distance**: Each walking segment ≤ 200m (~3 min at slow pace)
2. **Interchanges**: Maximum 1 interchange (each interchange requires navigating
   a new station layout, finding lifts, potentially long corridors)
3. **Total time**: Journey ≤ 90 minutes (fatigue management)
4. **No stairs-only routes**: If a segment requires stairs and no lift exists,
   the route is unusable

### Soft Constraints (warn but don't block)
1. **Seated preference**: Prefer transport modes where user can sit (MTR, bus)
   over long walks or standing on crowded minibuses
2. **Peak avoidance**: Flag if journey coincides with peak hours (8-9:30am,
   5:30-7pm) — crowded trains are difficult for elderly
3. **Weather sensitivity**: Flag outdoor walking segments during:
   - Rain (slippery surfaces)
   - Heat (≥32°C, risk of heat exhaustion)
   - Cold (≤10°C)
4. **Toilet availability**: Prefer routes with accessible toilets at
   interchange stations
5. **Seating at stops**: Prefer bus stops and station platforms with seating

## Hong Kong-Specific Elderly Benefits to Mention
- **$2 fare scheme**: Eligible elderly (65+) pay $2 per trip on MTR, buses,
  minibuses, and ferries. Always mention this when quoting fares.
- **Priority seats**: Available on all MTR trains and most buses.
- **MTR wide gates**: Elderly passengers can use wide gates (same as wheelchair
  users) — easier than standard gates with walking aids.
- **Octopus Elder Card**: Personalised Octopus for $2 scheme. Remind users
  they need this card for the concession fare.

## Interaction with Other Skills
- Runs AFTER accessibility-filter. If accessibility-filter blocks a route,
  elderly-friendly is not needed.
- If both accessibility-filter and elderly-friendly are active, combine
  constraints (take the stricter of any overlapping rules).
- Consult weather data from hko-mcp for heat/rain warnings.
