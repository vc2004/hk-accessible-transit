#!/usr/bin/env python3
"""Quick demo — English + 繁體中文 + 简体中文 queries."""

import asyncio
from agent.orchestrator import OrchestratorAgent, UserQuery
from agent.config import AccessibilityProfile


async def main():
    orchestrator = OrchestratorAgent()

    print("=" * 60)
    print("HK Accessible Transit Navigator ♿")
    print("Multi-Agent System + DeepSeek LLM + Live MTR API")
    print("=" * 60)

    demos = [
        # English
        ("Sha Tin to Central, wheelchair",
         "Sha Tin", "Central", AccessibilityProfile.WHEELCHAIR),
        # Traditional Chinese
        ("我係輪椅使用者，想由大埔墟去金鐘，要lift唔要樓梯",
         "Tai Po Market", "Admiralty", AccessibilityProfile.WHEELCHAIR),
        # Simplified Chinese
        ("老人，从沙田去中环，走路不方便，请帮我找最轻松的路线",
         "Sha Tin", "Central", AccessibilityProfile.ELDERLY),
    ]

    for text, origin, dest, profile in demos:
        print(f"\n{'─' * 50}")
        print(f"Q: {text}")
        print(f"{'─' * 50}\n")
        query = UserQuery(raw_text=text, origin=origin, destination=dest,
                          accessibility_profile=profile)
        response = await orchestrator.plan_route(query)
        print(response.natural_response)

    await orchestrator.shutdown()
    print("\nDone — all systems operational.")

if __name__ == "__main__":
    asyncio.run(main())
