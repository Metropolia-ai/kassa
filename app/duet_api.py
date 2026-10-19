"""Routes and wiring for Kassa x Kassa (two companies, one deployment). Enabled with DUET=1.

Companies come from the environment, two of them, prefixes CO_A_ and CO_B_:
  CO_A_KEY=frappua CO_A_NAME="Frappua" CO_A_EMAIL=... CO_A_OWNER="Dima" CO_A_STAFF="Alena Mima,Erik Sindonen"
  CO_A_PAYPAL_CLIENT_ID=... CO_A_PAYPAL_CLIENT_SECRET=... CO_A_AUTO_PAY_LIMIT=500
  CO_A_OPENING_BALANCE=... CO_A_OPENING_AT=...
DUET_BUYER / DUET_SUPPLIER name the keys (default: A buys, B supplies).
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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
    return Duet(db_path, companies)


class DecideIn(BaseModel):
    company: str
    choice: str
    amount: float | None = None


class PolicyIn(BaseModel):
    values: dict[str, float]


def make_router(duet: Duet) -> APIRouter:
    r = APIRouter(prefix="/api/duet")
    import time as _time
    last = {"t": 0.0}

    def lazy_refresh() -> None:  # at most once a minute while someone is looking
        if _time.time() - last["t"] > int(os.environ.get("LAZY_REFRESH_S", "60")):
            last["t"] = _time.time()
            duet.refresh()

    def company_view(c: Company) -> dict:
        bal = c.kassa.balance()
        return {"key": c.key, "name": c.name, "email": c.email, "owner": c.owner, "staff": c.staff,
                "role": "buyer" if c.key == duet.buyer_key() else "supplier",
                "paypal": bool(c.kassa.paypal), "balance": (bal or {}).get("value"),
                "currency": c.kassa.currency, "policy": duet.policy(c.key)}

    @r.get("/state")
    def state():
        lazy_refresh()
        return {"companies": [company_view(c) for c in duet.companies.values()],
                "buyer": duet.buyer_key(), "supplier": duet.supplier_key(),
                "scenarios": [{k: s[k] for k in ("key", "title", "summary", "expect")} for s in duet.scenarios()],
                "threads": duet.list_threads(),
                "env": os.environ.get("PAYPAL_ENV", "sandbox")}

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

    @r.post("/threads/{tid}/run")
    def run(tid: int, max_steps: int = 12):
        """Advance until the agents need a person or the thread is final (for scripts and tests)."""
        out = None
        for _ in range(max_steps):
            out = duet.step(tid)
            if not out["changed"] or out["status"] in ("needs_humans", "settled", "closed", "failed"):
                break
        return out

    @r.post("/threads/{tid}/decide")
    def decide(tid: int, body: DecideIn):
        return duet.decide(tid, body.company, body.choice, body.amount)

    @r.get("/threads/{tid}")
    def thread(tid: int):
        t = duet.get_thread(tid)
        if not t:
            raise HTTPException(404)
        return t

    @r.put("/policy/{company}")
    def policy(company: str, body: PolicyIn):
        if company not in duet.companies:
            raise HTTPException(404)
        return duet.set_policy(company, body.values)

    @r.get("/companies/{company}/bills")
    def bills(company: str):
        if company not in duet.companies:
            raise HTTPException(404)
        return duet.companies[company].kassa.store.list_bills()

    @r.get("/companies/{company}/invoices")
    def invoices(company: str):
        if company not in duet.companies:
            raise HTTPException(404)
        return duet.companies[company].kassa.store.list_customer_invoices()

    @r.get("/companies/{company}/audit")
    def audit(company: str, limit: int = 100):
        if company not in duet.companies:
            raise HTTPException(404)
        return duet.companies[company].kassa.store.list_audit(limit)

    @r.api_route("/refresh", methods=["GET", "POST"])
    def refresh():
        return duet.refresh()

    @r.post("/reset")
    def reset():
        duet.reset()
        return {"ok": True}

    return r
