"""Invoice extraction. An LLM with a forced tool call when a provider is configured (see llm.py),
otherwise a rule-based extractor so the app runs end-to-end in demo mode."""
from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta
from typing import Any

from . import llm

FIELDS = {
    "supplier": {"type": ["string", "null"], "description": "Supplier / vendor company name"},
    "supplier_email": {"type": ["string", "null"], "description": "PayPal email to pay the supplier"},
    "invoice_number": {"type": ["string", "null"]},
    "invoice_date": {"type": ["string", "null"], "description": "ISO date YYYY-MM-DD"},
    "due_date": {"type": ["string", "null"], "description": "ISO date YYYY-MM-DD"},
    "amount": {"type": ["number", "null"], "description": "Total amount payable including VAT"},
    "currency": {"type": ["string", "null"], "description": "ISO 4217 code, e.g. EUR"},
    "line_items": {"type": "array", "items": {"type": "object", "properties": {
        "description": {"type": "string"}, "quantity": {"type": "number"}, "unit_price": {"type": "number"},
        "total": {"type": "number"}}, "required": ["description", "total"]}},
    "confidence": {"type": "number", "description": "0..1 how sure you are the key fields (email, amount, number) are right"},
    "notes": {"type": "string", "description": "Anything odd: missing fields, unusual terms"},
    "risk_level": {"type": "string", "enum": ["low", "medium", "high"],
                   "description": "Fraud risk: high for likely invoice scam / business email compromise"},
    "risk_signals": {"type": "array", "items": {"type": "string"},
                     "description": "Short concrete fraud signals found in THIS text, e.g. 'urgent same-day payment', 'asks to keep it confidential', 'no invoice attached', 'new payment account', 'sender domain imitates our company'"},
}

TOOL = {
    "name": "record_invoice",
    "description": "Record the structured fields of a supplier invoice.",
    "input_schema": {"type": "object", "properties": FIELDS,
                     "required": ["supplier", "supplier_email", "invoice_number", "amount", "currency",
                                  "line_items", "confidence", "notes", "risk_level", "risk_signals"]},
}

SYSTEM = ("You are the accounts-payable clerk of a small company. Read the supplier invoice text "
          "(an email, PDF text or OCR transcript) and record its fields exactly. Never invent values: use null "
          "when a field is absent. Amount is the final total payable. Dates in ISO format. Flag anything odd in notes. "
          "Also assess fraud risk the way an experienced AP clerk would: invoice scams and business email compromise "
          "show urgency or pressure, secrecy, requests to pay a new or changed account, missing invoice or paperwork, "
          "sender domains that imitate the buyer or a known supplier, payment to personal accounts or gift cards. "
          "List only signals actually present in the text.")


def extract(text: str) -> dict[str, Any]:
    if llm.provider():
        return extract_llm(text)
    return extract_rules(text)


def extract_llm(text: str) -> dict[str, Any]:
    data = llm.call_tool_once(SYSTEM, text[:20000], TOOL)
    data["extractor"] = llm.provider() + ":" + llm.model_name("extract")
    return _normalise(data)


# --- rule-based fallback -----------------------------------------------------
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
TOTAL_WORDS = re.compile(r"(?i)\b(total|amount due|yhteens\u00e4|maksettava|summa|balance due|grand total)\b")
NUM_RE = re.compile(r"\d[\d\s.,]*\d|\d")
CUR_RE = re.compile(r"(?i)\b(EUR|USD|GBP)\b|\u20ac|\$|\u00a3")
INVNO_RE = re.compile(r"(?i)(invoice\s*(?:no|number|#)?|laskun?\s*numero|lasku\s*nro|lasku)\s*[:#]?\s*([A-Z0-9/-]*\d[A-Z0-9/-]*)")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})|(\d{1,2})[./](\d{1,2})[./](\d{4})")
SUPPLIER_RE = re.compile(r"(?im)^(?:from|l\u00e4hett\u00e4j\u00e4|supplier|toimittaja|vendor)\s*:\s*(.+)$")
LINE_RE = re.compile(r"(?m)^\s*(?:\d+\s*[x\u00d7]\s*)?(.{3,60}?)\s{2,}([\d][\d\s.,]*)\s*(?:EUR|\u20ac)?\s*$")
PAY_LINE_RE = re.compile(r"(?i)paypal|pay to|pay via|maksu|payment")


def extract_rules(text: str) -> dict[str, Any]:
    # supplier email: prefer a line that talks about payment, then the From: line, then any
    email = None
    for line in text.splitlines():
        if PAY_LINE_RE.search(line):
            m = EMAIL_RE.search(line)
            if m:
                email = m.group(0)
                break
    if not email:
        sup_line = SUPPLIER_RE.search(text)
        m = EMAIL_RE.search(sup_line.group(0)) if sup_line else None
        email = m.group(0) if m else (EMAIL_RE.search(text).group(0) if EMAIL_RE.search(text) else None)
    # total: last number on the last line that mentions a total keyword
    amount, cur = None, None
    for line in text.splitlines():
        if TOTAL_WORDS.search(line) and not re.search(r"(?i)subtotal|v\u00e4lisumma", line):
            nums = NUM_RE.findall(line)
            val = _num(nums[-1]) if nums else None
            if val is not None:
                amount = val
                cm = CUR_RE.search(line)
                cur = cm.group(0) if cm else cur
    if not cur:
        m = CUR_RE.search(text)
        cur = m.group(0) if m else None
    cur = {"\u20ac": "EUR", "$": "USD", "\u00a3": "GBP"}.get(cur, cur)
    inv = INVNO_RE.search(text)
    dates = [_iso(m) for m in DATE_RE.finditer(text)]
    sup = SUPPLIER_RE.search(text)
    supplier = sup.group(1).strip() if sup else None
    if supplier and "<" in supplier:
        supplier = supplier.split("<", 1)[0].strip().strip('"')
    due = None
    dm = re.search(r"(?i)(due|er\u00e4p\u00e4iv\u00e4|maksuehto)[^\n]{0,30}?((\d{4}-\d{2}-\d{2})|(\d{1,2}[./]\d{1,2}[./]\d{4}))", text)
    if dm:
        due = _iso(DATE_RE.search(dm.group(2)))
    items = [{"description": d.strip(), "total": _num(t)} for d, t in LINE_RE.findall(text)
             if _num(t) is not None and not re.search(r"(?i)total|yhteens\u00e4|due|vat|alv|subtotal", d)]
    confidence = 0.35 + 0.15 * sum(x is not None for x in (amount, email, inv, due))
    missing = [n for n, v in (("email", email), ("amount", amount), ("invoice number", inv), ("due date", due)) if not v]
    return _normalise({
        "supplier": supplier,
        "supplier_email": email,
        "invoice_number": inv.group(2) if inv else None,
        "invoice_date": dates[0] if dates else None,
        "due_date": due,
        "amount": amount,
        "currency": cur or "EUR",
        "line_items": items[:20],
        "confidence": round(min(confidence, 0.95), 2),
        "notes": ("rule-based extractor; missing: " + ", ".join(missing)) if missing else "rule-based extractor",
        "extractor": "rules",
    })


# --- deterministic fraud signals (work with or without an LLM) ---------------
URGENT_RE = re.compile(r"(?i)\b(urgent|asap|immediately|today|right away|within the hour|kiireellinen|heti|tänään)\b")
SECRET_RE = re.compile(r"(?i)\b(confidential|keep (this|it) (between us|quiet)|don.t tell|do not discuss|luottamuksellinen)\b")
LATER_RE = re.compile(r"(?i)(paperwork later|invoice later|send (the )?(invoice|paperwork|documents) later|no invoice attached)")
NEWACC_RE = re.compile(r"(?i)(new (paypal |bank )?account|changed (our )?(bank|payment) details|updated (bank|payment) details|uusi tili)")
WIRE_RE = re.compile(r"(?i)\b(wire transfer|wire needed|gift cards?|crypto|bitcoin)\b")


def risk_rules(text: str, data: dict[str, Any], merchant_name: str = "", own_domains: tuple[str, ...] = ()) -> list[str]:
    sig: list[str] = []
    if URGENT_RE.search(text):
        sig.append("pressure to pay urgently")
    if SECRET_RE.search(text):
        sig.append("asks to keep the payment confidential")
    if LATER_RE.search(text):
        sig.append("no invoice, paperwork promised later")
    if NEWACC_RE.search(text):
        sig.append("asks to pay a new or changed account")
    if WIRE_RE.search(text):
        sig.append("asks for a wire, gift cards or crypto")
    if not data.get("invoice_number"):
        sig.append("no invoice number")
    email = (data.get("supplier_email") or "").lower()
    dom = email.split("@", 1)[1] if "@" in email else ""
    m = (merchant_name or "").lower().replace(" ", "")
    if dom and m and m in dom.replace("-", "").replace(".", "") and dom not in own_domains:
        sig.append(f"sender domain {dom} imitates our company name")
    return sig


def combine_risk(llm_level: str | None, llm_signals: list[str] | None, rule_signals: list[str]) -> tuple[str, list[str]]:
    signals: list[str] = []
    for x in list(rule_signals) + list(llm_signals or []):
        x = x.strip().rstrip(".")
        if x and x.lower() not in {y.lower() for y in signals}:
            signals.append(x)
    strong = [x for x in rule_signals if x != "no invoice number"]
    level = "low"
    if len(strong) >= 2 or (llm_level == "high" and len(llm_signals or []) >= 2):
        level = "high"
    elif strong or llm_level == "medium" or len(signals) >= 2:
        level = "medium"
    return level, signals[:8]


def _num(s: str | None) -> float | None:
    if not s:
        return None
    s = s.strip().replace(" ", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def _iso(m: re.Match | None) -> str | None:
    if not m:
        return None
    if m.group(1):
        return m.group(1)
    d, mo, y = m.group(2), m.group(3), m.group(4)
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def _normalise(d: dict[str, Any]) -> dict[str, Any]:
    if d.get("supplier_email"):
        d["supplier_email"] = d["supplier_email"].strip().lower()
    if d.get("currency"):
        d["currency"] = d["currency"].upper()
    if isinstance(d.get("amount"), str):
        d["amount"] = _num(d["amount"])
    for k in ("invoice_date", "due_date"):
        v = d.get(k)
        if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            d[k] = _iso(DATE_RE.search(v))
    d.setdefault("line_items", [])
    d["confidence"] = float(d.get("confidence") or 0)
    return d


def sample_due(days: int = 14) -> str:
    return (date.today() + timedelta(days=days)).isoformat()
