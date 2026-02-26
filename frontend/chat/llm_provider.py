"""
PharmaPulse — LLM Provider Abstraction Layer

Provides a unified interface for different LLM backends:
  - AnthropicProvider: Uses Claude API (requires ANTHROPIC_API_KEY)
  - MockProvider: Returns canned responses for testing without API keys

Each provider implements:
  - chat(messages, tools, system_prompt) -> LLMResponse
  - stream_chat(messages, tools, system_prompt) -> AsyncIterator[LLMChunk]

The factory function get_provider() selects the appropriate provider based on
available API keys and user preference.
"""

import os
import json
import logging
from dataclasses import dataclass, field
from typing import Optional, AsyncIterator
from abc import ABC, abstractmethod

logger = logging.getLogger("pharmapulse.chat")


# ---------------------------------------------------------------------------
# Data classes for unified LLM interface
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    """Represents a tool call requested by the LLM."""
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class LLMChunk:
    """A single chunk from a streaming LLM response."""
    delta_text: str = ""
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input_delta: str = ""
    is_final: bool = False
    stop_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Abstract Base Provider
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system_prompt: str = "",
    ) -> LLMResponse:
        """Send messages and get a response (non-streaming)."""
        ...

    @abstractmethod
    def get_name(self) -> str:
        """Return provider name for display."""
        ...


# ---------------------------------------------------------------------------
# Anthropic Provider (Claude)
# ---------------------------------------------------------------------------

class AnthropicProvider(LLMProvider):
    """
    LLM provider using Anthropic's Claude API.

    Requires ANTHROPIC_API_KEY environment variable.
    Supports function calling via Claude's native tool_use feature.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
    ):
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic package not installed. Run: pip install anthropic"
            )

        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not set. Set it in environment or pass api_key."
            )

        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = model
        self.max_tokens = max_tokens

    def get_name(self) -> str:
        return f"Claude ({self.model})"

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system_prompt: str = "",
    ) -> LLMResponse:
        """Send a chat request to Claude with optional tool definitions."""

        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = tools

        try:
            response = self.client.messages.create(**kwargs)
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            return LLMResponse(
                content=f"Error calling Claude API: {e}",
                stop_reason="error",
            )

        # Parse response
        content_text = ""
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                    )
                )

        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason or "end_turn",
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            raw={"id": response.id, "model": response.model},
        )


# ---------------------------------------------------------------------------
# Mock Provider (for testing without API key)
# ---------------------------------------------------------------------------

class MockProvider(LLMProvider):
    """
    Mock LLM provider for testing.

    Instead of calling an LLM, it recognizes simple patterns in user messages
    and returns tool calls or canned text responses. This enables full end-to-end
    testing of the chat pipeline without any API key.
    """

    def get_name(self) -> str:
        return "Mock AI (testing mode)"

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system_prompt: str = "",
    ) -> LLMResponse:
        """Pattern-match user message to generate a mock response."""

        # Get the last user message
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                if isinstance(msg.get("content"), str):
                    last_user_msg = msg["content"].lower()
                elif isinstance(msg.get("content"), list):
                    for block in msg["content"]:
                        if isinstance(block, dict) and block.get("type") == "text":
                            last_user_msg = block["text"].lower()
                            break
                break

        # Check if this is a tool_result message (continue after tool call)
        last_msg = messages[-1] if messages else {}
        if last_msg.get("role") == "tool":
            # After tool result, provide a summary
            return LLMResponse(
                content=(
                    "Here are the results from the analysis. "
                    "The data has been retrieved successfully. "
                    "Would you like me to run any further analysis or explore "
                    "different scenarios?"
                ),
                stop_reason="end_turn",
            )

        # Pattern matching for common requests
        if any(kw in last_user_msg for kw in ["list asset", "show asset", "all asset", "show me"]):
            return LLMResponse(
                content="Let me fetch the asset list for you.",
                tool_calls=[
                    ToolCall(
                        id="mock_tc_1",
                        name="list_assets",
                        arguments={},
                    )
                ],
                stop_reason="tool_use",
            )

        if any(kw in last_user_msg for kw in ["list portfolio", "show portfolio", "my portfolio"]):
            return LLMResponse(
                content="Let me look up your portfolios.",
                tool_calls=[
                    ToolCall(
                        id="mock_tc_2",
                        name="list_portfolios",
                        arguments={},
                    )
                ],
                stop_reason="tool_use",
            )

        if "npv" in last_user_msg and any(kw in last_user_msg for kw in ["run", "calc", "compute"]):
            # Try to extract snapshot_id from message
            import re
            nums = re.findall(r'\d+', last_user_msg)
            snap_id = int(nums[0]) if nums else 1
            return LLMResponse(
                content=f"Running deterministic NPV for snapshot {snap_id}.",
                tool_calls=[
                    ToolCall(
                        id="mock_tc_3",
                        name="run_deterministic_npv",
                        arguments={"snapshot_id": snap_id},
                    )
                ],
                stop_reason="tool_use",
            )

        if "monte carlo" in last_user_msg:
            import re
            nums = re.findall(r'\d+', last_user_msg)
            snap_id = int(nums[0]) if nums else 1
            return LLMResponse(
                content=f"Running Monte Carlo simulation for snapshot {snap_id}.",
                tool_calls=[
                    ToolCall(
                        id="mock_tc_4",
                        name="run_monte_carlo",
                        arguments={"snapshot_id": snap_id},
                    )
                ],
                stop_reason="tool_use",
            )

        if any(kw in last_user_msg for kw in ["kill", "cancel"]) and "project" in last_user_msg:
            return LLMResponse(
                content=(
                    "I can help analyze the impact of killing a project. "
                    "Could you specify the portfolio ID and the asset ID you'd like to analyze?"
                ),
                stop_reason="end_turn",
            )

        if any(kw in last_user_msg for kw in ["concentration", "risk analysis"]):
            return LLMResponse(
                content="Let me run a concentration risk analysis.",
                tool_calls=[
                    ToolCall(
                        id="mock_tc_5",
                        name="get_concentration_analysis",
                        arguments={"portfolio_id": 1},
                    )
                ],
                stop_reason="tool_use",
            )

        if "simulate" in last_user_msg and "portfolio" in last_user_msg:
            import re
            nums = re.findall(r'\d+', last_user_msg)
            pid = int(nums[0]) if nums else 1
            return LLMResponse(
                content=f"Running portfolio simulation for portfolio {pid}.",
                tool_calls=[
                    ToolCall(
                        id="mock_tc_6",
                        name="run_portfolio_simulation",
                        arguments={"portfolio_id": pid},
                    )
                ],
                stop_reason="tool_use",
            )

        if any(kw in last_user_msg for kw in ["hello", "hi", "hey"]):
            return LLMResponse(
                content=(
                    "Hello! I'm PharmaPulse AI, your pharmaceutical R&D portfolio analyst. "
                    "I can help you with:\n\n"
                    "- **Portfolio Overview**: List and explore your drug assets\n"
                    "- **NPV Calculations**: Run deterministic or Monte Carlo valuations\n"
                    "- **What-If Analysis**: Simulate kill/accelerate scenarios\n"
                    "- **Strategy Insights**: Concentration risk, TA budget, temporal balance\n\n"
                    "What would you like to explore?"
                ),
                stop_reason="end_turn",
            )

        # Default response
        return LLMResponse(
            content=(
                "I can help you analyze your pharmaceutical R&D portfolio. "
                "Here are some things you can ask me:\n\n"
                "- **\"Show me all assets\"** — List all drug assets\n"
                "- **\"List my portfolios\"** — Show portfolio summaries\n"
                "- **\"Run NPV for snapshot 1\"** — Calculate deterministic rNPV\n"
                "- **\"Run Monte Carlo for snapshot 1\"** — Probabilistic simulation\n"
                "- **\"Simulate portfolio 1\"** — Run full portfolio simulation\n"
                "- **\"Concentration risk analysis\"** — Check portfolio diversification\n\n"
                "What would you like to do?"
            ),
            stop_reason="end_turn",
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_provider(
    provider_name: str = "auto",
    api_key: str | None = None,
    model: str = "claude-sonnet-4-20250514",
) -> LLMProvider:
    """
    Get an LLM provider instance.

    Args:
        provider_name: "anthropic", "mock", or "auto" (tries Anthropic first, falls back to mock)
        api_key: Optional API key override
        model: Model name for Anthropic

    Returns:
        An LLMProvider instance
    """
    if provider_name == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model)
    elif provider_name == "mock":
        return MockProvider()
    elif provider_name == "auto":
        # Try Anthropic first
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if key:
            try:
                return AnthropicProvider(api_key=key, model=model)
            except Exception as e:
                logger.warning(f"Anthropic unavailable ({e}), falling back to mock")
                return MockProvider()
        else:
            logger.info("No ANTHROPIC_API_KEY found, using mock provider")
            return MockProvider()
    else:
        raise ValueError(f"Unknown provider: {provider_name}. Use 'anthropic', 'mock', or 'auto'.")

