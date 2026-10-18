"""Approval policy. Pure function: bill + context -> decision. The agent cannot override it."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class Decision:
    status: str          # approved | needs_approval | rejected
    reasons: list[str]
    notes: list[str] | None = None

    @property
    def reason(self) -> str:
        if self.reasons:
            return "; ".join(self.reasons)
        base = "within policy: trusted supplier, amount under limit, no duplicates"
        return base + ("; " + "; ".join(self.notes) if self.notes else "")


def evaluate(bill: dict, *, auto_pay_limit: float, supplier: dict | None, duplicate: dict | None,
             today: date | None = None, min_confidence: float = 0.75) -> Decision:
    today = today or date.today()
    reasons: list[str] = []
    if duplicate:
        return Decision("rejected", [f"duplicate of bill #{duplicate['id']} (same supplier and invoice number {bill.get('invoice_number')})"])
    amount = bill.get("amount")
    if amount is None or amount <= 0:
        return Decision("needs_approval", ["amount missing or not positive"])
    if not bill.get("supplier_email"):
        reasons.append("no PayPal email found for supplier")
    elif supplier is None:
        reasons.append(f"first invoice from {bill.get('supplier') or bill['supplier_email']}")
    elif not supplier.get("trusted"):
        reasons.append("supplier not marked trusted")
    if amount > auto_pay_limit:
        reasons.append(f"amount {amount:.2f} {bill.get('currency') or ''} above auto-pay limit {auto_pay_limit:.0f}")
    conf = bill.get("confidence")
    if conf is not None and conf < min_confidence:
        reasons.append(f"extraction confidence {conf:.2f} below {min_confidence:.2f}")
    notes: list[str] = []
    due = bill.get("due_date")
    if due:
        try:
            if date.fromisoformat(due) < today:
                notes.append(f"overdue since {due}, pay now")
        except ValueError:
            reasons.append(f"unreadable due date {due!r}")
    if not bill.get("invoice_number"):
        reasons.append("no invoice number")
    if reasons:
        return Decision("needs_approval", reasons + notes)
    return Decision("approved", [], notes)
