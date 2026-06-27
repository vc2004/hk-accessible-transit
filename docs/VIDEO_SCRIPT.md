# Video Script: HK Accessible Transit Navigator

> **Duration:** 3 minutes
> **Format:** Screen recording + voiceover

---

## Scene 1: Problem (0:00 - 0:30)

**Visual:** Quick cuts of Hong Kong MTR stations — stairs, crowds, a wheelchair
symbol sign, an elderly person navigating an interchange. Overlay text:
"12 million trips daily. Not all of them accessible."

**Voiceover:**
"Hong Kong's public transport is world-class. But for wheelchair users,
elderly passengers, and parents with strollers, a simple journey can become
impossible. Lift outages go unreported. Accessible routes are hidden in PDFs.
No single service answers the question: can I get there, step-free?"

---

## Scene 2: Why Agents (0:30 - 0:50)

**Visual:** Split screen showing fragmented data sources (MTR app, KMB app,
HKO website, gov data portal) merging into a single agent interface.

**Voiceover:**
"Traditional apps can't solve this. The data is too fragmented, the rules too
complex. An AI agent can — using MCP servers to connect transit data, a
multi-agent system to plan and filter routes, and natural language so anyone
can ask in their own words."

---

## Scene 3: Architecture (0:50 - 1:20)

**Visual:** Architecture diagram animating in. Four agent boxes light up as
they're mentioned. MCP server boxes connect with arrows.

**Voiceover:**
"The system uses four specialized agents. The Orchestrator understands your
query. The Route Planner finds transit options. The Accessibility Filter checks
every segment against your needs — lifts for wheelchairs, minimal walking for
elderly, tactile paths for visually impaired. The Alert Monitor watches for
lift outages, weather, and service disruptions. Two custom MCP servers feed
them real-time Hong Kong transit and accessibility data."

---

## Scene 4: Demo (1:20 - 2:20)

**Visual:** Terminal or simple web UI. Type queries, see responses appear.

**Voiceover:**
"Let me show you. A wheelchair user asks: from Tai Po Market to Central…"

**Demo 1 — Wheelchair route:**
```
> I need to go from Tai Po Market to Central. I use a wheelchair.

🥇 Option 1: MTR East Rail Line (25 min)
   ♿ Tai Po Market → Admiralty → Central
   Lift at Exit A (Tai Po Market), Exit J (Central)
   ⚠️ Exit B lift under maintenance until June 30

♿ All routes step-free.
```

**Demo 2 — Blocked route (minibus):**
```
> wheelchair, take minibus 25M from Kowloon Tong

❌ Green minibuses are NOT wheelchair accessible in Hong Kong.
   Alternative: MTR Kwun Tong Line (2 stops, step-free)
```

**Demo 3 — Chinese query:**
```
> 老人家由沙田去中環，行路好辛苦

👴 Elderly-friendly route from Sha Tin to Central
   MTR East Rail Line, 18 min, 0 interchanges
   Lift at both stations. All seated transport.
   $2 fare with Elder Octopus Card.
```

---

## Scene 5: The Build (2:20 - 2:45)

**Visual:** Code editor showing key files — security/policy_server.py,
agent/accessibility_filter.py, evals/test_cases.json.

**Voiceover:**
"Built in Python with the MCP SDK. The accessibility filter is entirely
deterministic — safety-critical routing should never hallucinate. Security is
layered: PII masking, a policy server with structural and semantic gating, and
input sanitization blocking injection attacks. Sixty unit tests and a 30-case
golden dataset ensure reliability across all accessibility profiles."

---

## Scene 6: Impact (2:45 - 3:00)

**Visual:** Fade to project logo + GitHub URL. Overlay: "Open source. Built for
Hong Kong. Agents for Good."

**Voiceover:**
"HK Accessible Transit Navigator. Making Hong Kong's world-class transport
system accessible to everyone. Built for the Kaggle AI Agents Capstone Project."

---

## Recording Tips

1. **Screen recording:** Use OBS (free) or macOS QuickTime screen recording
2. **Terminal:** Use a clean terminal with large font (14-16pt) for readability
3. **Microphone:** Built-in Mac mic is fine — record in a quiet room
4. **Editing:** iMovie is sufficient. Cut pauses, add title overlays
5. **Upload:** Export as 1080p MP4, upload to YouTube (unlisted is fine)
