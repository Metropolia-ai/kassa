"""Kassa x Kassa: the finance agents of two companies settle an invoice with each other through PayPal.

The supplier's agent issues a PayPal invoice, the buyer's agent checks it against its own purchase order,
the two argue the difference, and the money moves by PayPal Payout once they agree. Each owner sets how far
its agent may go alone; beyond that the owners get a card with both agents' summaries and decide.

Design rule, same as the rest of Kassa: policy decides, the model only talks. Every turn the code works out
which action the company's policy allows; the language model (when configured) writes the wording.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import llm
from .agent import Kassa, payout_to_bill_status
from .paypal_client import PayPalError
from .store import _DB, now

ROOT = Path(__file__).resolve().parent.parent

DDL = """
CREATE TABLE IF NOT EXISTS threads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  scenario TEXT, title TEXT,
  buyer TEXT NOT NULL, supplier TEXT NOT NULL,
  invoice_number TEXT, paypal_invoice_id TEXT, po_number TEXT,
  invoice_amount REAL, agreed_amount REAL, currency TEXT,
  status TEXT NOT NULL, turn TEXT, rounds INTEGER DEFAULT 0,
  bill_id INTEGER, invoice_row_id INTEGER, payout_batch_id TEXT, payout_status TEXT,
  outcome TEXT, waiting TEXT, claimed_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL, ts TEXT NOT NULL,
  company TEXT NOT NULL, author TEXT NOT NULL, action TEXT NOT NULL,
  text TEXT NOT NULL, amount REAL, data TEXT
);
CREATE TABLE IF NOT EXISTS records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER, company TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
"""

# Thread statuses, in the order a happy path visits them:
#   new -> invoiced -> (disputed -> answered -> countered ->)* agreed -> ready -> paid -> settled
# side exits: needs_humans (owners decide), rejected -> closed (duplicate), failed.
FINAL = {"settled", "closed", "failed"}

DEFAULT_POLICY = {
    "buyer": {"tolerance_pct": 10.0, "tolerance_abs": 150.0, "documented_pct": 25.0, "max_rounds": 4},
    "supplier": {"concession_pct": 10.0, "floor_pct": 75.0},
}


@dataclass
class Company:
    key: str
    name: str
    email: str
    kassa: Kassa
    owner: str = "the owner"
    staff: list[str] = field(default_factory=list)


class Duet:
    def __init__(self, db_path: str, companies: dict[str, Company], schema: str | None = "duet"):
        self.db = _DB(db_path, schema, DDL)
        self.companies = companies
        # two windows tick at once; without this both could see "no re-send yet" and send it twice
        self._resend_lock = threading.Lock()
        try:  # older databases: the per-thread claim column (see step)
            self.db.execute("ALTER TABLE threads ADD COLUMN claimed_at TEXT")
        except Exception:
            pass
        for c in companies.values():
            c.kassa.extra_tools.append(({
                "name": "bill_conversation",
                "description": "What our agent and the other company's agent said about a bill or invoice, with the order "
                               "comparison, the evidence, the owner's decisions and the outcome. Use it to explain why an amount was paid.",
                "input_schema": {"type": "object", "properties": {"invoice_number": {"type": "string"}, "bill_id": {"type": "integer"}}}},
                lambda args, key=c.key: self.conversation(key, args.get("invoice_number"), args.get("bill_id"))))

    def conversation(self, company: str, invoice_number: str | None = None, bill_id: int | None = None) -> dict:
        for t in self.threads_for(company):
            if (invoice_number and invoice_number.upper() in (t.get("invoice_number") or "").upper()) or (bill_id and t.get("bill_id") == bill_id):
                check = next((r["data"] for r in self.records(t["buyer"], "check", thread_id=t["id"])), {})
                return {"invoice_number": t["invoice_number"], "status": t["status"], "outcome": t.get("outcome"),
                        "invoice_amount": t["invoice_amount"], "agreed_amount": t.get("agreed_amount"), "currency": t["currency"],
                        "order": check, "seconds": t["seconds"], "people_involved": t["humans"],
                        "messages": [{"from": (self.companies[m["company"]].name if m["company"] in self.companies else m["company"]),
                                      "who": m["author"], "action": m["action"], "text": m["text"]} for m in t["messages"]]}
        return {"error": "no conversation found for that bill"}

    # ----------------------------------------------------------------- data
    def _rows(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in self.db.execute(sql, params).fetchall()]

    def _row(self, sql: str, params: tuple = ()) -> dict | None:
        r = self.db.execute(sql, params).fetchone()
        return dict(r) if r else None

    def get_thread(self, tid: int) -> dict | None:
        t = self._row("SELECT * FROM threads WHERE id=?", (tid,))
        if not t:
            return None
        t["messages"] = self.messages(tid)
        t["decisions"] = self.pending_decisions(t)
        return t

    def list_threads(self) -> list[dict]:
        return [self.get_thread(t["id"]) for t in self._rows("SELECT id FROM threads ORDER BY id")]

    def messages(self, tid: int) -> list[dict]:
        out = []
        for m in self._rows("SELECT * FROM messages WHERE thread_id=? ORDER BY id", (tid,)):
            if m.get("data"):
                try:
                    m["data"] = json.loads(m["data"])
                except ValueError:
                    pass
            out.append(m)
        return out

    def _update(self, tid: int, **f: Any) -> None:
        f["updated_at"] = now()
        cols = ", ".join(f"{k}=?" for k in f)
        self.db.execute(f"UPDATE threads SET {cols} WHERE id=?", (*f.values(), tid))

    def _say(self, tid: int, company: str, author: str, action: str, text: str,
             amount: float | None = None, data: dict | None = None) -> dict:
        mid = self.db.insert("INSERT INTO messages (thread_id, ts, company, author, action, text, amount, data) VALUES (?,?,?,?,?,?,?,?)",
                             (tid, now(), company, author, action, text, amount, json.dumps(data or {}, ensure_ascii=False, default=str)))
        if author == "agent":
            self.db.execute("UPDATE threads SET rounds = COALESCE(rounds,0) + 1 WHERE id=?", (tid,))
        return {"id": mid, "company": company, "author": author, "action": action, "text": text, "amount": amount, "data": data or {}}

    def _record(self, tid: int | None, company: str, kind: str, ref: str, data: dict) -> None:
        self.db.execute("INSERT INTO records (thread_id, company, kind, ref, data) VALUES (?,?,?,?,?)",
                        (tid, company, kind, ref, json.dumps(data, ensure_ascii=False)))

    def records(self, company: str, kind: str, ref: str | None = None, thread_id: int | None = None) -> list[dict]:
        sql, params = "SELECT * FROM records WHERE company=? AND kind=?", [company, kind]
        if ref:
            sql += " AND ref=?"; params.append(ref)
        if thread_id:
            sql += " AND thread_id=?"; params.append(thread_id)
        return [{**r, "data": json.loads(r["data"])} for r in self._rows(sql + " ORDER BY id", tuple(params))]

    # --------------------------------------------------------------- policy
    def policy(self, company: str) -> dict:
        role = "buyer" if company == self.buyer_key() else "supplier"
        out = dict(DEFAULT_POLICY[role])
        for k in out:
            v = self._row("SELECT value FROM settings WHERE key=?", (f"{company}.{k}",))
            if v:
                out[k] = float(v["value"])
        out["auto_pay_limit"] = self.companies[company].kassa.auto_pay_limit
        return out

    def set_policy(self, company: str, values: dict) -> dict:
        role = "buyer" if company == self.buyer_key() else "supplier"
        for k, v in values.items():
            if k == "auto_pay_limit":
                self.companies[company].kassa.set_auto_pay_limit(float(v))
            elif k in DEFAULT_POLICY[role]:
                self.db.execute("DELETE FROM settings WHERE key=?", (f"{company}.{k}",))
                self.db.execute("INSERT INTO settings (key, value) VALUES (?,?)", (f"{company}.{k}", str(float(v))))
        return self.policy(company)

    def buyer_key(self) -> str:
        return os.environ.get("DUET_BUYER") or list(self.companies)[0]

    def supplier_key(self) -> str:
        return os.environ.get("DUET_SUPPLIER") or list(self.companies)[1]

    # ------------------------------------------------------------ scenarios
    def scenarios(self) -> list[dict]:
        return json.loads((ROOT / "samples" / "duet" / "scenarios.json").read_text(encoding="utf-8"))

    def _setting(self, key: str, default: str | None = None) -> str | None:
        v = self._row("SELECT value FROM settings WHERE key=?", (key,))
        return v["value"] if v else default

    def _set_setting(self, key: str, value: str) -> None:
        self.db.execute("DELETE FROM settings WHERE key=?", (key,))
        self.db.execute("INSERT INTO settings (key, value) VALUES (?,?)", (key, value))

    def next_invoice_number(self, prefix: str = "PF-2026-", start: int = 418) -> str:
        """Sequential numbers, like a real invoicing system. PayPal rejects a number it has seen on the
        supplier's account, so the counter lives in settings and is never reset."""
        n = int(self._setting("invoice_seq", str(start - 1))) + 1
        self._set_setting("invoice_seq", str(n))
        return f"{prefix}{n:04d}"

    def start(self, scenario_key: str) -> dict:
        sc = next((s for s in self.scenarios() if s["key"] == scenario_key), None)
        if not sc:
            raise KeyError(scenario_key)
        buyer, supplier = self.buyer_key(), self.supplier_key()
        cur = self.companies[buyer].kassa.currency
        inv = sc["invoice"]
        number = self.next_invoice_number(inv.get("prefix", "PF-2026-"))
        amount = _total(inv["items"])
        tid = self.db.insert(
            "INSERT INTO threads (created_at, updated_at, scenario, title, buyer, supplier, invoice_number, po_number, "
            "invoice_amount, currency, status, turn) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (now(), now(), sc["key"], sc["title"], buyer, supplier, number, sc.get("po", {}).get("number"),
             amount, cur, "new", supplier))
        if sc.get("po"):
            self._record(tid, buyer, "po", sc["po"]["number"], sc["po"])
        for r in sc.get("supplier_records", []):
            self._record(tid, supplier, r["kind"], number, r["data"])
        if sc.get("seed_prior_bill"):
            # the duplicate scenario needs the original on both sides' books: the last settled one, or a seeded one
            kb, ks = self.companies[buyer].kassa, self.companies[supplier].kassa
            if not kb.store.find_similar(self.companies[supplier].email, amount, 0):
                prev = self.next_invoice_number(inv.get("prefix", "PF-2026-"))
                number = self.next_invoice_number(inv.get("prefix", "PF-2026-"))  # the resend gets the later number
                self._update(tid, invoice_number=number)
                when = (date.today() - timedelta(days=3)).isoformat()
                b = kb.ingest_structured(f"{self.companies[supplier].name} {prev}", _invoice_text(self.companies[supplier], self.companies[buyer], prev, inv, cur),
                                         _fields(self.companies[supplier], prev, inv, cur))
                kb.store.update_bill(b["id"], status="paid", reason="within policy: trusted supplier, matches the order", payout_status="SUCCESS",
                                     created_at=f"{when}T09:12:00+00:00")
                ks.store.add_customer_invoice(paypal_invoice_id=None, invoice_number=prev, customer_name=self.companies[buyer].name,
                                              customer_email=self.companies[buyer].email, amount=amount, currency=cur,
                                              due_date=_due(11), memo=self._original_memo(sc), status="PAID", created_at=f"{when}T09:10:00+00:00")
        return self.get_thread(tid)

    # ---------------------------------------------------------------- drafts
    def drafts(self) -> list[dict]:
        """What the supplier's owner can send: the scenarios, seen from their side as invoices ready to go.
        A re-send is not a draft (the supplier's system sends it by itself), and a draft that already went out
        is gone until Start over: no owner sends the same invoice twice on purpose."""
        sent = {r["scenario"] for r in self._rows("SELECT DISTINCT scenario FROM threads")}
        out = []
        for sc in self.scenarios():
            if sc.get("auto_resend_of") or sc["key"] in sent:
                continue
            inv = sc["invoice"]
            log = []
            for r in sc.get("supplier_records", []):
                if r["kind"] == "work_log":
                    for e in r["data"].get("entries", []):
                        n = {"hours": e["hours"]} if "hours" in e else {"qty": e.get("qty")}
                        log.append({"date": e.get("date"), **n, "note": e.get("note", "")})
            out.append({"key": sc["key"], "title": inv.get("title") or sc["title"], "note": inv.get("memo"),
                        "amount": _total(inv["items"]), "currency": self.companies[self.buyer_key()].kassa.currency,
                        "items": inv["items"], "customer": self.companies[self.buyer_key()].name,
                        "source": inv.get("source", ""), "log": log, "hint": sc.get("hint", "")})
        return out

    def send_draft(self, key: str) -> dict:
        """The supplier's owner presses Send: the invoice goes out through PayPal right away; the rest follows on its own."""
        t = self.start(key)
        return self.step(t["id"])

    def maybe_resend(self) -> dict | None:
        """The supplier's old invoicing system re-sends a paid invoice under a new number a while after it was
        paid. Nobody presses anything: the first clock tick after the delay sends it. Returns the new thread."""
        with self._resend_lock:
            for sc in self.scenarios():
                orig_key = sc.get("auto_resend_of")
                if not orig_key:
                    continue
                orig = self._row("SELECT id FROM threads WHERE scenario=? AND status='settled' ORDER BY id DESC LIMIT 1", (orig_key,))
                if not orig:
                    continue
                # ids, not created_at: timestamps have one-second resolution and a fast clock creates both in one second
                if self._row("SELECT id FROM threads WHERE scenario=? AND id>? LIMIT 1", (sc["key"], orig["id"])):
                    continue
                last = self._row("SELECT ts FROM messages WHERE thread_id=? ORDER BY id DESC LIMIT 1", (orig["id"],))
                delay = float(os.environ.get("DUET_RESEND_AFTER_S") or sc.get("resend_after_s", 45))
                try:
                    waited = (datetime.now(timezone.utc) - datetime.fromisoformat(last["ts"])).total_seconds() if last else 0
                except ValueError:
                    continue
                if waited < delay:
                    continue
                t = self.start(sc["key"])
                return self.step(t["id"])
        return None

    def tick(self) -> list[dict]:
        """Advance every thread where it is an agent's turn, one step each. Called by whichever window is open."""
        changed = []
        resent = self.maybe_resend()
        if resent:
            # it arrives on this tick and is checked on the next, so the windows can show it arriving
            changed.append({"id": resent["id"], "status": resent["status"]})
        for t in self._rows("SELECT id, status FROM threads WHERE status NOT IN ('needs_humans','settled','closed','failed') ORDER BY id"):
            if resent and t["id"] == resent["id"]:
                continue
            out = self.step(t["id"])
            if out["changed"]:
                changed.append({"id": out["id"], "status": out["status"]})
        return changed

    def threads_for(self, company: str) -> list[dict]:
        out = []
        for t in self.list_threads():
            if company not in (t["buyer"], t["supplier"]):
                continue
            t["decisions"] = [d for d in t["decisions"] if d["company"] == company]
            t["role"] = "buyer" if company == t["buyer"] else "supplier"
            t["other"] = self.companies[t["supplier"] if t["role"] == "buyer" else t["buyer"]].name
            t["seconds"] = _seconds(t["messages"])
            t["humans"] = sum(1 for m in t["messages"] if m["author"] == "human")
            out.append(t)
        return out

    # ------------------------------------------------------------------ step
    def step(self, tid: int) -> dict:
        """Advance the thread by one agent action. Returns the thread; `changed` tells the UI whether anything happened."""
        # Two windows poll /tick and a Send runs its first step inline, so two workers can pick the same thread
        # at the same moment; that once produced two PayPal invoices and two payouts for one bill. A thread is
        # claimed in the database before it is stepped; a claim older than 90 s is treated as abandoned.
        stale = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat(timespec="seconds")
        cur = self.db.execute("UPDATE threads SET claimed_at=? WHERE id=? AND (claimed_at IS NULL OR claimed_at < ?)",
                              (now(), tid, stale))
        if cur.rowcount == 0:
            t = self.get_thread(tid)
            if not t:
                raise KeyError(tid)
            t["changed"] = False
            t["busy"] = True
            return t
        try:
            return self._step_claimed(tid)
        finally:
            self.db.execute("UPDATE threads SET claimed_at=NULL WHERE id=?", (tid,))

    def _step_claimed(self, tid: int) -> dict:
        t = self.get_thread(tid)
        if not t:
            raise KeyError(tid)
        before = (len(t["messages"]), t["status"])
        st = t["status"]
        try:
            if st == "new":
                self._supplier_invoice(t)
            elif st == "invoiced":
                self._buyer_checks(t)
            elif st == "disputed":
                self._supplier_answers(t)
            elif st == "answered":
                self._buyer_weighs(t)
            elif st == "countered":
                self._supplier_weighs(t)
            elif st == "proposed":
                self._supplier_weighs(t, human=True)
            elif st == "agreed":
                self._supplier_prepares(t)
            elif st == "ready":
                self._buyer_pays(t)
            elif st == "paid":
                self._supplier_closes(t)
            elif st == "rejected":
                self._supplier_cancels(t)
            # needs_humans and final states: nothing to do until a person acts
        except PayPalError as e:
            self._say(tid, "system", "system", "error", f"PayPal refused: {e}", None, {"body": e.body})
            self._update(tid, status="failed", outcome="PayPal error")
        out = self.get_thread(tid)
        out["changed"] = (len(out["messages"]), out["status"]) != before
        return out

    # supplier: issue the invoice -------------------------------------------
    def _supplier_invoice(self, t: dict) -> None:
        sup, buy = self.companies[t["supplier"]], self.companies[t["buyer"]]
        sc = self._scenario(t)
        inv = sc["invoice"]
        data: dict = {"items": inv["items"], "amount": t["invoice_amount"]}
        auto = bool(sc.get("auto_resend_of"))
        if auto:
            data["auto"] = True
        if sup.kassa.paypal:
            row = None
            for _ in range(40):  # a fresh database restarts the counter; the sandbox account remembers every number
                try:
                    row = sup.kassa.create_customer_invoice(
                        customer_name=buy.name, customer_email=buy.email, items=_pp_items(inv["items"]),
                        due_in_days=inv.get("due_in_days", 14), memo=inv.get("memo"), actor="agent",
                        reason=f"invoice {t['invoice_number']} to {buy.name}", invoice_number=t["invoice_number"])
                    break
                except PayPalError as e:
                    issues = [d.get("issue") for d in (e.body or {}).get("details", [])] if isinstance(e.body, dict) else []
                    if "DUPLICATE_INVOICE_NUMBER" not in issues:
                        raise
                    t["invoice_number"] = self.next_invoice_number(inv.get("prefix", "PF-2026-"))  # someone used it before us
                    self._update(t["id"], invoice_number=t["invoice_number"])
            if row is None:
                raise PayPalError(422, {"name": "DUPLICATE_INVOICE_NUMBER", "message": "no free invoice number found after 40 tries"})
            data.update({"paypal_invoice_id": row.get("paypal_invoice_id"), "paypal_status": row.get("status"),
                         "pay_url": row.get("pay_url")})
            self._update(t["id"], paypal_invoice_id=row.get("paypal_invoice_id"), invoice_row_id=row.get("id"))
        else:  # no PayPal: keep the books anyway so the supplier's agent can look things up later
            rid = sup.kassa.store.add_customer_invoice(paypal_invoice_id=None, invoice_number=t["invoice_number"], customer_name=buy.name,
                                                       customer_email=buy.email, amount=t["invoice_amount"], currency=t["currency"],
                                                       due_date=_due(inv.get("due_in_days", 14)), memo=inv.get("memo"), status="SENT")
            self._update(t["id"], invoice_row_id=rid)
        facts = {"invoice_number": t["invoice_number"], "amount": t["invoice_amount"], "currency": t["currency"],
                 "items": _items_text(inv["items"]), "po_number": t.get("po_number"),
                 "paypal_invoice_id": data.get("paypal_invoice_id"), "due": _due(inv.get("due_in_days", 14))}
        if auto:  # no person sent this one, and the message must not pretend otherwise
            facts["note"] = "sent automatically by the supplier's invoicing system, not by a person"
        text = self._voice(sup, buy, "invoice", facts)
        self._say(t["id"], sup.key, "agent", "invoice", text, t["invoice_amount"], data)
        self._update(t["id"], status="invoiced", turn=t["buyer"])

    # buyer: book it and check it against the purchase order -------------------
    def _buyer_checks(self, t: dict) -> None:
        sup, buy = self.companies[t["supplier"]], self.companies[t["buyer"]]
        sc = self._scenario(t)
        inv = sc["invoice"]
        cur = t["currency"]
        source = f"{sup.name} {t['invoice_number']}" + (" (re-sent by their invoicing system)" if sc.get("auto_resend_of") else "")
        bill = buy.kassa.ingest_structured(source,
                                           _invoice_text(sup, buy, t["invoice_number"], inv, cur),
                                           _fields(sup, t["invoice_number"], inv, cur))
        self._update(t["id"], bill_id=bill["id"])
        if bill["status"] == "rejected":
            text = self._voice(buy, sup, "reject", {"invoice_number": t["invoice_number"], "reason": bill["reason"]})
            self._say(t["id"], buy.key, "agent", "reject", text, None, {"reason": bill["reason"], "bill_id": bill["id"]})
            self._update(t["id"], status="rejected", turn=t["supplier"], outcome="rejected: " + bill["reason"])
            return
        if bill["status"] == "needs_approval" and (bill.get("reason") or "").startswith("possible duplicate"):
            prev = buy.kassa.store.find_similar(sup.email, bill["amount"], bill["id"])
            text = self._voice(buy, sup, "query_duplicate", {"invoice_number": t["invoice_number"], "amount": bill["amount"], "currency": cur,
                                                             "earlier_number": prev.get("invoice_number"),
                                                             "earlier_status": _plain_status(prev.get("status"))})
            self._say(t["id"], buy.key, "agent", "query", text, None, {"duplicate_of": prev.get("invoice_number"), "earlier_bill": prev["id"]})
            buy.kassa.store.update_bill(bill["id"], status="negotiating", reason=f"checking with {sup.name}'s agent: looks like {prev.get('invoice_number')}, which we already paid")
            self._update(t["id"], status="disputed", turn=t["supplier"])
            return
        pol = self.policy(buy.key)
        po = next((r["data"] for r in self.records(buy.key, "po", thread_id=t["id"])), None)
        if not po:
            self._escalate(t, buy, f"no purchase order on file for {sup.name}; the agent may not accept an invoice without one",
                           options=self._buyer_options(t, t["invoice_amount"], None))
            return
        diffs = _diff(po["items"], inv["items"])
        po_total = _total(po["items"])
        gap = round(t["invoice_amount"] - po_total, 2)
        tol = _tolerance(po_total, pol)
        self._record(t["id"], buy.key, "check", t["invoice_number"], {"po_total": po_total, "gap": gap, "tolerance": tol, "diffs": diffs})
        if gap <= tol:
            why = (f"matches order {po['number']}" if not diffs else
                   f"{_money(gap, cur)} over order {po['number']}, within the owner's tolerance of {_money(tol, cur)}")
            self._accept(t, buy, t["invoice_amount"], why)
            return
        text = self._voice(buy, sup, "query", {"invoice_number": t["invoice_number"], "po_number": po["number"],
                                               "po_total": po_total, "invoice_total": t["invoice_amount"], "currency": cur,
                                               "differences": _diff_text(diffs), "tolerance": tol})
        self._say(t["id"], buy.key, "agent", "query", text, None, {"gap": gap, "tolerance": tol, "diffs": diffs, "po_total": po_total})
        buy.kassa.store.update_bill(bill["id"], status="negotiating",
                                    reason=f"checking with {sup.name}'s agent: {_money(gap, cur)} over what we agreed ({po['number']}), "
                                           f"the agent may accept {_money(tol, cur)} on its own")
        self._update(t["id"], status="disputed", turn=t["supplier"])

    # supplier: explain or concede ----------------------------------------------
    def _supplier_answers(self, t: dict) -> None:
        sup, buy = self.companies[t["supplier"]], self.companies[t["buyer"]]
        pol = self.policy(sup.key)
        last_q = next((m for m in reversed(t["messages"]) if m["action"] == "query"), None)
        if last_q and last_q["data"].get("duplicate_of"):
            earlier = next((r for r in sup.kassa.store.list_customer_invoices()
                            if r.get("invoice_number") == last_q["data"]["duplicate_of"]), None)
            if earlier and (earlier.get("status") or "").upper() in ("PAID", "MARKED_AS_PAID", "SENT", "UNPAID"):
                if t.get("bill_id"):
                    buy.kassa.store.update_bill(t["bill_id"], status="rejected",
                                                reason=f"withdrawn by {sup.name}: same work as {earlier['invoice_number']}, already {_plain_invoice(earlier.get('status'))}")
                self._supplier_cancels(t, earlier=earlier)
                return
            text = self._voice(sup, buy, "explain", {"invoice_number": t["invoice_number"], "currency": t["currency"],
                                                     "evidence": "our books show no earlier invoice for this work", "amount": t["invoice_amount"]})
            self._say(t["id"], sup.key, "agent", "explain", text, t["invoice_amount"], {"evidence": []})
            self._update(t["id"], status="answered", turn=t["buyer"])
            return
        log = next((r["data"] for r in self.records(sup.key, "work_log", thread_id=t["id"])), None)
        evidence = [e for e in (log or {}).get("entries", []) if e.get("approved_by")]
        last_query = next((m for m in reversed(t["messages"]) if m["action"] == "query"), None)
        gap = (last_query or {}).get("data", {}).get("gap", 0)
        if evidence:
            text = self._voice(sup, buy, "explain", {"invoice_number": t["invoice_number"], "currency": t["currency"],
                                                     "evidence": _evidence_text(evidence), "amount": t["invoice_amount"]})
            self._say(t["id"], sup.key, "agent", "explain", text, t["invoice_amount"], {"evidence": evidence})
            self._update(t["id"], status="answered", turn=t["buyer"])
            return
        # nothing in writing: offer the concession the owner allows, keep the rest
        concession = round(t["invoice_amount"] * pol["concession_pct"] / 100, 2)
        offer = round(t["invoice_amount"] - concession, 2)
        unwritten = [e for e in (log or {}).get("entries", []) if e.get("note")]
        text = self._voice(sup, buy, "counter", {"invoice_number": t["invoice_number"], "currency": t["currency"],
                                                 "offer": offer, "concession": concession, "invoice_total": t["invoice_amount"],
                                                 "what_happened": "; ".join(e["note"] for e in unwritten) or "the work was delivered as invoiced",
                                                 "gap": gap})
        self._say(t["id"], sup.key, "agent", "counter", text, offer, {"concession": concession, "entries": unwritten})
        self._update(t["id"], status="answered", turn=t["buyer"])

    # buyer: weigh the answer ------------------------------------------------------
    def _buyer_weighs(self, t: dict) -> None:
        sup, buy = self.companies[t["supplier"]], self.companies[t["buyer"]]
        pol = self.policy(buy.key)
        cur = t["currency"]
        check = next((r["data"] for r in self.records(buy.key, "check", thread_id=t["id"])), {})
        po_total, gap = check.get("po_total", t["invoice_amount"]), check.get("gap", 0)
        last = t["messages"][-1]
        if last["action"] == "explain":
            ours = [e for e in last["data"].get("evidence", []) if _is_staff(e.get("approved_by", ""), buy)]
            doc_tol = round(po_total * pol["documented_pct"] / 100, 2)
            if ours and gap <= doc_tol:
                self._accept(t, buy, t["invoice_amount"],
                             f"the extra work was ordered in writing by {ours[0]['approved_by']}; "
                             f"{_money(gap, cur)} over the order is within the {pol['documented_pct']:.0f} % the owner allows for documented changes")
                return
            why = ("the approval named is not from our staff" if not ours else
                   f"{_money(gap, cur)} over the order exceeds the {pol['documented_pct']:.0f} % allowed for documented changes")
            self._escalate(t, buy, why, options=self._buyer_options(t, t["invoice_amount"], po_total))
            return
        offer = last.get("amount") or t["invoice_amount"]
        tol = _tolerance(po_total, pol)
        if offer - po_total <= tol:
            self._accept(t, buy, offer, f"{sup.name}'s offer of {_money(offer, cur)} is within the owner's tolerance over the order")
            return
        if (t.get("rounds") or 0) < pol["max_rounds"] and not any(m["action"] == "counter" and m["company"] == buy.key for m in t["messages"]):
            most = round(po_total + tol, 2)
            text = self._voice(buy, sup, "counter", {"invoice_number": t["invoice_number"], "currency": cur, "offer": most,
                                                     "po_total": po_total, "their_offer": offer,
                                                     "reason": "that is the most the agent may approve without the owner"})
            self._say(t["id"], buy.key, "agent", "counter", text, most, {"most": most, "their_offer": offer})
            self._update(t["id"], status="countered", turn=t["supplier"])
            return
        self._escalate(t, buy, f"{sup.name} wants {_money(offer, cur)}, the agent may go to {_money(po_total + tol, cur)}",
                       options=self._buyer_options(t, offer, po_total))

    # supplier: weigh the buyer's number ------------------------------------------
    def _supplier_weighs(self, t: dict, human: bool = False) -> None:
        sup, buy = self.companies[t["supplier"]], self.companies[t["buyer"]]
        pol = self.policy(sup.key)
        cur = t["currency"]
        last = next(m for m in reversed(t["messages"]) if m["action"] in ("counter", "propose"))
        offer = float(last["amount"])
        floor = round(t["invoice_amount"] * pol["floor_pct"] / 100, 2)
        who = f"{buy.owner} personally" if human else f"{buy.name}'s agent"
        if offer >= floor:
            self._accept(t, sup, offer, f"{who} offers {_money(offer, cur)}, above the {pol['floor_pct']:.0f} % floor the owner set")
            return
        if human:
            self._escalate(t, sup, f"{who} offers {_money(offer, cur)}, below the {pol['floor_pct']:.0f} % floor ({_money(floor, cur)}) the owner set",
                           options=[{"key": "accept", "label": f"Accept {_money(offer, cur)}", "amount": offer},
                                    {"key": "decline", "label": "Decline and keep the invoice open"}])
            return
        # the other agent is at its limit too: name our floor so the buyer's owner can decide with real numbers
        text = self._voice(sup, buy, "counter", {"invoice_number": t["invoice_number"], "currency": cur, "offer": floor,
                                                 "their_offer": offer,
                                                 "reason": f"the owner allows at most {100 - pol['floor_pct']:.0f} % off the invoice without asking"})
        self._say(t["id"], sup.key, "agent", "counter", text, floor, {"floor": floor, "their_offer": offer})
        self._update(t["id"], status="answered", turn=t["buyer"])

    # agreed: supplier reissues if the amount changed ---------------------------------
    def _supplier_prepares(self, t: dict) -> None:
        sup, buy = self.companies[t["supplier"]], self.companies[t["buyer"]]
        agreed = float(t["agreed_amount"])
        if abs(agreed - float(t["invoice_amount"])) < 0.005:
            self._update(t["id"], status="ready", turn=t["buyer"])
            return
        data: dict = {"old_amount": t["invoice_amount"], "new_amount": agreed}
        number = f"{t['invoice_number']}R"
        if sup.kassa.paypal and t.get("paypal_invoice_id"):
            try:
                sup.kassa.paypal.cancel_invoice(t["paypal_invoice_id"], note=f"Replaced by {number} after agreement with {buy.name}")
            except PayPalError as e:
                data["cancel_error"] = str(e)
            if t.get("invoice_row_id"):
                sup.kassa.store.update_customer_invoice(t["invoice_row_id"], status="CANCELLED")
            row = sup.kassa.create_customer_invoice(
                customer_name=buy.name, customer_email=buy.email,
                items=[{"name": f"As agreed, replaces {t['invoice_number']}", "quantity": 1, "unit_amount": agreed}],
                due_in_days=7, memo=f"Agreed amount for {t['invoice_number']}", actor="agent",
                reason="corrected invoice after negotiation", invoice_number=number)
            data.update({"paypal_invoice_id": row.get("paypal_invoice_id"), "paypal_status": row.get("status")})
            self._update(t["id"], paypal_invoice_id=row.get("paypal_invoice_id"), invoice_row_id=row.get("id"))
        self._update(t["id"], invoice_number=number)
        text = self._voice(sup, buy, "reissue", {"old_number": t["invoice_number"], "new_number": number,
                                                 "amount": agreed, "currency": t["currency"]})
        self._say(t["id"], sup.key, "agent", "reissue", text, agreed, data)
        self._update(t["id"], status="ready", turn=t["buyer"])

    # ready: buyer pays by Payout ------------------------------------------------------
    def _buyer_pays(self, t: dict) -> None:
        sup, buy = self.companies[t["supplier"]], self.companies[t["buyer"]]
        agreed = float(t["agreed_amount"])
        k = buy.kassa
        bill = k.store.get_bill(t["bill_id"]) if t.get("bill_id") else None
        if not bill:
            raise RuntimeError("the buyer's bill is missing")
        acc = next((m for m in reversed(t["messages"]) if m["action"] == "accept"), {})
        why = (acc.get("data") or {}).get("why") or acc.get("text") or "agreed between the agents"
        decided_by_human = any(m["author"] == "human" for m in t["messages"])
        k.store.update_bill(bill["id"], status="approved", amount=agreed, invoice_number=t["invoice_number"],
                            reason=("decided by the owner: " if decided_by_human else "agreed within policy: ") + why)
        k.store.audit("agent" if not decided_by_human else "human", "approve_bill", {"bill_id": bill["id"], "thread": t["id"]},
                      {"status": "approved", "amount": agreed}, why, True)
        data: dict = {"amount": agreed}
        if k.paypal:
            paid = k.pay_bill(bill["id"], actor="agent", reason=f"settlement of {t['invoice_number']} with {sup.name}")
            data.update({"payout_batch_id": paid.get("payout_batch_id"), "payout_status": paid.get("payout_status")})
            self._update(t["id"], payout_batch_id=paid.get("payout_batch_id"), payout_status=paid.get("payout_status"))
        else:
            k.store.update_bill(bill["id"], status="paid", payout_status="SIMULATED")
        text = self._voice(buy, sup, "paid", {"invoice_number": t["invoice_number"], "amount": agreed, "currency": t["currency"],
                                              "payout_batch_id": data.get("payout_batch_id"), "to": sup.email})
        self._say(t["id"], buy.key, "agent", "paid", text, agreed, data)
        self._update(t["id"], status="paid", turn=t["supplier"])

    # paid: supplier records the payment on the PayPal invoice ---------------------------
    def _supplier_closes(self, t: dict) -> None:
        sup, buy = self.companies[t["supplier"]], self.companies[t["buyer"]]
        agreed = float(t["agreed_amount"])
        data: dict = {}
        if buy.kassa.paypal and t.get("payout_batch_id"):
            try:
                res = buy.kassa.paypal.get_payout(t["payout_batch_id"])
                item = (res.get("items") or [{}])[0]
                data["payout_status"] = item.get("transaction_status") or res["batch_header"].get("batch_status")
                self._update(t["id"], payout_status=data["payout_status"])
                if t.get("bill_id"):
                    buy.kassa.store.update_bill(t["bill_id"], payout_status=data["payout_status"],
                                                status=payout_to_bill_status(data["payout_status"]))
            except PayPalError:
                pass
        if sup.kassa.paypal and t.get("paypal_invoice_id"):
            sup.kassa.paypal.record_invoice_payment(t["paypal_invoice_id"], f"{agreed:.2f}", t["currency"],
                                                    note=f"PayPal payout {t.get('payout_batch_id') or ''} from {buy.name}")
            inv = sup.kassa.paypal.get_invoice(t["paypal_invoice_id"])
            data["invoice_status"] = inv.get("status")
            if t.get("invoice_row_id"):
                sup.kassa.store.update_customer_invoice(t["invoice_row_id"], status=inv.get("status"))
        elif t.get("invoice_row_id"):
            sup.kassa.store.update_customer_invoice(t["invoice_row_id"], status="MARKED_AS_PAID")
            data["invoice_status"] = "MARKED_AS_PAID"
        sup.kassa.store.add_ledger(-agreed, t["currency"])  # money in: the supplier's balance goes up
        text = self._voice(sup, buy, "settled", {"invoice_number": t["invoice_number"], "amount": agreed, "currency": t["currency"],
                                                 "invoice_status": _plain_invoice(data.get("invoice_status", "PAID")),
                                                 "payout_status": _plain_payout(data.get("payout_status"))})
        self._say(t["id"], sup.key, "agent", "settled", text, agreed, data)
        humans = sorted({m["company"] for m in t["messages"] if m["author"] == "human"})
        secs = _seconds(t["messages"])
        outcome = (f"settled by the agents in {secs} s, no one interrupted" if not humans
                   else f"settled in {secs} s after the owner decided")
        if t.get("bill_id"):
            b = buy.kassa.store.get_bill(t["bill_id"])
            if b:
                buy.kassa.store.update_bill(t["bill_id"], reason=f"{outcome}. {b.get('reason') or ''}".strip())
        self._update(t["id"], status="settled", turn=None, outcome=outcome, waiting=None)

    # rejected: supplier withdraws the invoice -------------------------------------------
    def _supplier_cancels(self, t: dict, earlier: dict | None = None) -> None:
        sup, buy = self.companies[t["supplier"]], self.companies[t["buyer"]]
        data: dict = {}
        if sup.kassa.paypal and t.get("paypal_invoice_id"):
            try:
                sup.kassa.paypal.cancel_invoice(t["paypal_invoice_id"], note="Withdrawn: sent twice by mistake")
                data["invoice_status"] = "CANCELLED"
                if t.get("invoice_row_id"):
                    sup.kassa.store.update_customer_invoice(t["invoice_row_id"], status="CANCELLED")
            except PayPalError as e:
                data["cancel_error"] = str(e)
        facts = {"invoice_number": t["invoice_number"]}
        if earlier:
            facts.update({"earlier_number": earlier["invoice_number"], "earlier_status": _plain_invoice(earlier.get("status"))})
        text = self._voice(sup, buy, "withdraw", facts)
        self._say(t["id"], sup.key, "agent", "withdraw", text, None, data)
        outcome = (f"duplicate of {earlier['invoice_number']}, withdrawn by {sup.name}'s agent in {_seconds(t['messages'])} s, no one interrupted" if earlier
                   else "duplicate withdrawn, no one interrupted")
        self._update(t["id"], status="closed", turn=None, outcome=outcome)

    # ------------------------------------------------------------- outcomes
    def _accept(self, t: dict, who: Company, amount: float, why: str) -> None:
        other = self.companies[t["buyer"] if who.key == t["supplier"] else t["supplier"]]
        text = self._voice(who, other, "accept", {"invoice_number": t["invoice_number"], "amount": amount,
                                                  "currency": t["currency"], "why": why})
        self._say(t["id"], who.key, "agent", "accept", text, amount, {"why": why})
        self._update(t["id"], status="agreed", agreed_amount=amount, turn=t["supplier"], waiting=None)

    def _escalate(self, t: dict, who: Company, why: str, options: list[dict]) -> None:
        other = self.companies[t["buyer"] if who.key == t["supplier"] else t["supplier"]]
        if who.key == t["buyer"] and t.get("bill_id"):
            who.kassa.store.update_bill(t["bill_id"], status="negotiating", reason=f"waiting for {who.owner}: {why}")
        text = self._voice(who, other, "escalate", {"invoice_number": t["invoice_number"], "why": why, "owner": who.owner})
        self._say(t["id"], who.key, "agent", "escalate", text, None, {"why": why, "options": options})
        self._update(t["id"], status="needs_humans", turn=None, waiting=who.key)

    def _buyer_options(self, t: dict, their: float, po_total: float | None) -> list[dict]:
        cur = t["currency"]
        opts = [{"key": "pay", "label": f"Pay {_money(their, cur)} as asked", "amount": their}]
        if po_total and abs(po_total - their) > 0.005:
            mid = round((their + po_total) / 2 / 10) * 10
            opts.append({"key": "pay", "label": f"Offer {_money(mid, cur)}", "amount": float(mid)})
            opts.append({"key": "pay", "label": f"Pay the order amount {_money(po_total, cur)}", "amount": po_total})
        opts.append({"key": "pay", "label": "Offer another amount", "amount": None, "custom": True})
        opts.append({"key": "reject", "label": "Reject the invoice"})
        return opts

    def pending_decisions(self, t: dict) -> list[dict]:
        if t["status"] != "needs_humans" or not t.get("waiting"):
            return []
        esc = next((m for m in reversed(t["messages"]) if m["action"] == "escalate"), None)
        if not esc:
            return []
        c = self.companies[t["waiting"]]
        return [{"company": c.key, "owner": c.owner, "why": esc["data"].get("why"), "options": esc["data"].get("options", [])}]

    def decide(self, tid: int, company: str, choice: str, amount: float | None = None) -> dict:
        t = self.get_thread(tid)
        if not t or t["status"] != "needs_humans" or t.get("waiting") != company:
            raise ValueError("nothing is waiting for this owner")
        me = self.companies[company]
        other = self.companies[t["buyer"] if company == t["supplier"] else t["supplier"]]
        cur = t["currency"]
        if company == t["buyer"]:
            if choice == "reject":
                self._say(tid, company, "human", "reject", f"{me.owner}: we will not pay {t['invoice_number']}.", None, {})
                self._update(tid, status="rejected", turn=t["supplier"], waiting=None, outcome="rejected by the buyer's owner")
                if t.get("bill_id"):
                    me.kassa.reject(t["bill_id"], "rejected by the owner after negotiation", actor="human")
            else:
                if amount is None:
                    raise ValueError("an amount is needed")
                amount = round(float(amount), 2)
                self._say(tid, company, "human", "propose", f"{me.owner}: I will pay {_money(amount, cur)} for {t['invoice_number']}.", amount, {})
                if amount >= float(t["invoice_amount"]) - 0.005:
                    self._update(tid, status="agreed", agreed_amount=amount, turn=t["supplier"], waiting=None)
                else:
                    self._update(tid, status="proposed", turn=t["supplier"], waiting=None)
        else:
            if choice == "accept":
                amount = round(float(amount), 2)
                self._say(tid, company, "human", "accept", f"{me.owner}: fine, {_money(amount, cur)} it is.", amount, {})
                self._update(tid, status="agreed", agreed_amount=amount, turn=t["supplier"], waiting=None)
            else:
                self._say(tid, company, "human", "decline", f"{me.owner}: no, the invoice stands at {_money(float(t['invoice_amount']), cur)}.", None, {})
                self._update(tid, status="needs_humans", waiting=t["buyer"], outcome=None)
                esc_opts = self._buyer_options(t, float(t["invoice_amount"]), None)
                self._say(tid, other.key, "agent", "escalate",
                          f"{me.name} declined. {other.owner}, pay {_money(float(t['invoice_amount']), cur)} or reject.",
                          None, {"why": f"{me.name} insists on the full amount", "options": esc_opts})
        return self.get_thread(tid)

    # --------------------------------------------------------------- history
    def seed_history(self) -> None:
        """Two months of ordinary business on both sides, so the first screen looks like a company, not a lab."""
        buy, sup = self.companies[self.buyer_key()], self.companies[self.supplier_key()]
        kb, ks = buy.kassa, sup.kassa
        if kb.store.list_bills():
            return
        cur = kb.currency
        kb.store.upsert_supplier(sup.email, sup.name, trusted=True)
        kb.store.upsert_supplier("ar@cloudbox.example.net", "Cloudbox Hosting", trusted=True)
        hist = [  # (days ago, supplier, email, number, memo, items)
            (58, sup, sup.email, "PF-2026-0401", "Render farm, second half of August", [{"name": "GPU render hours", "qty": 31, "unit": 6.50}, {"name": "Storage 2 TB, half month", "qty": 1, "unit": 12.00}]),
            (49, None, "ar@cloudbox.example.net", "CB-09-2214", "Hosting, September", [{"name": "Shared hosting, frappua.win", "qty": 1, "unit": 19.90}, {"name": "Domain renewal", "qty": 1, "unit": 14.00}]),
            (43, sup, sup.email, "PF-2026-0407", "Render farm, first half of September", [{"name": "GPU render hours", "qty": 44, "unit": 6.50}, {"name": "Storage 2 TB, half month", "qty": 1, "unit": 12.00}]),
            (28, sup, sup.email, "PF-2026-0411", "Render farm, second half of September", [{"name": "GPU render hours", "qty": 36, "unit": 6.50}, {"name": "Storage 2 TB, half month", "qty": 1, "unit": 12.00}]),
            (19, None, "ar@cloudbox.example.net", "CB-10-2291", "Hosting, October", [{"name": "Shared hosting, frappua.win", "qty": 1, "unit": 19.90}, {"name": "Domain renewal", "qty": 1, "unit": 14.00}]),
            (12, sup, sup.email, "PF-2026-0415", "Character rig, Guidepost", [{"name": "Character rig", "qty": 1, "unit": 480.00}]),
        ]
        for days, s_co, email, number, memo, items in hist:
            when = (date.today() - timedelta(days=days)).isoformat()
            name = s_co.name if s_co else "Cloudbox Hosting"
            inv = {"items": items, "due_in_days": 14, "memo": memo}
            fake = Company(key="x", name=name, email=email, kassa=kb)
            b = kb.ingest_structured(f"{name} {number}", _invoice_text(fake, buy, number, inv, cur), _fields(fake, number, inv, cur))
            kb.store.update_bill(b["id"], status="paid", payout_status="SUCCESS", created_at=f"{when}T09:12:00+00:00",
                                 invoice_date=when, due_date=(date.fromisoformat(when) + timedelta(days=14)).isoformat(),
                                 reason="within policy: trusted supplier, matches what we agreed" if days != 12 else
                                        "settled by the agents in 11 s, no one interrupted. The rig was priced as quoted on 2 Oct")
            if s_co:
                ks.store.add_customer_invoice(paypal_invoice_id=None, invoice_number=number, customer_name=buy.name, customer_email=buy.email,
                                              amount=_total(items), currency=cur, due_date=(date.fromisoformat(when) + timedelta(days=14)).isoformat(),
                                              memo=memo, status="PAID", created_at=f"{when}T09:10:00+00:00")
        kb.store.audit("agent", "history", {}, {}, "two months of bills on the books", True)

    # ------------------------------------------------------------------ misc
    def refresh(self) -> dict:
        """Ask PayPal for the latest payout and invoice statuses on both sides; mirror payouts into the threads."""
        out = {"payouts": [], "invoices": []}
        for c in self.companies.values():
            try:
                out["payouts"] += c.kassa.refresh_payouts()
                out["invoices"] += c.kassa.refresh_customer_invoices()
            except Exception:
                continue
        for t in self._rows("SELECT id, buyer, bill_id, payout_status FROM threads WHERE payout_batch_id IS NOT NULL"):
            b = self.companies[t["buyer"]].kassa.store.get_bill(t["bill_id"]) if t.get("bill_id") else None
            if b and b.get("payout_status") and b["payout_status"] != t.get("payout_status"):
                self._update(t["id"], payout_status=b["payout_status"])
        return out

    def reset(self) -> None:
        for tbl in ("messages", "records", "threads"):
            self.db.execute(f"DELETE FROM {tbl}")
        for c in self.companies.values():
            c.kassa.store.reset()
        self.seed_history()

    def _scenario(self, t: dict) -> dict:
        return next(s for s in self.scenarios() if s["key"] == t["scenario"])

    def _original_memo(self, sc: dict) -> str | None:
        """A re-send's memo says it was re-sent; the original it copies said what the work was."""
        orig = next((s for s in self.scenarios() if s["key"] == sc.get("auto_resend_of")), None)
        return (orig or sc)["invoice"].get("memo")

    def _voice(self, me: Company, other: Company, action: str, facts: dict) -> str:
        """The model writes the message; the facts and the action are decided by code. Templates if no model."""
        template = _template(me, other, action, facts)
        if not llm.provider() or os.environ.get("DUET_PLAIN"):
            return template
        cur = facts.get("currency", me.kassa.currency)
        facts = {k: (_money(v, cur) if isinstance(v, (int, float)) and not isinstance(v, bool) and k not in ("hours", "qty") else v)
                 for k, v in facts.items()}
        system = (f"You are the finance agent of {me.name}, writing to the finance agent of {other.name}. "
                  "Write one message of at most 55 words, plain business English, no greeting, no sign-off. "
                  "Use only the facts given, keep every number exactly, do not invent anything. "
                  f"The decision has already been made by {me.name}'s policy; your job is to state it clearly and politely.")
        tool = {"name": "write_message", "description": "The message to send.",
                "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}
        try:
            out = llm.call_tool_once(system, f"Action: {action}\nFacts:\n{json.dumps(facts, ensure_ascii=False, default=str)}\n"
                                             f"A plain version you may improve: {template}", tool)
            text = (out.get("text") or "").strip()
            return text if 10 < len(text) < 600 else template
        except Exception:
            return template


# ------------------------------------------------------------------ helpers
def _total(items: list[dict]) -> float:
    return round(sum(float(i["qty"]) * float(i["unit"]) for i in items), 2)


def _pp_items(items: list[dict]) -> list[dict]:
    return [{"name": i["name"], "description": i.get("description", ""), "quantity": i["qty"], "unit_amount": i["unit"]} for i in items]


def _fields(sup: Company, number: str, inv: dict, cur: str) -> dict:
    return {"supplier": sup.name, "supplier_email": sup.email, "invoice_number": number,
            "invoice_date": date.today().isoformat(), "due_date": _due(inv.get("due_in_days", 14)),
            "amount": _total(inv["items"]), "currency": cur,
            "line_items": [{"description": i["name"], "quantity": i["qty"], "unit_price": i["unit"],
                            "total": round(float(i["qty"]) * float(i["unit"]), 2)} for i in inv["items"]],
            "confidence": 1.0, "risk_level": "low", "risk_signals": []}


def _invoice_text(sup: Company, buy: Company, number: str, inv: dict, cur: str) -> str:
    lines = [f"From: {sup.name} <{sup.email}>", f"To: {buy.email}", f"Subject: Invoice {number}", "",
             f"Invoice number: {number}", f"Invoice date: {date.today().isoformat()}", f"Due date: {_due(inv.get('due_in_days', 14))}",
             f"Payment: PayPal to {sup.email}", ""]
    for i in inv["items"]:
        lines.append(f"  {i['name']} ({i['qty']} x {float(i['unit']):.2f})    {float(i['qty']) * float(i['unit']):.2f}")
    lines.append(f"Total {cur}    {_total(inv['items']):.2f}")
    return "\n".join(lines)


def _due(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _tolerance(po_total: float, pol: dict) -> float:
    return round(min(po_total * pol["tolerance_pct"] / 100, pol["tolerance_abs"]), 2)


def _diff(po_items: list[dict], inv_items: list[dict]) -> list[dict]:
    out = []
    po = {i["name"].lower(): i for i in po_items}
    for it in inv_items:
        p = po.get(it["name"].lower())
        if not p:
            out.append({"name": it["name"], "ordered": None, "invoiced": it["qty"], "unit": it["unit"]})
        elif float(p["qty"]) != float(it["qty"]) or float(p["unit"]) != float(it["unit"]):
            out.append({"name": it["name"], "ordered": p["qty"], "invoiced": it["qty"], "unit": it["unit"], "ordered_unit": p["unit"]})
    return out


def _diff_text(diffs: list[dict]) -> str:
    parts = []
    for d in diffs:
        if d["ordered"] is None:
            parts.append(f"{d['name']}: not on the order, invoiced {d['invoiced']} x {float(d['unit']):.2f}")
        else:
            parts.append(f"{d['name']}: ordered {d['ordered']}, invoiced {d['invoiced']} (at {float(d['unit']):.2f})")
    return "; ".join(parts)


def _items_text(items: list[dict]) -> str:
    return "; ".join(f"{i['name']} {i['qty']} x {float(i['unit']):.2f}" for i in items)


def _evidence_text(entries: list[dict]) -> str:
    return "; ".join(f"{e.get('date', '')}: {e.get('hours', e.get('qty', ''))} {e.get('what', 'units')} {e.get('note', '')}, approved by {e['approved_by']}"
                     for e in entries)


def _is_staff(name: str, c: Company) -> bool:
    n = name.lower()
    return any(s.lower() in n for s in c.staff) or c.name.lower() in n


def _plain_invoice(st: str | None) -> str:
    return {"PAID": "paid", "MARKED_AS_PAID": "marked as paid", "SENT": "sent", "UNPAID": "unpaid", "CANCELLED": "withdrawn",
            "PARTIALLY_PAID": "partly paid"}.get((st or "").upper(), (st or "on our books").lower())


def _plain_payout(st: str | None) -> str | None:
    if not st:
        return None
    return {"SUCCESS": "confirmed by PayPal", "PENDING": "on its way, PayPal is confirming", "PROCESSING": "being processed by PayPal",
            "UNCLAIMED": "waiting to be claimed"}.get(st.upper(), st.lower())


def _seconds(messages: list[dict]) -> int:
    from datetime import datetime as _dt
    agent = [m for m in messages if m.get("company") != "system"]
    if len(agent) < 2:
        return 0
    try:
        return max(0, int((_dt.fromisoformat(agent[-1]["ts"]) - _dt.fromisoformat(agent[0]["ts"])).total_seconds()))
    except (ValueError, KeyError):
        return 0


def _plain_status(st: str | None) -> str:
    return {"paid": "paid", "sent": "paid, PayPal is confirming", "unclaimed": "paid, waiting to be claimed",
            "approved": "approved for payment"}.get(st or "", st or "on our books")


def _money(v: float, cur: str) -> str:
    return f"{v:,.2f} {cur}".replace(",", " ")


def _template(me: Company, other: Company, action: str, f: dict) -> str:
    cur = f.get("currency", "EUR")
    if action == "invoice":
        pp = f" PayPal invoice {f['paypal_invoice_id']}." if f.get("paypal_invoice_id") else ""
        po = f" against order {f['po_number']}" if f.get("po_number") else ""
        auto = f"Sent automatically by {me.name}'s invoicing system. " if f.get("note") else ""
        return f"{auto}Invoice {f['invoice_number']}{po}: {f['items']}. Total {_money(f['amount'], cur)}, due {f['due']}.{pp}"
    if action == "query":
        return (f"Invoice {f['invoice_number']} is {_money(f['invoice_total'], cur)}, order {f['po_number']} is {_money(f['po_total'], cur)}. "
                f"Differences: {f['differences']}. Please explain or correct; I can accept up to {_money(f['tolerance'], cur)} over the order on my own.")
    if action == "explain":
        return f"The difference is extra work you ordered: {f['evidence']}. The amount stands at {_money(f['amount'], cur)}."
    if action == "counter":
        if "concession" in f:
            return (f"Nothing in writing for the difference: {f['what_happened']}. I can take {_money(f['concession'], cur)} off: "
                    f"{_money(f['offer'], cur)} instead of {_money(f['invoice_total'], cur)}.")
        return f"{_money(f['their_offer'], cur)} is outside what I may agree to alone; {f['reason']}. I can go to {_money(f['offer'], cur)}."
    if action == "accept":
        return f"Agreed: {_money(f['amount'], cur)} for {f['invoice_number']}. Reason: {f['why']}."
    if action == "escalate":
        return f"I cannot settle this alone: {f['why']}. Passing it to {f['owner']}."
    if action == "reject":
        return f"Invoice {f['invoice_number']} is refused: {f['reason']}."
    if action == "reissue":
        return f"Cancelled {f['old_number']} and issued {f['new_number']} for the agreed {_money(f['amount'], cur)}."
    if action == "paid":
        pp = f" PayPal payout {f['payout_batch_id']}." if f.get("payout_batch_id") else ""
        return f"Paid {_money(f['amount'], cur)} for {f['invoice_number']} to {f['to']}.{pp}"
    if action == "settled":
        ps = f"; the payout is {f['payout_status']}" if f.get("payout_status") else ""
        return f"Payment received and recorded, invoice {f['invoice_number']} is {f['invoice_status']}{ps}. Thank you."
    if action == "query_duplicate":
        return (f"Invoice {f['invoice_number']} for {_money(f['amount'], cur)} looks like {f['earlier_number']}, "
                f"which is already {f['earlier_status']} on our side. Is this the same work?")
    if action == "withdraw":
        if f.get("earlier_number"):
            return f"You are right: {f['invoice_number']} is the same work as {f['earlier_number']}, which is {f['earlier_status']}. Withdrawn, sorry for the noise."
        return f"Understood, {f['invoice_number']} was sent twice. Withdrawn."
    return json.dumps(f, ensure_ascii=False)
