"""The agent: a fixed tool set over the store and PayPal, plus a Claude chat loop.

Design rule: money only moves through `pay_bill`, and `pay_bill` only runs for bills in
`approved` state. Policy (policy.py) or a human sets that state; the agent cannot.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from . import extract as extract_mod
from . import llm
from . import policy
from .paypal_client import PayPalClient, PayPalError
from .store import Store


class Kassa:
    def __init__(self, store: Store, paypal: PayPalClient | None, *, merchant_email: str, merchant_name: str,
                 auto_pay_limit: float, currency: str = "EUR"):
        self.store = store
        self.paypal = paypal
        self.merchant_email = merchant_email
        self.merchant_name = merchant_name
        self.auto_pay_limit = auto_pay_limit
        self.currency = currency

    # ------------------------------------------------------------------ inbox
    def ingest(self, source: str, text: str, actor: str = "agent") -> dict:
        bill_id = self.store.add_bill(source, text)
        try:
            data = extract_mod.extract(text)
        except Exception as e:  # keep the bill, mark it for a human
            self.store.update_bill(bill_id, status="needs_approval", reason=f"extraction failed: {e}")
            self.store.audit(actor, "extract_bill", {"bill_id": bill_id, "source": source}, str(e), None, False)
            return self.store.get_bill(bill_id)
        fields = {k: data.get(k) for k in ("supplier", "supplier_email", "invoice_number", "invoice_date",
                                            "due_date", "amount", "currency", "line_items", "confidence")}
        own = tuple(d.strip().lower() for d in os.environ.get("OWN_DOMAINS", "").split(",") if d.strip())
        rule_sig = extract_mod.risk_rules(text, data, self.merchant_name, own)
        known = self.store.find_supplier_by_name(data.get("supplier"))
        if known and data.get("supplier_email") and known["email"] != (data.get("supplier_email") or "").lower():
            rule_sig.append(f"payment details changed: {known['name']} is paid to {known['email']}, this bill asks for {data.get('supplier_email')}")
        level, signals = extract_mod.combine_risk(data.get("risk_level"), data.get("risk_signals"), rule_sig)
        if any(x.startswith("payment details changed") for x in rule_sig):
            level = "high"
        fields["risk_level"], fields["risk_signals"] = level, signals
        self.store.update_bill(bill_id, status="extracted", **fields)
        self.store.audit(actor, "extract_bill", {"bill_id": bill_id, "source": source},
                         {**fields, "notes": data.get("notes"), "extractor": data.get("extractor")},
                         (f"risk {level}: " + "; ".join(signals[:3]) + ". " if level != "low" else "") + (data.get("notes") or ""), True)
        return self.evaluate(bill_id, actor=actor)

    def evaluate(self, bill_id: int, actor: str = "agent") -> dict:
        bill = self.store.get_bill(bill_id)
        if not bill:
            raise KeyError(bill_id)
        supplier = self.store.get_supplier(bill.get("supplier_email"))
        dup = self.store.find_duplicate(bill.get("supplier_email"), bill.get("invoice_number"), bill_id)
        d = policy.evaluate(bill, auto_pay_limit=self.auto_pay_limit, supplier=supplier, duplicate=dup)
        self.store.update_bill(bill_id, status=d.status, reason=d.reason)
        if bill.get("supplier_email"):
            self.store.upsert_supplier(bill["supplier_email"], bill.get("supplier"))
        self.store.audit(actor, "evaluate_policy", {"bill_id": bill_id}, {"status": d.status}, d.reason, True)
        return self.store.get_bill(bill_id)

    # --------------------------------------------------------------- approvals
    def approve(self, bill_id: int, trust_supplier: bool, actor: str = "human", note: str | None = None) -> dict:
        bill = self.store.get_bill(bill_id)
        if not bill:
            raise KeyError(bill_id)
        if actor != "human":
            raise PermissionError("only a human can approve a bill")
        if bill["status"] not in ("needs_approval", "extracted", "failed"):
            raise ValueError(f"bill #{bill_id} is {bill['status']}, cannot approve")
        reason = note or "approved by human"
        self.store.update_bill(bill_id, status="approved", reason=reason)
        if trust_supplier and bill.get("supplier_email"):
            self.store.upsert_supplier(bill["supplier_email"], bill.get("supplier"), trusted=True)
        self.store.audit(actor, "approve_bill", {"bill_id": bill_id, "trust_supplier": trust_supplier}, {"status": "approved"}, reason, True)
        return self.store.get_bill(bill_id)

    def reject(self, bill_id: int, reason: str, actor: str = "human") -> dict:
        bill = self.store.get_bill(bill_id)
        if not bill:
            raise KeyError(bill_id)
        if bill["status"] in ("paid", "paying"):
            raise ValueError("cannot reject a bill that is being paid")
        self.store.update_bill(bill_id, status="rejected", reason=reason)
        self.store.audit(actor, "reject_bill", {"bill_id": bill_id}, {"status": "rejected"}, reason, True)
        return self.store.get_bill(bill_id)

    # ----------------------------------------------------------------- paying
    def pay_bill(self, bill_id: int, actor: str = "agent", reason: str | None = None) -> dict:
        bill = self.store.get_bill(bill_id)
        if not bill:
            raise KeyError(bill_id)
        if bill["status"] != "approved":
            msg = f"refused: bill #{bill_id} is '{bill['status']}', only 'approved' bills can be paid"
            self.store.audit(actor, "pay_bill", {"bill_id": bill_id}, msg, reason, False)
            raise PermissionError(msg)
        if not self.paypal:
            raise RuntimeError("PayPal is not configured")
        self.store.update_bill(bill_id, status="paying")
        note = f"{self.merchant_name}: payment of invoice {bill.get('invoice_number') or ''}".strip()
        try:
            res = self.paypal.create_payout(
                receiver_email=bill["supplier_email"], amount=f"{bill['amount']:.2f}",
                currency=bill.get("currency") or self.currency, note=note,
                sender_item_id=f"bill-{bill_id}", batch_id=f"kassa-bill-{bill_id}-{int(datetime.now().timestamp())}")
        except PayPalError as e:
            self.store.update_bill(bill_id, status="failed", reason=str(e)[:500])
            self.store.audit(actor, "pay_bill", {"bill_id": bill_id, "amount": bill["amount"]}, e.body, reason, False)
            raise
        batch = res["batch_header"]["payout_batch_id"]
        self.store.update_bill(bill_id, status="paid", payout_batch_id=batch,
                               payout_status=res["batch_header"].get("batch_status"))
        self.store.audit(actor, "pay_bill", {"bill_id": bill_id, "amount": bill["amount"], "to": bill["supplier_email"]},
                         {"payout_batch_id": batch, "batch_status": res["batch_header"].get("batch_status")}, reason, True)
        return self.store.get_bill(bill_id)

    def pay_all_approved(self, actor: str = "agent") -> list[dict]:
        out = []
        for b in self.store.list_bills("approved"):
            try:
                out.append(self.pay_bill(b["id"], actor=actor, reason="batch payment of approved bills"))
            except Exception as e:
                out.append({"id": b["id"], "error": str(e)})
        return out

    def refresh_payouts(self) -> list[dict]:
        if not self.paypal:
            return []
        changed = []
        for b in self.store.list_bills():
            if b.get("payout_batch_id") and b.get("payout_status") not in ("SUCCESS", "DENIED", "CANCELED"):
                try:
                    res = self.paypal.get_payout(b["payout_batch_id"])
                except PayPalError:
                    continue
                items = res.get("items") or [{}]
                st = items[0].get("transaction_status") or res["batch_header"].get("batch_status")
                if st != b.get("payout_status"):
                    self.store.update_bill(b["id"], payout_status=st, payout_item_id=items[0].get("payout_item_id"))
                    changed.append({"id": b["id"], "payout_status": st})
        return changed

    # -------------------------------------------------------- customer billing
    def create_customer_invoice(self, *, customer_name: str, customer_email: str, items: list[dict],
                                due_in_days: int = 14, memo: str | None = None, send: bool = True,
                                actor: str = "agent", reason: str | None = None) -> dict:
        if not self.paypal:
            raise RuntimeError("PayPal is not configured")
        due = (date.today() + timedelta(days=due_in_days)).isoformat()
        total = sum(float(i["unit_amount"]) * float(i.get("quantity", 1)) for i in items)
        inv = self.paypal.create_invoice(merchant_email=self.merchant_email, merchant_name=self.merchant_name,
                                         recipient_email=customer_email, recipient_name=customer_name,
                                         items=items, currency=self.currency, due_date=due, note=memo)
        row_id = self.store.add_customer_invoice(
            paypal_invoice_id=inv.get("id"), invoice_number=inv.get("detail", {}).get("invoice_number"),
            customer_name=customer_name, customer_email=customer_email, amount=round(total, 2),
            currency=self.currency, due_date=due, memo=memo, status=inv.get("status"))
        self.store.audit(actor, "create_customer_invoice", {"customer": customer_email, "items": items, "due": due},
                         {"invoice_id": inv.get("id"), "status": inv.get("status")}, reason, True)
        if send:
            try:
                self.paypal.send_invoice(inv["id"], subject=f"Invoice from {self.merchant_name}")
                full = self.paypal.get_invoice(inv["id"])
                pay_url = (full.get("detail", {}).get("metadata", {}).get("recipient_view_url")
                           or next((l["href"] for l in full.get("links", []) if l.get("rel") == "payer-view"), None))
                self.store.update_customer_invoice(row_id, status=full.get("status"), pay_url=pay_url)
                self.store.audit(actor, "send_customer_invoice", {"invoice_id": inv["id"]},
                                 {"status": full.get("status"), "pay_url": pay_url}, reason, True)
            except PayPalError as e:
                self.store.audit(actor, "send_customer_invoice", {"invoice_id": inv["id"]}, e.body, reason, False)
        return next(r for r in self.store.list_customer_invoices() if r["id"] == row_id)

    def refresh_customer_invoices(self) -> list[dict]:
        if not self.paypal:
            return []
        changed = []
        for r in self.store.list_customer_invoices():
            if r.get("paypal_invoice_id") and r.get("status") not in ("PAID", "CANCELLED", "REFUNDED"):
                try:
                    inv = self.paypal.get_invoice(r["paypal_invoice_id"])
                except PayPalError:
                    continue
                if inv.get("status") != r.get("status"):
                    self.store.update_customer_invoice(r["id"], status=inv.get("status"))
                    changed.append({"id": r["id"], "status": inv.get("status")})
        return changed

    # ------------------------------------------------------------------ chat
    def tools(self) -> list[dict]:
        return [
            {"name": "list_bills", "description": "List supplier bills, optionally filtered by status "
             "(received, extracted, needs_approval, approved, paying, paid, failed, rejected).",
             "input_schema": {"type": "object", "properties": {"status": {"type": ["string", "null"]}}}},
            {"name": "pay_bill", "description": "Pay one approved supplier bill via PayPal Payouts. Refuses unless status is 'approved'.",
             "input_schema": {"type": "object", "properties": {"bill_id": {"type": "integer"}, "reason": {"type": "string"}},
                              "required": ["bill_id", "reason"]}},
            {"name": "pay_all_approved", "description": "Pay every bill currently in 'approved' status.",
             "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
            {"name": "create_customer_invoice", "description": "Create and send a PayPal invoice to a customer.",
             "input_schema": {"type": "object", "properties": {
                 "customer_name": {"type": "string"}, "customer_email": {"type": "string"},
                 "items": {"type": "array", "items": {"type": "object", "properties": {
                     "name": {"type": "string"}, "description": {"type": "string"},
                     "quantity": {"type": "number"}, "unit_amount": {"type": "number"}}, "required": ["name", "unit_amount"]}},
                 "due_in_days": {"type": "integer"}, "memo": {"type": "string"}, "reason": {"type": "string"}},
                 "required": ["customer_name", "customer_email", "items", "reason"]}},
            {"name": "list_customer_invoices", "description": "List invoices we have issued to customers and their PayPal status.",
             "input_schema": {"type": "object", "properties": {}}},
            {"name": "refresh_status", "description": "Pull latest payout and invoice statuses from PayPal.",
             "input_schema": {"type": "object", "properties": {}}},
            {"name": "list_audit", "description": "Show the most recent audit log entries.",
             "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
        ]

    def run_tool(self, name: str, args: dict) -> Any:
        if name == "list_bills":
            return [_slim(b) for b in self.store.list_bills(args.get("status") or None)]
        if name == "pay_bill":
            return _slim(self.pay_bill(int(args["bill_id"]), reason=args.get("reason")))
        if name == "pay_all_approved":
            return [(_slim(b) if "id" in b and "error" not in b else b) for b in self.pay_all_approved()]
        if name == "create_customer_invoice":
            return self.create_customer_invoice(customer_name=args["customer_name"], customer_email=args["customer_email"],
                                                items=args["items"], due_in_days=int(args.get("due_in_days") or 14),
                                                memo=args.get("memo"), reason=args.get("reason"))
        if name == "list_customer_invoices":
            return self.store.list_customer_invoices()
        if name == "refresh_status":
            return {"payouts": self.refresh_payouts(), "invoices": self.refresh_customer_invoices()}
        if name == "list_audit":
            return self.store.list_audit(int(args.get("limit") or 20))
        raise KeyError(name)

    def chat(self, user_text: str) -> str:
        self.store.add_chat("user", user_text)
        answer = self._chat_llm(user_text) if llm.provider() else self._chat_rules(user_text)
        self.store.add_chat("assistant", answer)
        return answer

    def _chat_llm(self, user_text: str) -> str:
        system = (f"You are Kassa, the finance agent of {self.merchant_name}. Today is {date.today().isoformat()}. "
                  f"Currency {self.currency}. Auto-pay limit {self.auto_pay_limit:.0f}. "
                  "You pay supplier bills and issue customer invoices through PayPal using the tools. "
                  "You can only pay bills a human or policy has approved; if a tool refuses, say why and "
                  "tell the user to approve the bill in the queue. Always give a one-line reason when you move money. "
                  "Be brief and concrete: amounts, ids, statuses.")
        history = [{"role": m["role"], "content": m["content"]} for m in self.store.list_chat(12)[:-1]]
        return llm.run_agent(system, history, user_text, self.tools(), self.run_tool)

    def _chat_rules(self, text: str) -> str:
        """No LLM key: a few canned commands so the demo still works."""
        t = text.lower()
        if "pay" in t and "approved" in t:
            res = self.pay_all_approved()
            paid = [r for r in res if "error" not in r]
            errs = [r for r in res if "error" in r]
            return f"Paid {len(paid)} approved bill(s) via PayPal Payouts." + (f" Errors: {errs}" if errs else "")
        if "pay" in t and "#" in t:
            bid = int(t.split("#", 1)[1].split()[0])
            try:
                b = self.pay_bill(bid, reason="user asked in chat")
                return f"Paid bill #{bid}: {b['amount']} {b['currency']} to {b['supplier_email']}, payout {b['payout_batch_id']}."
            except Exception as e:
                return f"Could not pay bill #{bid}: {e}"
        if "invoice" in t and "@" in text:
            import re
            email = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text).group(0)
            amt = re.search(r"(\d[\d\s]*(?:[.,]\d+)?)\s*(?:eur|€)", t)
            amount = float(amt.group(1).replace(" ", "").replace(",", ".")) if amt else 100.0
            name = (re.search(r"(?i)invoice\s+([A-Za-z][\w&-]*)", text) or [None, "Customer"])[1]
            r = self.create_customer_invoice(customer_name=name, customer_email=email,
                                             items=[{"name": "Services", "unit_amount": amount}], memo=text,
                                             reason="user asked in chat")
            return f"Invoice {r['invoice_number']} for {r['amount']} {r['currency']} sent to {email}. Status {r['status']}. {r.get('pay_url') or ''}"
        if "status" in t or "refresh" in t:
            return json.dumps(self.run_tool("refresh_status", {}), default=str)
        if "bill" in t or "list" in t:
            bills = self.run_tool("list_bills", {})
            return "\n".join(f"#{b['id']} {b['supplier']} {b['amount']} {b['currency']} {b['status']}" for b in bills) or "No bills."
        return ("Demo mode (no LLM key). Try: 'list bills', 'pay approved bills', 'pay #3', "
                "'invoice Acme acme@example.com 1500 EUR for the pilot', 'refresh status'.")


def _slim(b: dict) -> dict:
    return {k: b.get(k) for k in ("id", "supplier", "supplier_email", "invoice_number", "due_date", "amount",
                                  "currency", "status", "reason", "risk_level", "risk_signals", "payout_batch_id", "payout_status")}
