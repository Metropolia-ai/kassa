"""Kassa x Kassa without PayPal or a model: the policy engine alone must walk every scenario to its end."""
import os

import pytest

from app.agent import Kassa
from app.duet import Company, Duet
from app.store import Store


@pytest.fixture
def duet(tmp_path, monkeypatch):
    for k in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DATABASE_URL", "DUET_BUYER", "DUET_SUPPLIER"):
        monkeypatch.delenv(k, raising=False)
    db = str(tmp_path / "duet.db")
    buyer = Company("frappua", "Frappua", "pay@frappua.example", Kassa(Store(db, schema="co_frappua"), None,
                    merchant_email="pay@frappua.example", merchant_name="Frappua", auto_pay_limit=500),
                    owner="Dima", staff=["Alena Mima", "Erik Sindonen"])
    sup = Company("pixelforge", "Pixelforge Oy", "ar@pixelforge.example", Kassa(Store(db, schema="co_pixelforge"), None,
                  merchant_email="ar@pixelforge.example", merchant_name="Pixelforge Oy", auto_pay_limit=500),
                  owner="Mika")
    return Duet(db, {"frappua": buyer, "pixelforge": sup})


def run(d, tid, max_steps=12):
    out = None
    for _ in range(max_steps):
        out = d.step(tid)
        if not out["changed"] or out["status"] in ("needs_humans", "settled", "closed", "failed"):
            break
    return out


def actions(t):
    return [(m["company"], m["author"], m["action"]) for m in t["messages"] if m["company"] != "system"]


def test_extra_hours_settles_without_people(duet):
    t = duet.start("extra-hours")
    assert t["status"] == "new" and t["invoice_amount"] == 337.0
    t = run(duet, t["id"])
    assert t["status"] == "settled"
    assert t["agreed_amount"] == 337.0
    assert t["outcome"] == "settled by the agents alone"
    acts = [a for _, _, a in actions(t)]
    assert acts == ["invoice", "query", "explain", "accept", "paid", "settled"]
    assert all(author == "agent" for _, author, _ in actions(t))
    bill = duet.companies["frappua"].kassa.store.list_bills()[0]
    assert bill["status"] == "paid" and bill["amount"] == 337.0
    assert "Alena Mima" in bill["reason"]


def test_scope_doubled_needs_both_owners(duet):
    t = run(duet, duet.start("scope-doubled")["id"])
    assert t["status"] == "needs_humans" and t["waiting"] == "frappua"
    acts = [a for _, _, a in actions(t)]
    # supplier offers 10 % off (2160), buyer may go to 1200 + min(10 %, 150) = 1320, supplier names its floor (1800),
    # buyer's agent has used its one counter: the buyer's owner decides
    assert acts == ["invoice", "query", "counter", "counter", "counter", "escalate"]
    opts = t["decisions"][0]["options"]
    assert any(o.get("amount") == 1800.0 for o in opts) and any(o.get("amount") == 1200.0 for o in opts)
    # the owner offers 1800: the supplier's floor is 75 % of 2400 = 1800, so its agent accepts
    t = duet.decide(t["id"], "frappua", "pay", 1800)
    assert t["status"] == "proposed"
    t = run(duet, t["id"])
    assert t["status"] == "settled" and t["agreed_amount"] == 1800.0
    assert t["outcome"] == "settled after the owners decided"
    assert t["invoice_number"].endswith("R")  # reissued for the agreed amount
    assert any(a == "reissue" for _, _, a in actions(t))


def test_scope_doubled_low_offer_goes_to_supplier_owner(duet):
    t = run(duet, duet.start("scope-doubled")["id"])
    t = duet.decide(t["id"], "frappua", "pay", 1500)
    t = run(duet, t["id"])
    assert t["status"] == "needs_humans" and t["waiting"] == "pixelforge"
    t = duet.decide(t["id"], "pixelforge", "accept", 1500)
    t = run(duet, t["id"])
    assert t["status"] == "settled" and t["agreed_amount"] == 1500.0


def test_owner_can_reject(duet):
    t = run(duet, duet.start("scope-doubled")["id"])
    t = duet.decide(t["id"], "frappua", "reject")
    t = run(duet, t["id"])
    assert t["status"] == "closed"
    assert duet.companies["frappua"].kassa.store.list_bills()[0]["status"] == "rejected"


def test_duplicate_is_refused_and_withdrawn(duet):
    first = run(duet, duet.start("extra-hours")["id"])
    t = run(duet, duet.start("duplicate")["id"])
    assert t["invoice_number"] != first["invoice_number"]  # a new number for the same work
    assert t["status"] == "closed"
    assert [a for _, _, a in actions(t)] == ["invoice", "query", "withdraw"]
    assert first["invoice_number"] in t["outcome"]
    bills = duet.companies["frappua"].kassa.store.list_bills()
    assert bills[0]["status"] == "rejected" and "withdrawn" in bills[0]["reason"]


def test_duplicate_alone_seeds_the_original(duet):
    t = run(duet, duet.start("duplicate")["id"])
    assert t["status"] == "closed"
    bills = duet.companies["frappua"].kassa.store.list_bills()
    assert {b["status"] for b in bills} == {"paid", "rejected"}


def test_policy_knobs_change_the_outcome(duet):
    duet.set_policy("frappua", {"tolerance_pct": 30, "tolerance_abs": 500})
    t = run(duet, duet.start("extra-hours")["id"])
    # 65 over a 272 order is now inside the plain tolerance: no query at all
    assert [a for _, _, a in actions(t)] == ["invoice", "accept", "paid", "settled"]


def test_reset_clears_everything(duet):
    run(duet, duet.start("extra-hours")["id"])
    duet.reset()
    assert duet.list_threads() == []
    assert duet.companies["frappua"].kassa.store.list_bills() == []
