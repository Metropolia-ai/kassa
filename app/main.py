"""Kassa web app: FastAPI routes + static dashboard."""
from __future__ import annotations

import glob
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import llm
from .agent import Kassa
from .paypal_client import PayPalClient, PayPalConfig, PayPalError
from .store import Store

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def build_kassa() -> Kassa:
    store = Store(os.environ.get("KASSA_DB", str(ROOT / "kassa.db")))
    cid, sec = os.environ.get("PAYPAL_CLIENT_ID"), os.environ.get("PAYPAL_CLIENT_SECRET")
    paypal = PayPalClient(PayPalConfig(cid, sec, os.environ.get("PAYPAL_ENV", "sandbox"))) if cid and sec else None
    return Kassa(store, paypal,
                 merchant_email=os.environ.get("MERCHANT_EMAIL", "merchant@example.com"),
                 merchant_name=os.environ.get("MERCHANT_NAME", "Kassa Demo Oy"),
                 auto_pay_limit=float(os.environ.get("AUTO_PAY_LIMIT", "500")),
                 currency=os.environ.get("CURRENCY", "EUR"))


app = FastAPI(title="Kassa", version="0.1")
kassa = build_kassa()

# Vercel Hobby runs cron at most once a day, so status refresh is also done lazily on reads:
# at most once per LAZY_REFRESH_S while the dashboard is open.
import time as _time
LAZY_REFRESH_S = int(os.environ.get("LAZY_REFRESH_S", "600"))
_last_refresh = 0.0


def lazy_refresh() -> None:
    global _last_refresh
    if kassa.paypal and _time.time() - _last_refresh > LAZY_REFRESH_S:
        _last_refresh = _time.time()
        try:
            kassa.refresh_payouts(); kassa.refresh_customer_invoices()
        except Exception:
            pass


class TextIn(BaseModel):
    text: str
    source: str = "paste"


class ChatIn(BaseModel):
    message: str


class ApproveIn(BaseModel):
    trust_supplier: bool = False
    note: str | None = None


class RejectIn(BaseModel):
    reason: str


class InvoiceItem(BaseModel):
    name: str
    description: str = ""
    quantity: float = 1
    unit_amount: float


class InvoiceIn(BaseModel):
    customer_name: str
    customer_email: str
    items: list[InvoiceItem]
    due_in_days: int = 14
    memo: str | None = None


@app.exception_handler(PayPalError)
async def paypal_err(_, e: PayPalError):
    return JSONResponse(status_code=502, content={"error": "paypal", "status": e.status, "body": e.body})


@app.exception_handler(PermissionError)
async def perm_err(_, e: PermissionError):
    return JSONResponse(status_code=403, content={"error": str(e)})


@app.exception_handler(ValueError)
async def val_err(_, e: ValueError):
    return JSONResponse(status_code=400, content={"error": str(e)})


@app.get("/")
def index():
    return FileResponse(ROOT / "app" / "static" / "index.html")


@app.get("/api/config")
def config():
    return {"merchant_name": kassa.merchant_name, "merchant_email": kassa.merchant_email,
            "currency": kassa.currency, "auto_pay_limit": kassa.auto_pay_limit,
            "paypal": bool(kassa.paypal), "env": os.environ.get("PAYPAL_ENV", "sandbox"),
            "llm": (f"{llm.provider()}:{llm.model_name()}" if llm.provider() else "rules (demo mode)")}


# --- bills ---------------------------------------------------------------
@app.get("/api/bills")
def bills(status: str | None = None):
    lazy_refresh()
    return kassa.store.list_bills(status)


@app.post("/api/bills/text")
def bill_from_text(body: TextIn):
    return kassa.ingest(body.source, body.text)


@app.post("/api/bills/upload")
async def bill_upload(files: list[UploadFile] = File(...)):
    out = []
    for f in files:
        raw = await f.read()
        text = _to_text(f.filename or "upload", raw)
        out.append(kassa.ingest(f.filename or "upload", text))
    return out


@app.post("/api/bills/samples")
def load_samples():
    out = []
    for path in sorted(glob.glob(str(ROOT / "samples" / "*.txt"))):
        out.append(kassa.ingest(Path(path).name, Path(path).read_text(encoding="utf-8")))
    return out


@app.post("/api/bills/{bill_id}/approve")
def approve(bill_id: int, body: ApproveIn):
    return kassa.approve(bill_id, body.trust_supplier, note=body.note)


@app.post("/api/bills/{bill_id}/reject")
def reject(bill_id: int, body: RejectIn):
    return kassa.reject(bill_id, body.reason)


@app.post("/api/bills/{bill_id}/pay")
def pay(bill_id: int):
    return kassa.pay_bill(bill_id, actor="human", reason="pay button in dashboard")


@app.post("/api/bills/pay-approved")
def pay_approved():
    return kassa.pay_all_approved(actor="human")


@app.post("/api/bills/{bill_id}/re-evaluate")
def re_evaluate(bill_id: int):
    if not kassa.store.get_bill(bill_id):
        raise HTTPException(404)
    return kassa.evaluate(bill_id, actor="human")


# --- customer invoices ----------------------------------------------------
@app.get("/api/invoices")
def invoices():
    lazy_refresh()
    return kassa.store.list_customer_invoices()


@app.post("/api/invoices")
def create_invoice(body: InvoiceIn):
    return kassa.create_customer_invoice(customer_name=body.customer_name, customer_email=body.customer_email,
                                         items=[i.model_dump() for i in body.items], due_in_days=body.due_in_days,
                                         memo=body.memo, actor="human", reason="created in dashboard")


# --- status, audit, chat ---------------------------------------------------
@app.api_route("/api/refresh", methods=["GET", "POST"])
def refresh():
    return {"payouts": kassa.refresh_payouts(), "invoices": kassa.refresh_customer_invoices()}


@app.get("/api/audit")
def audit(limit: int = 200):
    return kassa.store.list_audit(limit)


@app.get("/api/suppliers")
def suppliers():
    return kassa.store.list_suppliers()


@app.get("/api/chat")
def chat_history():
    return kassa.store.list_chat()


@app.post("/api/chat")
def chat(body: ChatIn):
    return {"reply": kassa.chat(body.message)}


@app.post("/api/reset")
def reset():
    kassa.store.reset()
    kassa.store.audit("human", "reset", {}, {}, "demo reset", True)
    return {"ok": True}


def _to_text(name: str, raw: bytes) -> str:
    if name.lower().endswith(".pdf"):
        try:
            from pypdf import PdfReader  # optional
            import io
            return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(raw)).pages)
        except ImportError:
            return raw.decode("latin-1", "ignore")
    if name.lower().endswith(".eml"):
        import email
        from email import policy as epolicy
        msg = email.message_from_bytes(raw, policy=epolicy.default)
        body = msg.get_body(preferencelist=("plain", "html"))
        text = body.get_content() if body else ""
        return f"From: {msg['from']}\nSubject: {msg['subject']}\nDate: {msg['date']}\n\n{text}"
    return raw.decode("utf-8", "ignore")


app.mount("/static", StaticFiles(directory=str(ROOT / "app" / "static")), name="static")
