"""
Base Agent — the shared "Agent Loop" that all agents inherit.

Every agent runs: Perceive → Think → Act (call tools) → Observe → Iterate
This is the core loop from Day 1 Section 1.2.

Each agent has:
  Model (LLM) → decides what to do next
  Tools (MCP + local) → actions the agent can take
  Memory → session context
  Orchestration → this loop
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Optional

from .llm_client import LLMClient
from .config import SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Base class for all agents in the system.

    Subclasses override:
      - system_prompt: the agent's role and rules
      - tools_schema: the tools this agent can call (JSON Schema list)
      - handle_tool(tool_name, args): execute a tool call and return result
    """

    def __init__(self, name: str, llm: LLMClient, tier: str = "light"):
        self.name = name
        self.llm = llm
        self.tier = tier  # "heavy" for complex, "light" for simple
        self.memory: list[dict] = []  # conversation/tool call history

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """The agent's role definition and rules."""
        ...

    @abstractmethod
    def get_tools(self) -> list[dict]:
        """Return tool schemas in OpenAI function-calling format."""
        ...

    @abstractmethod
    async def handle_tool(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool call and return the result string."""
        ...

    # ------------------------------------------------------------------
    # The Agent Loop — the heart of every agent
    # ------------------------------------------------------------------

    async def run(self, user_message: str, max_steps: int = 5) -> str:
        """Run the agent loop: Think → Act → Observe → (repeat).

        Args:
            user_message: The task/query to process
            max_steps: Maximum tool-calling iterations before giving up

        Returns:
            Final text response from the agent
        """
        self.memory = [{"role": "user", "content": user_message}]

        tools = self.get_tools()

        for step in range(max_steps):
            # THINK: Ask the LLM what to do next (with tools!)
            response = await self.llm.chat(
                messages=self.memory,
                system_prompt=self.system_prompt,
                tier=self.tier,
                tools=tools if tools else None,
            )

            # Check if the LLM wants to call a tool
            tool_call = self._parse_tool_call(response)

            if tool_call:
                tool_name = tool_call["name"]
                tool_args = tool_call.get("arguments", {})

                logger.info(
                    f"[{self.name}] Step {step + 1}: calling {tool_name}({json.dumps(tool_args, ensure_ascii=False)[:100]})"
                )

                # ACT: Execute the tool
                try:
                    tool_result = await self.handle_tool(tool_name, tool_args)
                except Exception as e:
                    tool_result = json.dumps({"error": str(e)})

                # OBSERVE: Feed the result back into the agent's memory
                self.memory.append({"role": "assistant", "content": response})
                self.memory.append({
                    "role": "user",
                    "content": f"Tool result from {tool_name}:\n{tool_result}\n\n"
                               f"Based on this result, what's your next step? "
                               f"If you have enough information, provide your final answer. "
                               f"Otherwise, call another tool.",
                })

            else:
                # No tool call → agent is done, return final answer
                logger.info(f"[{self.name}] finished after {step + 1} steps")
                return response

        # Max steps reached — return whatever we have
        logger.warning(f"[{self.name}] max steps ({max_steps}) reached")
        return await self.llm.chat(
            messages=self.memory + [{
                "role": "user",
                "content": "You've reached the maximum number of steps. "
                           "Please provide your final answer now based on what you've learned."
            }],
            system_prompt=self.system_prompt,
            tier=self.tier,
        )

    # ------------------------------------------------------------------
    # Tool call parsing — extracts function calls from LLM output
    # ------------------------------------------------------------------

    def _parse_tool_call(self, response: str) -> Optional[dict]:
        """Parse a tool call from the LLM's response.

        Supports three formats:
        1. Native function calling (DeepSeek/Gemini/Claude):
           {"tool_call": {"name": "...", "arguments": {...}}}
        2. JSON block: ```json\n{"tool": "name", "arguments": {...}}\n```
        3. FUNCTION_CALL marker for non-function-calling models
        """
        import re

        # Format 1: Native function calling (from llm_client)
        try:
            data = json.loads(response)
            if "tool_call" in data:
                tc = data["tool_call"]
                return {"name": tc["name"], "arguments": tc.get("arguments", {})}
        except (json.JSONDecodeError, TypeError):
            pass

        # Format 2: JSON code block
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1).strip())
                if "tool" in data:
                    return {"name": data["tool"], "arguments": data.get("arguments", {})}
                if "function" in data:
                    return {"name": data["function"], "arguments": data.get("arguments", {})}
            except json.JSONDecodeError:
                pass

        # Format 3: FUNCTION_CALL marker
        func_match = re.search(
            r'FUNCTION_CALL:\s*(\w+)\s*\(\s*(.*?)\s*\)', response, re.DOTALL
        )
        if func_match:
            tool_name = func_match.group(1)
            args_str = func_match.group(2).strip()
            try:
                args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                args = {"raw": args_str}
            return {"name": tool_name, "arguments": args}

        return None
