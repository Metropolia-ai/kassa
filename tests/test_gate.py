import importlib, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_client(monkeypatch, tmp_path, **env):
    for k in ("ACCESS_KEY", "CRON_SECRET", "VERCEL", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
              "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "DATABASE_URL"):
        monkeypatch.setenv(k, "")
    monkeypatch.setenv("KASSA_DB", str(tmp_path / "g.db"))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: None)
    import app.main as m
    m = importlib.reload(m)
    from fastapi.testclient import TestClient
    return TestClient(m.app)


def test_gate_blocks_without_key(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path, ACCESS_KEY="s3cret", CRON_SECRET="cron1")
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/bills").status_code == 401
    assert c.post("/api/chat", json={"message": "hi"}).status_code == 401
    assert c.get("/api/bills", headers={"X-Kassa-Key": "wrong"}).status_code == 401
    assert c.get("/api/bills", headers={"X-Kassa-Key": "s3cret"}).status_code == 200
    assert c.get("/api/refresh", headers={"Authorization": "Bearer cron1"}).status_code == 200
    assert c.get("/api/bills", headers={"Authorization": "Bearer cron1"}).status_code == 401  # cron secret only for refresh
    assert c.get("/").status_code == 200  # page itself is public


def test_fail_closed_on_vercel(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path, VERCEL="1")
    assert c.get("/api/bills").status_code == 503
