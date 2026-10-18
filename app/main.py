"""Kassa web app: FastAPI routes + static dashboard."""
from __future__ import annotations

import glob
import os
from pathlib import Path

from dotenv import load_dotenv
import hmac

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
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

# --- access gate ---------------------------------------------------------
# Every /api/* call needs header X-Kassa-Key == ACCESS_KEY. The page itself is public, the API is not,
# so nobody can spend the LLM key or touch the PayPal sandbox without the key.
# Vercel Cron calls /api/refresh with "Authorization: Bearer $CRON_SECRET".
# Fail closed on Vercel if ACCESS_KEY is missing; locally an unset key means open (dev mode).
ACCESS_KEY = os.environ.get("ACCESS_KEY", "")
CRON_SECRET = os.environ.get("CRON_SECRET", "")
ON_VERCEL = bool(os.environ.get("VERCEL"))
OPEN_PATHS = {"/api/health"}


def _eq(a: str, b: str) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())


@app.middleware("http")
async def access_gate(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in OPEN_PATHS:
        if not ACCESS_KEY and ON_VERCEL:
            return JSONResponse(status_code=503, content={"error": "ACCESS_KEY is not configured on the server"})
        if ACCESS_KEY:
            key = request.headers.get("x-kassa-key", "")
            bearer = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            cron_ok = path == "/api/refresh" and _eq(bearer, CRON_SECRET)
            if not (_eq(key, ACCESS_KEY) or cron_ok):
                return JSONResponse(status_code=401, content={"error": "access key required"})
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"ok": True, "gate": bool(ACCESS_KEY)}

# Vercel Hobby runs cron at most once a day, so status refresh is also done lazily on reads:
# at most once per LAZY_REFRESH_S while the dashboard is open.
import time as _time
LAZY_REFRESH_S = int(os.environ.get("LAZY_REFRESH_S", "60"))
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


class SettingsIn(BaseModel):
    auto_pay_limit: float


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
            "llm": (f"{llm.provider()}:{llm.model_name()}" if llm.provider() else "rules (demo mode)"),
            "demo_customer_email": os.environ.get("DEMO_CUSTOMER_EMAIL", "")}


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


@app.get("/api/samples")
def list_samples():
    return [{"name": Path(x).name, "text": Path(x).read_text(encoding="utf-8")} for x in sorted(glob.glob(str(ROOT / "samples" / "*.txt")))]


@app.post("/api/samples/suppliers")
def seed_suppliers():
    """Demo: the company already works with some suppliers. Seeds them as trusted so auto-pay is visible."""
    import json as _json
    seeded = []
    for sup in _json.loads((ROOT / "samples" / "suppliers.json").read_text(encoding="utf-8")):
        kassa.store.upsert_supplier(sup["email"], sup["name"], trusted=sup.get("trusted", False))
        seeded.append(sup["name"])
    kassa.store.audit("human", "seed_suppliers", {"suppliers": seeded}, {"trusted": seeded}, "demo: known suppliers", True)
    return {"seeded": seeded}


@app.get("/api/samples/invoices")
def sample_invoices():
    import json as _json
    email = os.environ.get("DEMO_CUSTOMER_EMAIL", "")
    out = _json.loads((ROOT / "samples" / "customer-invoices.json").read_text(encoding="utf-8"))
    for x in out:
        x["customer_email"] = email
    return out


@app.get("/api/suppliers")
def suppliers_list():
    return kassa.store.list_suppliers()


@app.post("/api/bills/samples")
def load_samples():
    seed_suppliers()
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


@app.get("/api/settings")
def get_settings():
    return {"auto_pay_limit": kassa.auto_pay_limit, "currency": kassa.currency}


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    return {"auto_pay_limit": kassa.set_auto_pay_limit(body.auto_pay_limit), "currency": kassa.currency}


@app.get("/api/audit")
def audit(limit: int = 200):
    return kassa.store.list_audit(limit)


@app.get("/api/chat")
def chat_history():
    return kassa.store.list_chat()


@app.post("/api/chat")
def chat(body: ChatIn):
    reply, tools = kassa.chat_with_trace(body.message)
    return {"reply": reply, "tools": tools}


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
