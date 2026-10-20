"""Kassa x Kassa without PayPal or a model: the policy engine alone must walk every scenario to its end."""
import os

import pytest

from app.agent import Kassa
from app.duet import Company, Duet
from app.store import Store


@pytest.fixture
def duet(tmp_path, monkeypatch):
    for k in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DATABASE_URL", "DUET_BUYER", "DUET_SUPPLIER",
              "DUET_RESEND_AFTER_S"):
        monkeypatch.delenv(k, raising=False)
    db = str(tmp_path / "duet.db")
    buyer = Company("frappua", "Frappua", "pay@frappua.example", Kassa(Store(db, schema="co_frappua"), None,
                    merchant_email="pay@frappua.example", merchant_name="Frappua", auto_pay_limit=500),
                    owner="Erik", staff=["Alena Mima", "Erik Sindonen"])
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
    assert t["outcome"].startswith("settled by the agents in") and t["outcome"].endswith("no one interrupted")
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
    assert "after the owner decided" in t["outcome"]
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


def test_reset_clears_threads_and_keeps_two_months_of_history(duet):
    run(duet, duet.start("extra-hours")["id"])
    duet.reset()
    assert duet.list_threads() == []
    bills = duet.companies["frappua"].kassa.store.list_bills()
    assert bills and all(b["status"] == "paid" for b in bills)          # seeded history only
    assert duet.companies["pixelforge"].kassa.store.list_customer_invoices()


def test_invoice_numbers_are_sequential_and_survive_reset(duet):
    a = duet.start("extra-hours")["invoice_number"]
    b = duet.start("scope-doubled")["invoice_number"]
    assert a == "PF-2026-0418" and b == "PF-2026-0419"
    duet.reset()
    assert duet.start("extra-hours")["invoice_number"] == "PF-2026-0420"


def test_supplier_sends_a_draft_and_the_clock_does_the_rest(duet):
    drafts = duet.drafts()
    assert [d["key"] for d in drafts] == ["extra-hours", "scope-doubled"]
    t = duet.send_draft("extra-hours")
    assert t["status"] == "invoiced"                                    # the invoice went out at once
    inv = duet.companies["pixelforge"].kassa.store.list_customer_invoices()[0]
    assert inv["invoice_number"] == t["invoice_number"] and inv["status"] == "SENT"
    for _ in range(10):
        if not duet.tick():
            break
    t = duet.get_thread(t["id"])
    assert t["status"] == "settled"
    mine = duet.threads_for("frappua")[-1]
    assert mine["role"] == "buyer" and mine["other"] == "Pixelforge Oy" and mine["humans"] == 0


def test_buyer_sees_the_bill_as_negotiating_then_waiting_for_the_owner(duet):
    t = duet.send_draft("scope-doubled")
    duet.tick(); duet.tick()
    bill = duet.companies["frappua"].kassa.store.get_bill(duet.get_thread(t["id"])["bill_id"])
    assert bill["status"] == "negotiating" and "checking with Pixelforge Oy" in bill["reason"]
    while duet.tick():
        pass
    bill = duet.companies["frappua"].kassa.store.get_bill(bill["id"])
    assert bill["status"] == "negotiating" and bill["reason"].startswith("waiting for Erik")
    assert duet.threads_for("frappua")[-1]["decisions"] and not duet.threads_for("pixelforge")[-1]["decisions"]


def test_chat_tool_explains_a_settlement(duet):
    t = duet.send_draft("extra-hours")
    while duet.tick():
        pass
    out = duet.companies["frappua"].kassa.run_tool("bill_conversation", {"invoice_number": t["invoice_number"]})
    assert out["agreed_amount"] == 337.0 and out["people_involved"] == 0
    assert any(m["action"] == "explain" for m in out["messages"])


def test_drafts_show_where_they_come_from(duet):
    drafts = duet.drafts()
    assert len(drafts) == 2                                              # the re-send is never a draft
    for d in drafts:
        assert d["source"].startswith("Drafted by Kassa from your")
        assert d["log"] and all(e["date"] and e["note"] for e in d["log"])
    hours = next(d for d in drafts if d["key"] == "extra-hours")["log"]
    assert sum(e["hours"] for e in hours) == 50


def test_a_sent_draft_leaves_ready_to_send(duet):
    duet.send_draft("extra-hours")
    assert [d["key"] for d in duet.drafts()] == ["scope-doubled"]
    duet.reset()
    assert [d["key"] for d in duet.drafts()] == ["extra-hours", "scope-doubled"]


def test_the_old_invoicing_system_resends_and_the_agents_withdraw_it(duet, monkeypatch):
    monkeypatch.setenv("DUET_RESEND_AFTER_S", "0")
    first = duet.send_draft("extra-hours")
    for _ in range(10):
        if duet.get_thread(first["id"])["status"] == "settled":
            break
        duet.tick()
    first = duet.get_thread(first["id"])
    assert first["status"] == "settled"
    assert not [t for t in duet.list_threads() if t["scenario"] == "duplicate"]
    duet.tick()                                                          # the re-send arrives by itself
    dups = [t for t in duet.list_threads() if t["scenario"] == "duplicate"]
    assert len(dups) == 1
    inv = dups[0]["messages"][0]
    assert inv["action"] == "invoice" and inv["data"]["auto"] is True
    assert "sent automatically" in inv["text"].lower() and "Pixelforge Oy" in inv["text"]
    for _ in range(10):
        duet.tick()
    t = duet.get_thread(dups[0]["id"])
    assert t["status"] == "closed" and first["invoice_number"] in t["outcome"]
    bill = duet.companies["frappua"].kassa.store.get_bill(t["bill_id"])
    assert bill["status"] == "rejected" and "withdrawn" in bill["reason"]
    assert bill["source"].endswith("(re-sent by their invoicing system)")
    row = next(r for r in duet.companies["pixelforge"].kassa.store.list_customer_invoices() if r["invoice_number"] == t["invoice_number"])
    assert row["memo"] == "Render farm, first half of October (re-sent automatically)"
    # it happens once: more ticks and direct calls never send it again
    assert duet.maybe_resend() is None
    duet.tick()
    assert len([t for t in duet.list_threads() if t["scenario"] == "duplicate"]) == 1


def test_no_resend_before_the_delay(duet):
    t = duet.send_draft("extra-hours")
    while duet.tick():
        pass
    assert duet.get_thread(t["id"])["status"] == "settled"
    assert duet.maybe_resend() is None                                   # 45 s have not passed
