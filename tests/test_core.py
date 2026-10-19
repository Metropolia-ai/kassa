import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.pop("ANTHROPIC_API_KEY", None)

import pytest  # noqa: E402

from app import policy  # noqa: E402
from app.agent import Kassa  # noqa: E402
from app.extract import extract_rules  # noqa: E402
from app.paypal_client import PayPalClient, PayPalConfig  # noqa: E402
from app.store import Store  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


class FakePayPal(PayPalClient):
    def __init__(self):
        super().__init__(PayPalConfig("id", "secret"))
        self.payouts = []

    def create_payout(self, receiver_email, amount, currency, note, sender_item_id, batch_id=None, subject=""):
        self.payouts.append((receiver_email, amount, currency))
        return {"batch_header": {"payout_batch_id": f"B{len(self.payouts)}", "batch_status": "PENDING"}}

    def get_payout(self, payout_batch_id):
        return {"batch_header": {"batch_status": "SUCCESS"}, "items": [{"transaction_status": "SUCCESS", "payout_item_id": "I1"}]}

    def create_invoice(self, **kw):
        return {"id": "INV2-TEST", "status": "DRAFT", "detail": {"invoice_number": "0001"}}

    def send_invoice(self, invoice_id, subject=None, note=None):
        return {}

    def get_invoice(self, invoice_id):
        return {"id": invoice_id, "status": "SENT", "links": [{"rel": "payer-view", "href": "https://sandbox.paypal.com/invoice/p/INV2-TEST"}]}


@pytest.fixture
def kassa(tmp_path):
    return Kassa(Store(str(tmp_path / "t.db")), FakePayPal(), merchant_email="m@example.com",
                 merchant_name="Test Oy", auto_pay_limit=500)


def read(name):
    return (SAMPLES / name).read_text(encoding="utf-8")


def test_rules_extract_total_and_email():
    d = extract_rules(read("01-pixelforge-render.txt"))
    assert d["amount"] == 325.05 and d["currency"] == "EUR"
    assert d["supplier_email"] == "sb-zkzff53386438@personal.example.com"
    assert d["invoice_number"] == "PF-2026-0412"


def test_rules_extract_finnish():
    d = extract_rules(read("02-nordic-voice-studio.txt"))
    assert d["amount"] == 940.0 and d["invoice_number"] == "NVS-887"


def test_policy_limits():
    bill = {"amount": 600, "currency": "EUR", "supplier_email": "a@b.c", "invoice_number": "1", "confidence": 0.9}
    d = policy.evaluate(bill, auto_pay_limit=500, supplier={"trusted": 1}, duplicate=None)
    assert d.status == "needs_approval" and "above auto-pay limit" in d.reason
    d = policy.evaluate({**bill, "amount": 100}, auto_pay_limit=500, supplier={"trusted": 1}, duplicate=None)
    assert d.status == "approved"
    d = policy.evaluate(bill, auto_pay_limit=500, supplier=None, duplicate={"id": 7})
    assert d.status == "rejected"


def test_pipeline_first_invoice_needs_approval_then_trusted_autopays(kassa):
    b1 = kassa.ingest("01", read("01-pixelforge-render.txt"))
    assert b1["status"] == "needs_approval" and "first invoice" in b1["reason"]
    with pytest.raises(PermissionError):
        kassa.pay_bill(b1["id"])  # agent cannot pay unapproved
    b1 = kassa.approve(b1["id"], trust_supplier=True)
    assert b1["status"] == "approved"
    b1 = kassa.pay_bill(b1["id"])
    assert b1["status"] == "sent" and b1["payout_batch_id"] == "B1"
    # duplicate is rejected
    b3 = kassa.ingest("03", read("03-pixelforge-duplicate.txt"))
    assert b3["status"] == "rejected" and "duplicate" in b3["reason"]
    # same supplier, new number, same amount -> held as a possible duplicate
    b4 = kassa.ingest("04", read("01-pixelforge-render.txt").replace("PF-2026-0412", "PF-2026-0413"))
    assert b4["status"] == "needs_approval" and "possible duplicate" in b4["reason"]
    # same supplier, new number, different amount, under limit -> auto approved
    text = read("01-pixelforge-render.txt").replace("PF-2026-0412", "PF-2026-0414").replace("325.05", "225.05")
    b4 = kassa.ingest("05", text)
    assert b4["status"] == "approved"
    assert kassa.refresh_payouts() == [{"id": b1["id"], "payout_status": "SUCCESS", "status": "paid"}]
    assert kassa.store.get_bill(b1["id"])["status"] == "paid"


def test_suspicious_email_is_held(kassa):
    b = kassa.ingest("05", read("05-suspicious-urgent.txt"))
    assert b["status"] == "needs_approval"


def test_customer_invoice_and_audit(kassa):
    r = kassa.create_customer_invoice(customer_name="Acme", customer_email="c@example.com",
                                      items=[{"name": "Pilot", "unit_amount": 1500}], reason="test")
    assert r["status"] == "SENT" and r["pay_url"].startswith("https://")
    tools = [a["tool"] for a in kassa.store.list_audit()]
    assert "create_customer_invoice" in tools and "send_customer_invoice" in tools


def test_rules_chat(kassa):
    kassa.ingest("01", read("01-pixelforge-render.txt"))
    assert "Pixelforge" in kassa.chat("list bills")
    assert "Sent 0" in kassa.chat("pay approved bills")


def test_trusted_supplier_autopays_even_if_overdue(kassa):
    kassa.store.upsert_supplier("ar@cloudbox.example.net", "Cloudbox Hosting", trusted=True)
    b = kassa.ingest("04", read("04-cloudbox-hosting.txt"))
    assert b["status"] == "approved" and "overdue since" in b["reason"]


def test_demo_story(kassa):
    import json
    for sup in json.loads((SAMPLES / "suppliers.json").read_text()):
        kassa.store.upsert_supplier(sup["email"], sup["name"], trusted=sup["trusted"])
    st = [kassa.ingest(f.name, f.read_text())["status"] for f in sorted(SAMPLES.glob("*.txt"))]
    assert st == ["approved", "needs_approval", "rejected", "approved", "needs_approval"]


def test_quantity_format():
    from app.paypal_client import _qty
    assert _qty(3.0) == "3" and _qty(1) == "1" and _qty(1.5) == "1.5"


def test_scam_flagged_high(kassa):
    b = kassa.ingest("05", read("05-suspicious-urgent.txt"))
    assert b["status"] == "needs_approval" and b["risk_level"] == "high"
    assert b["reason"].startswith("POSSIBLE SCAM") and any("urgent" in x for x in b["risk_signals"])


def test_changed_payment_details_of_trusted_supplier(kassa):
    kassa.store.upsert_supplier("billing@pixelforge.example.com", "Pixelforge Oy", trusted=True)
    text = read("01-pixelforge-render.txt").replace("PF-2026-0412", "PF-2026-0499").replace(
        "sb-zkzff53386438@personal.example.com", "pixelforge-payments@mail.example.org")
    b = kassa.ingest("x", text)
    assert b["status"] == "needs_approval" and b["risk_level"] == "high"
    assert any(x.startswith("payment details changed") for x in b["risk_signals"])


def test_lookalike_domain():
    from app.extract import risk_rules
    sig = risk_rules("Invoice 123", {"invoice_number": "123", "supplier_email": "ceo@frappua-payments.example"}, "Frappua", ("frappua.win",))
    assert any("imitates" in x for x in sig)


def test_payout_status_mapping():
    from app.agent import payout_to_bill_status as f
    assert [f(x) for x in ("SUCCESS", "UNCLAIMED", "PENDING", "RETURNED", None)] == ["paid", "unclaimed", "sent", "failed", "sent"]


def test_limit_is_a_setting(kassa):
    assert kassa.auto_pay_limit == 500
    kassa.set_auto_pay_limit(1000)
    assert kassa.auto_pay_limit == 1000
    kassa.store.upsert_supplier("pay@nordicvoice.example.com", "Nordic Voice Studio", trusted=True)
    b = kassa.ingest("02", read("02-nordic-voice-studio.txt"))
    assert b["status"] == "approved"  # 940 EUR is now under the limit
    import pytest
    with pytest.raises(ValueError):
        kassa.set_auto_pay_limit(-1)
