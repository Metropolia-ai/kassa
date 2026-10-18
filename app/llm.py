"""LLM provider switch. Two backends behind one interface:
- "openai": any OpenAI-compatible endpoint (OpenRouter by default) via the openai SDK, function calling.
- "anthropic": Claude via the anthropic SDK, tool use.
Selection by env: OPENROUTER_API_KEY or OPENAI_API_KEY -> openai; ANTHROPIC_API_KEY -> anthropic; none -> rules."""
from __future__ import annotations

import json
import os
from typing import Any, Callable


def provider() -> str | None:
    if os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def model_name(kind: str = "chat") -> str:
    """kind: "chat" (agent loop) or "extract" (structured extraction, can be a cheaper model)."""
    if kind == "extract" and os.environ.get("LLM_EXTRACT_MODEL"):
        return os.environ["LLM_EXTRACT_MODEL"]
    return os.environ.get("LLM_MODEL") or os.environ.get("ANTHROPIC_MODEL") or "openai/gpt-6-luna"


def _openai_client():
    from openai import OpenAI
    key = os.environ.get("OPENROUTER_API_KEY") or os.environ["OPENAI_API_KEY"]
    base = os.environ.get("OPENAI_BASE_URL") or ("https://openrouter.ai/api/v1" if os.environ.get("OPENROUTER_API_KEY") else None)
    headers = {"HTTP-Referer": "https://github.com/frappua/kassa", "X-Title": "Kassa"} if base and "openrouter" in base else None
    return OpenAI(api_key=key, base_url=base, default_headers=headers)


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                               "parameters": t["input_schema"]}} for t in tools]


# --- structured extraction -------------------------------------------------
def call_tool_once(system: str, user_text: str, tool: dict) -> dict:
    """Force one call of `tool` and return its arguments as a dict."""
    p = provider()
    if p == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        msg = client.messages.create(model=model_name("extract"), max_tokens=1500, system=system, tools=[tool],
                                     tool_choice={"type": "tool", "name": tool["name"]},
                                     messages=[{"role": "user", "content": user_text}])
        for b in msg.content:
            if b.type == "tool_use" and b.name == tool["name"]:
                return dict(b.input)
        raise RuntimeError("model did not call the tool")
    if p == "openai":
        client = _openai_client()
        resp = client.chat.completions.create(
            model=model_name("extract"), max_tokens=1500,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_text}],
            tools=_to_openai_tools([tool]),
            tool_choice={"type": "function", "function": {"name": tool["name"]}})
        calls = resp.choices[0].message.tool_calls or []
        if not calls:  # some routers ignore tool_choice: fall back to JSON in content
            txt = resp.choices[0].message.content or ""
            start, end = txt.find("{"), txt.rfind("}")
            if start >= 0 and end > start:
                return json.loads(txt[start:end + 1])
            raise RuntimeError("model did not call the tool")
        return json.loads(calls[0].function.arguments or "{}")
    raise RuntimeError("no LLM provider configured")


# --- agent loop --------------------------------------------------------------
def run_agent(system: str, history: list[dict], user_text: str, tools: list[dict],
              run_tool: Callable[[str, dict], Any], max_rounds: int = 8) -> str:
    """history: [{role: user|assistant, content: str}]. Returns final assistant text."""
    p = provider()
    if p == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        messages = history + [{"role": "user", "content": user_text}]
        for _ in range(max_rounds):
            resp = client.messages.create(model=model_name(), max_tokens=1200, system=system, tools=tools, messages=messages)
            messages.append({"role": "assistant", "content": resp.content})
            uses = [b for b in resp.content if b.type == "tool_use"]
            if not uses:
                return "".join(b.text for b in resp.content if b.type == "text").strip() or "(no answer)"
            results = []
            for tu in uses:
                try:
                    out = run_tool(tu.name, dict(tu.input))
                    results.append({"type": "tool_result", "tool_use_id": tu.id, "content": _dump(out)})
                except Exception as e:
                    results.append({"type": "tool_result", "tool_use_id": tu.id, "content": f"error: {e}", "is_error": True})
            messages.append({"role": "user", "content": results})
        return "Stopped after too many tool calls."
    if p == "openai":
        client = _openai_client()
        messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": user_text}]
        oa_tools = _to_openai_tools(tools)
        for _ in range(max_rounds):
            resp = client.chat.completions.create(model=model_name(), max_tokens=1200, messages=messages,
                                                  tools=oa_tools, tool_choice="auto")
            m = resp.choices[0].message
            calls = m.tool_calls or []
            if not calls:
                return (m.content or "").strip() or "(no answer)"
            messages.append({"role": "assistant", "content": m.content or "",
                             "tool_calls": [{"id": c.id, "type": "function",
                                             "function": {"name": c.function.name, "arguments": c.function.arguments}} for c in calls]})
            for c in calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                    out = run_tool(c.function.name, args)
                    content = _dump(out)
                except Exception as e:
                    content = f"error: {e}"
                messages.append({"role": "tool", "tool_call_id": c.id, "content": content})
        return "Stopped after too many tool calls."
    raise RuntimeError("no LLM provider configured")


def _dump(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)[:12000]
