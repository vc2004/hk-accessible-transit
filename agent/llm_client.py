"""
LLM Client — unified interface for multiple LLM providers.

Supports Gemini (Google) and Claude (Anthropic) with automatic
model routing based on complexity tier (heavy vs light).

Usage:
    from agent.llm_client import LLMClient

    client = LLMClient(provider="gemini")
    response = await client.chat(
        messages=[{"role": "user", "content": "Plan a route..."}],
        system_prompt="You are a transit navigator...",
        tier="heavy",
    )
"""

import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# Load .env file before anything else reads environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)


class Provider(Enum):
    GEMINI = "gemini"
    CLAUDE = "claude"
    DEEPSEEK = "deepseek"
    MOCK = "mock"  # For testing without API keys


@dataclass
class LLMConfig:
    """LLM provider configuration."""
    provider: Provider = Provider.MOCK
    api_key: str = ""
    heavy_model: str = ""
    light_model: str = ""
    max_tokens: int = 4096
    temperature: float = 0.3  # Low temp for deterministic routing


def get_config_from_env() -> LLMConfig:
    """Build LLMConfig from environment variables.

    GEMINI_API_KEY → uses Gemini
    ANTHROPIC_API_KEY → uses Claude
    DEEPSEEK_API_KEY → uses DeepSeek
    If none set, defaults to MOCK provider.
    """
    config = LLMConfig()

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")

    if deepseek_key:
        config.provider = Provider.DEEPSEEK
        config.api_key = deepseek_key
        config.heavy_model = os.getenv("DEEPSEEK_HEAVY_MODEL", "deepseek-v4-flash")
        config.light_model = os.getenv("DEEPSEEK_LIGHT_MODEL", "deepseek-v4-flash")
    elif gemini_key:
        config.provider = Provider.GEMINI
        config.api_key = gemini_key
        config.heavy_model = os.getenv("GEMINI_HEAVY_MODEL", "gemini-2.5-pro")
        config.light_model = os.getenv("GEMINI_LIGHT_MODEL", "gemini-2.5-flash")
    elif anthropic_key:
        config.provider = Provider.CLAUDE
        config.api_key = anthropic_key
        config.heavy_model = os.getenv("CLAUDE_HEAVY_MODEL", "claude-sonnet-4-6")
        config.light_model = os.getenv("CLAUDE_LIGHT_MODEL", "claude-haiku-4-5")
    else:
        config.provider = Provider.MOCK
        config.heavy_model = "mock-heavy"
        config.light_model = "mock-light"
        logger.info("No LLM API key found — using MOCK provider")

    return config


class LLMClient:
    """Unified LLM client with provider-specific backends.

    All agent modules call this client instead of calling LLM APIs directly.
    This allows swapping providers without changing agent code.
    """

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or get_config_from_env()

    async def chat(
        self,
        messages: list[dict],
        system_prompt: str = "",
        tier: str = "heavy",
        temperature: Optional[float] = None,
        tools: Optional[list[dict]] = None,
    ) -> str:
        """Send a chat completion request and return the text response.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."}
            system_prompt: System-level instruction
            tier: "heavy" (complex reasoning) or "light" (simple tasks)
            temperature: Override default temperature
            tools: Optional OpenAI-format function definitions for tool calling
        """
        model = (
            self.config.heavy_model if tier == "heavy"
            else self.config.light_model
        )
        temp = temperature if temperature is not None else self.config.temperature

        if self.config.provider == Provider.GEMINI:
            return await self._chat_gemini(messages, system_prompt, model, temp, tools)
        elif self.config.provider == Provider.CLAUDE:
            return await self._chat_claude(messages, system_prompt, model, temp, tools)
        elif self.config.provider == Provider.DEEPSEEK:
            return await self._chat_deepseek(messages, system_prompt, model, temp, tools)
        else:
            return await self._chat_mock(messages, system_prompt, model, temp)

    # ------------------------------------------------------------------
    # Gemini backend
    # ------------------------------------------------------------------

    async def _chat_gemini(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        tools: Optional[list[dict]] = None,
    ) -> str:
        """Call Google Gemini API."""
        try:
            import google.generativeai as genai
        except ImportError:
            logger.error("google-generativeai not installed. pip install google-generativeai")
            return self._fallback_mock_response(messages)

        genai.configure(api_key=self.config.api_key)

        # Gemini uses a different message format
        gemini_messages = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            gemini_messages.append({"role": role, "parts": [msg["content"]]})

        try:
            gemini_model = genai.GenerativeModel(
                model_name=model,
                system_instruction=system_prompt,
            )
            response = await gemini_model.generate_content_async(
                gemini_messages,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": self.config.max_tokens,
                },
            )
            return response.text
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return self._fallback_mock_response(messages)

    # ------------------------------------------------------------------
    # Claude backend
    # ------------------------------------------------------------------

    async def _chat_claude(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        tools: Optional[list[dict]] = None,
    ) -> str:
        """Call Anthropic Claude API."""
        try:
            import anthropic
        except ImportError:
            logger.error("anthropic not installed. pip install anthropic")
            return self._fallback_mock_response(messages)

        try:
            client = anthropic.AsyncAnthropic(api_key=self.config.api_key)

            # Claude uses system param, not a message role
            response = await client.messages.create(
                model=model,
                system=system_prompt,
                messages=[
                    {"role": m["role"], "content": m["content"]}
                    for m in messages
                ],
                max_tokens=self.config.max_tokens,
                temperature=temperature,
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return self._fallback_mock_response(messages)

    # ------------------------------------------------------------------
    # DeepSeek backend
    # ------------------------------------------------------------------

    async def _chat_deepseek(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        tools: Optional[list[dict]] = None,
    ) -> str:
        """Call DeepSeek API (OpenAI-compatible)."""
        try:
            from openai import AsyncOpenAI
        except ImportError:
            logger.error("openai not installed. pip install openai")
            return self._fallback_mock_response(messages)

        try:
            client = AsyncOpenAI(
                api_key=self.config.api_key,
                base_url="https://api.deepseek.com",
            )

            # Build messages with system prompt
            api_messages = []
            if system_prompt:
                api_messages.append({"role": "system", "content": system_prompt})
            api_messages.extend(messages)

            kwargs = {
                "model": model,
                "messages": api_messages,
                "max_tokens": self.config.max_tokens,
                "temperature": temperature,
            }

            # If tools are provided, use function calling
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            response = await client.chat.completions.create(**kwargs)

            msg = response.choices[0].message

            # If the model made a tool call, return it as JSON
            if msg.tool_calls:
                tool_call = msg.tool_calls[0]
                return json.dumps({
                    "tool_call": {
                        "id": tool_call.id,
                        "name": tool_call.function.name,
                        "arguments": json.loads(tool_call.function.arguments),
                    }
                }, ensure_ascii=False)

            return msg.content or ""
        except Exception as e:
            logger.error(f"DeepSeek API error: {e}")
            return self._fallback_mock_response(messages)

    # ------------------------------------------------------------------
    # Mock backend (for development/testing without API keys)
    # ------------------------------------------------------------------

    async def _chat_mock(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        tools: Optional[list[dict]] = None,
    ) -> str:
        """Mock LLM response for testing without API keys.

        Returns a plausible but clearly-marked response so developers
        know when the mock is active vs. a real LLM.
        """
        last_msg = messages[-1]["content"] if messages else ""
        return self._fallback_mock_response(messages)

    def _fallback_mock_response(self, messages: list[dict]) -> str:
        """Generate a mock response based on message content."""
        last_msg = messages[-1]["content"] if messages else ""

        if "route" in last_msg.lower() or "transit" in last_msg.lower():
            return (
                "[MOCK LLM RESPONSE]\n\n"
                "I've analyzed the accessible transit options for your journey.\n\n"
                "🥇 Option 1: MTR East Rail Line\n"
                "   • Board at origin station (lift available at Exit A)\n"
                "   • Alight at destination station (step-free exit confirmed)\n"
                "   • Total time: ~25 min | Interchanges: 0\n\n"
                "♿ All suggested routes are step-free. Please verify lift status\n"
                "at mtr.com.hk before travelling.\n\n"
                "[This is a mock response. Set DEEPSEEK_API_KEY, GEMINI_API_KEY, or ANTHROPIC_API_KEY for live LLM.]"
            )
        elif "accessibility" in last_msg.lower():
            return (
                "[MOCK LLM RESPONSE]\n\n"
                "Accessibility check complete:\n"
                "✅ Station has lift-equipped exits\n"
                "✅ Tactile guide paths available\n"
                "✅ Audio announcements operational\n"
                "⚠️ One lift under maintenance — use alternative exit\n\n"
                "[This is a mock response. Set DEEPSEEK_API_KEY, GEMINI_API_KEY, or ANTHROPIC_API_KEY for live LLM.]"
            )
        else:
            return (
                "[MOCK LLM RESPONSE]\n\n"
                "I understand your query about Hong Kong accessible transit.\n"
                "To get real-time, detailed route guidance, please set your\n"
                "GEMINI_API_KEY or ANTHROPIC_API_KEY environment variable.\n\n"
                "[Mock mode active — no LLM API key configured.]"
            )
