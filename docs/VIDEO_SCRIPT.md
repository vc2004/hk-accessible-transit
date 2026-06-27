# Video Script: HK Accessible Transit Navigator

> **Duration:** 3 minutes
> **Format:** Screen recording terminal + voiceover

---

## Scene 1: Problem (0:00 - 0:30)

**Visual:** Terminal opening. Text overlay: "12M trips daily. Not all accessible."

**Voiceover:**
"Hong Kong's public transport is world-class. But for wheelchair users, elderly
passengers, and visually impaired people, a simple journey can become impossible.
Lift outages go unreported. Accessible information is scattered across PDFs and
websites. No single service answers: can I get there, step-free, right now?"

---

## Scene 2: Demo — English (0:30 - 1:00)

**Visual:** `python3.11 run_demo.py` output scrolls.

```
Q: Sha Tin to Central, wheelchair

♿ Accessible Route: Sha Tin → Central
Total time: ~35 min | Interchanges: 1 (Admiralty)

🚇 Segments:
  1. Sha Tin (EAL) → Admiralty – 15 min, lift available ✅
  2. Admiralty → Central (TWL) – 15 min, lift available ✅

💡 All stations have lifts — no step-free gaps
```

**Voiceover:**
"A wheelchair user asks: Sha Tin to Central. The Route Planner Agent calls
MTR's live API, searches station accessibility via MCP tools, identifies
Admiralty as the interchange, and verifies lifts at both ends. DeepSeek
generates the response."

---

## Scene 3: Demo — 繁體中文 (1:00 - 1:30)

**Visual:**
```
Q: 我係輪椅使用者，想由大埔墟去金鐘，要lift唔要樓梯

♿ 無障礙路線：大埔墟 → 金鐘
最佳選擇：東鐵綫直達 ✅  總時間：約22分鐘

⚠️ 大埔墟B出口升降機維修中（至2026年6月30日），請用A或C出口
```

**Voiceover:**
"The system auto-detects Traditional Chinese and responds in the same language
with Hong Kong-specific terminology — 港鐵、升降機、無障礙. It even flags
a real lift maintenance notice at Tai Po Market Exit B."

---

## Scene 4: Architecture (1:30 - 2:10)

**Visual:** Architecture diagram or code structure scrolling through agent files.

**Voiceover:**
"Under the hood: three specialized agents. The Route Planner uses DeepSeek's
function calling to reason about which MCP tools to call — searching stations,
checking schedules, verifying accessibility. The Accessibility Filter is
deterministic — it never uses an LLM for safety-critical decisions. The Alert
Monitor queries Hong Kong Observatory's live weather API for typhoon and
rainstorm warnings.

Two custom MCP servers provide 11 tools total: station search in English and
Chinese, real-time lift status, bus route accessibility checks, and transport
mode verification. Security is layered: PII masking, a two-tier policy server,
and input sanitization blocking prompt injection attacks."

---

## Scene 5: The Build (2:10 - 2:45)

**Visual:** Tests running — `pytest tests/ -v` output showing 60 passed.

**Voiceover:**
"Built in Python with the MCP SDK. DeepSeek powers the LLM reasoning with
native function calling. Real MTR schedule data from Hong Kong's open data
API — free, no key required. Live weather from the Observatory.

Sixty unit tests. Thirty golden dataset evaluation cases covering all five
accessibility profiles across Hong Kong regions. Evaluation-driven
development — the test cases were written before the accessibility rules."

---

## Scene 6: Impact (2:45 - 3:00)

**Visual:** GitHub repo URL. "Agents for Good — Kaggle AI Agents Capstone 2026"

**Voiceover:**
"HK Accessible Transit Navigator — making Hong Kong's world-class transport
system accessible to everyone. Open source. Three languages. Built for the
Kaggle AI Agents Capstone Project."

---

## Recording Tips

1. **Screen recording:** OBS (free) or macOS QuickTime
2. **Terminal:** Large font (14-16pt), run `python3.11 run_demo.py`
3. **Microphone:** Built-in Mac mic — quiet room
4. **Edit:** iMovie. Cut pauses, add title overlays
5. **Upload:** 1080p MP4 → YouTube (unlisted OK)
