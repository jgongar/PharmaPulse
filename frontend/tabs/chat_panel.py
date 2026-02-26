"""
Tab 6: AI Chat Panel — Conversational analytics powered by LLM.

Features:
- Natural language interaction with PharmaPulse data
- Automatic tool calling (LLM decides when to query backend)
- Tool call results displayed inline with expandable details
- Provider selector (Anthropic Claude or Mock for testing)
- Persistent chat history within session
- Suggested prompts for quick start
"""

import json
import streamlit as st
import logging

from frontend.chat.llm_provider import get_provider, LLMResponse, ToolCall
from frontend.chat.tool_definitions import TOOL_DEFINITIONS
from frontend.chat.tool_executor import execute_tool, format_tool_result_for_display
from mcp_server.system_prompt import SYSTEM_PROMPT

logger = logging.getLogger("pharmapulse.chat_panel")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUGGESTED_PROMPTS = [
    "Show me all internal assets",
    "List my portfolios",
    "Run NPV for snapshot 1",
    "Run Monte Carlo simulation for snapshot 1",
    "Simulate portfolio 1",
    "Show concentration risk analysis for portfolio 1",
    "What is the innovation score of portfolio 1?",
    "Show the TA budget efficiency for portfolio 1",
]

MAX_TOOL_ITERATIONS = 8  # Safety limit on tool call loops


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_chat_state():
    """Initialize session state for chat."""
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []
    if "chat_provider_name" not in st.session_state:
        st.session_state.chat_provider_name = "auto"
    if "chat_api_key" not in st.session_state:
        st.session_state.chat_api_key = ""
    if "chat_model" not in st.session_state:
        st.session_state.chat_model = "claude-sonnet-4-20250514"
    if "chat_processing" not in st.session_state:
        st.session_state.chat_processing = False


def _get_provider():
    """Get the configured LLM provider."""
    return get_provider(
        provider_name=st.session_state.chat_provider_name,
        api_key=st.session_state.chat_api_key or None,
        model=st.session_state.chat_model,
    )


def _build_llm_messages(chat_messages: list[dict]) -> list[dict]:
    """
    Convert our internal chat_messages to the format expected by the LLM provider.

    Our internal format stores:
      - {"role": "user", "content": "..."}
      - {"role": "assistant", "content": "...", "tool_calls": [...]}
      - {"role": "tool", "tool_call_id": "...", "name": "...", "content": "..."}

    For Anthropic, we need to convert tool messages to the proper format.
    """
    llm_messages = []

    for msg in chat_messages:
        role = msg["role"]

        if role == "user":
            llm_messages.append({"role": "user", "content": msg["content"]})

        elif role == "assistant":
            # Build content blocks
            content_blocks = []
            if msg.get("content"):
                content_blocks.append({"type": "text", "text": msg["content"]})
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["arguments"],
                    })
            if content_blocks:
                llm_messages.append({"role": "assistant", "content": content_blocks})

        elif role == "tool":
            # Anthropic expects tool results as user messages with tool_result blocks
            # Group consecutive tool results into one user message
            tool_result_block = {
                "type": "tool_result",
                "tool_use_id": msg["tool_call_id"],
                "content": msg["content"],
            }
            # Check if we can append to the previous user message
            if llm_messages and llm_messages[-1]["role"] == "user" and isinstance(llm_messages[-1]["content"], list):
                llm_messages[-1]["content"].append(tool_result_block)
            else:
                llm_messages.append({
                    "role": "user",
                    "content": [tool_result_block],
                })

    return llm_messages


def _process_user_message(user_text: str):
    """
    Process a user message through the full LLM pipeline:
    1. Add user message to history
    2. Call LLM with message history + tools
    3. If LLM requests tool calls, execute them and loop
    4. Display final response
    """
    # Add user message
    st.session_state.chat_messages.append({
        "role": "user",
        "content": user_text,
    })

    # Get provider
    try:
        provider = _get_provider()
    except Exception as e:
        st.session_state.chat_messages.append({
            "role": "assistant",
            "content": f"Error initializing LLM provider: {e}",
        })
        return

    # LLM loop (handles tool calls)
    iterations = 0
    while iterations < MAX_TOOL_ITERATIONS:
        iterations += 1

        # Build messages for LLM
        llm_messages = _build_llm_messages(st.session_state.chat_messages)

        # Call LLM
        response: LLMResponse = provider.chat(
            messages=llm_messages,
            tools=TOOL_DEFINITIONS,
            system_prompt=SYSTEM_PROMPT,
        )

        if response.has_tool_calls:
            # Store assistant message with tool calls
            st.session_state.chat_messages.append({
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                    }
                    for tc in response.tool_calls
                ],
            })

            # Execute each tool call
            for tc in response.tool_calls:
                result = execute_tool(tc.name, tc.arguments)
                result_text = format_tool_result_for_display(tc.name, result)
                st.session_state.chat_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": result_text,
                })

            # Continue loop — LLM will see tool results and respond
            continue

        else:
            # No tool calls — final text response
            st.session_state.chat_messages.append({
                "role": "assistant",
                "content": response.content,
            })
            break

    if iterations >= MAX_TOOL_ITERATIONS:
        st.session_state.chat_messages.append({
            "role": "assistant",
            "content": "I've reached the maximum number of tool calls for this turn. Please try a more specific request.",
        })


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _display_tool_call(tc_data: dict, index: int):
    """Display a tool call block in the chat."""
    name = tc_data.get("name", "unknown")
    args = tc_data.get("arguments", {})
    with st.expander(f"🔧 Called `{name}`", expanded=False):
        st.code(json.dumps(args, indent=2), language="json")


def _display_tool_result(msg: dict, index: int):
    """Display a tool result block in the chat."""
    name = msg.get("name", "tool")
    content = msg.get("content", "")
    with st.expander(f"📊 Result from `{name}`", expanded=False):
        # Try to parse as JSON for nice display
        try:
            parsed = json.loads(content)
            st.json(parsed)
        except (json.JSONDecodeError, TypeError):
            st.code(content, language="text")


def _display_message(msg: dict, index: int):
    """Display a single chat message."""
    role = msg["role"]

    if role == "user":
        with st.chat_message("user", avatar="👤"):
            st.markdown(msg["content"])

    elif role == "assistant":
        with st.chat_message("assistant", avatar="💊"):
            # Show any text content
            if msg.get("content"):
                st.markdown(msg["content"])
            # Show tool calls if any
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    _display_tool_call(tc, index)

    elif role == "tool":
        # Tool results — show as collapsed section
        _display_tool_result(msg, index)


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render():
    """Render the AI Chat Panel tab."""

    _init_chat_state()

    st.subheader("AI Chat Panel")
    st.markdown(
        "Ask questions about your portfolio in natural language. "
        "The AI can query data, run simulations, and provide strategic insights."
    )

    # ----- Sidebar configuration -----
    with st.expander("⚙️ Chat Settings", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            provider_choice = st.selectbox(
                "LLM Provider",
                ["auto", "anthropic", "mock"],
                index=["auto", "anthropic", "mock"].index(
                    st.session_state.chat_provider_name
                ),
                key="chat_provider_selector",
                help="'auto' tries Anthropic first, falls back to mock for testing",
            )
            if provider_choice != st.session_state.chat_provider_name:
                st.session_state.chat_provider_name = provider_choice

        with col2:
            model_choice = st.selectbox(
                "Model",
                [
                    "claude-sonnet-4-20250514",
                    "claude-3-5-sonnet-20241022",
                    "claude-3-5-haiku-20241022",
                ],
                index=0,
                key="chat_model_selector",
            )
            if model_choice != st.session_state.chat_model:
                st.session_state.chat_model = model_choice

        api_key_input = st.text_input(
            "Anthropic API Key (optional — overrides env var)",
            value=st.session_state.chat_api_key,
            type="password",
            key="chat_api_key_input",
            help="Leave blank to use ANTHROPIC_API_KEY environment variable",
        )
        if api_key_input != st.session_state.chat_api_key:
            st.session_state.chat_api_key = api_key_input

        # Show current provider info
        try:
            provider = _get_provider()
            st.success(f"Active provider: **{provider.get_name()}**")
        except Exception as e:
            st.warning(f"Provider error: {e}")

        # Clear chat button
        if st.button("🗑️ Clear Chat History", use_container_width=True):
            st.session_state.chat_messages = []
            st.rerun()

    # ----- Suggested prompts -----
    if not st.session_state.chat_messages:
        st.markdown("#### 💡 Try asking:")
        cols = st.columns(2)
        for i, prompt in enumerate(SUGGESTED_PROMPTS):
            with cols[i % 2]:
                if st.button(
                    prompt,
                    key=f"suggested_{i}",
                    use_container_width=True,
                ):
                    st.session_state.chat_processing = True
                    _process_user_message(prompt)
                    st.session_state.chat_processing = False
                    st.rerun()

    # ----- Chat history display -----
    chat_container = st.container()
    with chat_container:
        for i, msg in enumerate(st.session_state.chat_messages):
            _display_message(msg, i)

    # ----- Chat input -----
    user_input = st.chat_input(
        "Ask about your portfolio...",
        key="chat_user_input",
    )

    if user_input:
        st.session_state.chat_processing = True
        _process_user_message(user_input)
        st.session_state.chat_processing = False
        st.rerun()

