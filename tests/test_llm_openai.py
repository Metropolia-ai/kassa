import json, os, sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import llm  # noqa: E402


class FakeChat:
    def __init__(self, script):
        self.script = list(script); self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        step = self.script.pop(0)
        if "tool" in step:
            name, args = step["tool"]
            tc = SimpleNamespace(id="c1", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
            msg = SimpleNamespace(content=None, tool_calls=[tc])
        else:
            msg = SimpleNamespace(content=step["text"], tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def test_openai_agent_loop(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x"); monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    fake = FakeChat([{"tool": ("list_bills", {"status": "approved"})}, {"text": "2 approved bills, total 443.45 EUR."}])
    monkeypatch.setattr(llm, "_openai_client", lambda: SimpleNamespace(chat=SimpleNamespace(completions=fake)))
    seen = []
    out = llm.run_agent("sys", [], "what is approved?", [{"name": "list_bills", "description": "", "input_schema": {"type": "object", "properties": {}}}],
                        lambda n, a: seen.append((n, a)) or [{"id": 1}, {"id": 2}])
    assert out.startswith("2 approved") and seen == [("list_bills", {"status": "approved"})]
    assert fake.calls[1]["messages"][-1]["role"] == "tool"


def test_openai_forced_tool(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    fake = FakeChat([{"tool": ("record_invoice", {"amount": 12.5, "currency": "EUR"})}])
    monkeypatch.setattr(llm, "_openai_client", lambda: SimpleNamespace(chat=SimpleNamespace(completions=fake)))
    out = llm.call_tool_once("s", "u", {"name": "record_invoice", "description": "", "input_schema": {"type": "object", "properties": {}}})
    assert out["amount"] == 12.5 and fake.calls[0]["tool_choice"]["function"]["name"] == "record_invoice"
