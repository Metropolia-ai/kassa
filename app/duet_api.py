"""Routes and wiring for Kassa x Kassa (two companies, one deployment). Enabled with DUET=1.

Companies come from the environment, two of them, prefixes CO_A_ and CO_B_:
  CO_A_KEY=frappua CO_A_NAME="Frappua" CO_A_EMAIL=... CO_A_OWNER="Erik" CO_A_STAFF="Alena Mima,Erik Sindonen"
  CO_A_PAYPAL_CLIENT_ID=... CO_A_PAYPAL_CLIENT_SECRET=... CO_A_AUTO_PAY_LIMIT=500
  CO_A_OPENING_BALANCE=... CO_A_OPENING_AT=...
DUET_BUYER / DUET_SUPPLIER name the keys (default: A buys, B supplies).

The page shows one company at a time (`/?co=frappua`); everything a company sees goes through
/api/duet/companies/{co}/... so one side never reads the other side's settings.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import llm
from .agent import Kassa
from .duet import Company, Duet
from .paypal_client import PayPalClient, PayPalConfig
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


def build_company(prefix: str, db_path: str) -> Company | None:
    g = lambda k, d=None: os.environ.get(f"{prefix}_{k}", d)  # noqa: E731
    key = g("KEY")
    if not key:
        return None
    cid, sec = g("PAYPAL_CLIENT_ID"), g("PAYPAL_CLIENT_SECRET")
    paypal = PayPalClient(PayPalConfig(cid, sec, os.environ.get("PAYPAL_ENV", "sandbox"))) if cid and sec else None
    ob = g("OPENING_BALANCE")
    kassa = Kassa(Store(db_path, schema=f"co_{key}"), paypal,
                  merchant_email=g("EMAIL", f"{key}@example.com"), merchant_name=g("NAME", key.title()),
                  auto_pay_limit=float(g("AUTO_PAY_LIMIT", "500")), currency=os.environ.get("CURRENCY", "EUR"),
                  opening_balance=float(ob) if ob else None, opening_at=g("OPENING_AT"))
    staff = [s.strip() for s in (g("STAFF") or "").split(",") if s.strip()]
    return Company(key=key, name=kassa.merchant_name, email=kassa.merchant_email, kassa=kassa,
                   owner=g("OWNER", "the owner"), staff=staff)


def build_duet(db_path: str) -> Duet:
    companies = {}
    for prefix in ("CO_A", "CO_B"):
        c = build_company(prefix, db_path)
        if c:
            companies[c.key] = c
    if len(companies) != 2:
        raise RuntimeError("DUET needs two companies: CO_A_* and CO_B_* in the environment")
    d = Duet(db_path, companies)
    try:
        d.seed_history()
    except Exception:
        pass
    return d


class DecideIn(BaseModel):
    choice: str
    amount: float | None = None


class PolicyIn(BaseModel):
    values: dict[str, float]


class ChatIn(BaseModel):
    message: str


class DecideLegacyIn(BaseModel):
    company: str
    choice: str
    amount: float | None = None


def make_router(duet: Duet) -> APIRouter:
    r = APIRouter(prefix="/api/duet")
    last = {"t": 0.0}

    def lazy_refresh() -> None:  # at most once a minute while someone is looking
        if time.time() - last["t"] > int(os.environ.get("LAZY_REFRESH_S", "60")):
            last["t"] = time.time()
            try:
                duet.refresh()
            except Exception:
                pass

    def co(key: str) -> Company:
        if key not in duet.companies:
            raise HTTPException(404, "no such company")
        return duet.companies[key]

    def other(c: Company) -> Company:
        return next(x for x in duet.companies.values() if x.key != c.key)

    # ------------------------------------------------------------ one company's view
    @r.get("/companies/{key}/me")
    def me(key: str):
        c = co(key)
        bal = c.kassa.balance()
        o = other(c)
        return {"key": c.key, "merchant_name": c.name, "merchant_email": c.email, "owner": c.owner, "staff": c.staff,
                "role": "buyer" if c.key == duet.buyer_key() else "supplier",
                "other": {"key": o.key, "name": o.name, "owner": o.owner, "role": "supplier" if c.key == duet.buyer_key() else "buyer"},
                "currency": c.kassa.currency, "auto_pay_limit": c.kassa.auto_pay_limit, "policy": duet.policy(c.key),
                "paypal": bool(c.kassa.paypal), "env": os.environ.get("PAYPAL_ENV", "sandbox"),
                "paypal_balance": (bal or {}).get("value"),
                "llm": (f"{llm.provider()}:{llm.model_name()}" if llm.provider() else "rules (demo mode)")}

    @r.get("/companies/{key}/bills")
    def bills(key: str):
        lazy_refresh()
        return co(key).kassa.store.list_bills()

    @r.get("/companies/{key}/invoices")
    def invoices(key: str):
        lazy_refresh()
        c = co(key)
        by_row = {t.get("invoice_row_id"): t for t in duet.threads_for(c.key)}
        out = []
        for row in c.kassa.store.list_customer_invoices():
            t = by_row.get(row["id"])
            row["thread"] = {k: t.get(k) for k in ("id", "status", "outcome", "seconds", "humans")} if t else None
            out.append(row)
        return out

    @r.get("/companies/{key}/threads")
    def threads(key: str):
        return duet.threads_for(co(key).key)

    @r.get("/companies/{key}/drafts")
    def drafts(key: str):
        c = co(key)
        if c.key != duet.supplier_key():
            return []
        return duet.drafts()

    @r.post("/companies/{key}/drafts/{draft}/send")
    def send(key: str, draft: str):
        c = co(key)
        if c.key != duet.supplier_key():
            raise HTTPException(403, "only the supplier sends invoices in this demo")
        try:
            return duet.send_draft(draft)
        except KeyError:
            raise HTTPException(404, "no such draft")

    @r.post("/companies/{key}/threads/{tid}/decide")
    def decide(key: str, tid: int, body: DecideIn):
        return duet.decide(tid, co(key).key, body.choice, body.amount)

    @r.put("/companies/{key}/policy")
    def policy(key: str, body: PolicyIn):
        return duet.set_policy(co(key).key, body.values)

    @r.get("/companies/{key}/audit")
    def audit(key: str, limit: int = 200):
        return co(key).kassa.store.list_audit(limit)

    @r.get("/companies/{key}/chat")
    def chat_history(key: str):
        return co(key).kassa.store.list_chat()

    @r.post("/companies/{key}/chat")
    def chat(key: str, body: ChatIn):
        reply, tools = co(key).kassa.chat_with_trace(body.message)
        return {"reply": reply, "tools": tools}

    class ApproveIn(BaseModel):
        trust_supplier: bool = False
        note: str | None = None

    class RejectIn(BaseModel):
        reason: str

    @r.post("/companies/{key}/bills/{bill_id}/approve")
    def approve(key: str, bill_id: int, body: ApproveIn):
        return co(key).kassa.approve(bill_id, body.trust_supplier, note=body.note)

    @r.post("/companies/{key}/bills/{bill_id}/reject")
    def reject(key: str, bill_id: int, body: RejectIn):
        return co(key).kassa.reject(bill_id, body.reason)

    @r.post("/companies/{key}/bills/pay-approved")
    def pay_approved(key: str):
        return co(key).kassa.pay_all_approved(actor="human")

    @r.post("/companies/{key}/refresh")
    def refresh_company(key: str):
        co(key)
        return duet.refresh()

    # ------------------------------------------------------------ the clock
    @r.post("/tick")
    def tick():
        """Whichever window is open drives the agents forward. Idempotent: nothing to do returns []."""
        return duet.tick()

    @r.post("/reset")
    def reset():
        duet.reset()
        return {"ok": True}

    # ------------------------------------------------------------ for scripts and tests
    @r.get("/state")
    def state():
        lazy_refresh()
        return {"companies": [{"key": c.key, "name": c.name, "role": "buyer" if c.key == duet.buyer_key() else "supplier",
                               "paypal": bool(c.kassa.paypal), "balance": (c.kassa.balance() or {}).get("value")} for c in duet.companies.values()],
                "buyer": duet.buyer_key(), "supplier": duet.supplier_key(),
                "scenarios": [{k: s[k] for k in ("key", "title", "summary", "expect")} for s in duet.scenarios()],
                "threads": duet.list_threads(), "env": os.environ.get("PAYPAL_ENV", "sandbox")}

    @r.post("/scenario/{key}")
    def start(key: str):
        try:
            return duet.start(key)
        except KeyError:
            raise HTTPException(404, "no such scenario")

    @r.post("/threads/{tid}/step")
    def step(tid: int):
        try:
            return duet.step(tid)
        except KeyError:
            raise HTTPException(404)

    @r.post("/threads/{tid}/decide")
    def decide_legacy(tid: int, body: DecideLegacyIn):
        return duet.decide(tid, body.company, body.choice, body.amount)

    @r.get("/threads/{tid}")
    def thread(tid: int):
        t = duet.get_thread(tid)
        if not t:
            raise HTTPException(404)
        return t

    @r.api_route("/refresh", methods=["GET", "POST"])
    def refresh():
        return duet.refresh()

    return r
