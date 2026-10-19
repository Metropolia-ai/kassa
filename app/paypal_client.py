"""Thin PayPal REST client: OAuth2, Payouts v1, Invoicing v2, Transaction Search v1.

Only what Kassa needs. Every call goes through `_request`, which raises
`PayPalError` with PayPal's debug_id so failures are traceable in the audit log.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

BASE_URLS = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live": "https://api-m.paypal.com",
}


class PayPalError(RuntimeError):
    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = body
        name = body.get("name") if isinstance(body, dict) else None
        debug_id = body.get("debug_id") if isinstance(body, dict) else None
        message = body.get("message") if isinstance(body, dict) else None
        super().__init__(f"PayPal {status} {name or ''}: {message}" if message
                         else f"PayPal {status} {name or ''} debug_id={debug_id or '-'}: {body}")


@dataclass
class PayPalConfig:
    client_id: str
    client_secret: str
    env: str = "sandbox"

    @property
    def base_url(self) -> str:
        return BASE_URLS[self.env]


class PayPalClient:
    def __init__(self, cfg: PayPalConfig, http: httpx.Client | None = None):
        self.cfg = cfg
        self.http = http or httpx.Client(timeout=30)
        self._token: str | None = None
        self._token_exp: float = 0

    # --- auth -------------------------------------------------------------
    def access_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        r = self.http.post(
            f"{self.cfg.base_url}/v1/oauth2/token",
            auth=(self.cfg.client_id, self.cfg.client_secret),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
        )
        if r.status_code != 200:
            raise PayPalError(r.status_code, _json(r))
        data = r.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def _request(self, method: str, path: str, json: Any = None, params: dict | None = None,
                 idempotency_key: str | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.access_token()}",
                   "Content-Type": "application/json"}
        if idempotency_key:
            headers["PayPal-Request-Id"] = idempotency_key
        r = self.http.request(method, f"{self.cfg.base_url}{path}", json=json, params=params, headers=headers)
        if r.status_code >= 400:
            raise PayPalError(r.status_code, _json(r))
        return _json(r)

    # --- payouts (we pay suppliers) --------------------------------------
    def create_payout(self, receiver_email: str, amount: str, currency: str, note: str,
                      sender_item_id: str, batch_id: str | None = None, subject: str = "Payment from Kassa") -> dict:
        batch_id = batch_id or f"kassa-{uuid.uuid4().hex[:16]}"
        body = {
            "sender_batch_header": {"sender_batch_id": batch_id, "email_subject": subject,
                                    "email_message": note},
            "items": [{
                "recipient_type": "EMAIL",
                "receiver": receiver_email,
                "amount": {"value": amount, "currency": currency},
                "note": note,
                "sender_item_id": sender_item_id,
            }],
        }
        return self._request("POST", "/v1/payments/payouts", json=body, idempotency_key=batch_id)

    def get_payout(self, payout_batch_id: str) -> dict:
        return self._request("GET", f"/v1/payments/payouts/{payout_batch_id}")

    # --- invoicing (we bill customers) ------------------------------------
    def create_invoice(self, *, merchant_email: str, merchant_name: str, recipient_email: str,
                       recipient_name: str | None, items: list[dict], currency: str,
                       due_date: str | None, note: str | None, reference: str | None = None,
                       invoice_number: str | None = None) -> dict:
        """items: [{name, quantity, unit_amount, description?}] amounts as strings."""
        detail: dict[str, Any] = {"currency_code": currency}
        if invoice_number:
            detail["invoice_number"] = invoice_number
        if note:
            detail["note"] = note
        if reference:
            detail["reference"] = reference
        if due_date:
            detail["payment_term"] = {"due_date": due_date}
        recipient: dict[str, Any] = {"billing_info": {"email_address": recipient_email}}
        if recipient_name:
            parts = recipient_name.split(" ", 1)
            recipient["billing_info"]["name"] = {"given_name": parts[0], "surname": parts[1] if len(parts) > 1 else ""}
        body = {
            "detail": detail,
            "invoicer": {"business_name": merchant_name, "email_address": merchant_email},
            "primary_recipients": [recipient],
            "items": [{
                "name": it["name"],
                "description": it.get("description", ""),
                "quantity": _qty(it.get("quantity", 1)),
                "unit_amount": {"currency_code": currency, "value": str(it["unit_amount"])},
            } for it in items],
        }
        created = self._request("POST", "/v2/invoicing/invoices", json=body)
        # PayPal returns only a self link on 201; fetch the full invoice.
        href = created.get("href") if isinstance(created, dict) else None
        if href:
            invoice_id = href.rstrip("/").rsplit("/", 1)[-1]
            return self.get_invoice(invoice_id)
        return created

    def send_invoice(self, invoice_id: str, subject: str | None = None, note: str | None = None) -> dict:
        body: dict[str, Any] = {"send_to_recipient": True, "send_to_invoicer": False}
        if subject:
            body["subject"] = subject
        if note:
            body["note"] = note
        return self._request("POST", f"/v2/invoicing/invoices/{invoice_id}/send", json=body) or {}

    def get_invoice(self, invoice_id: str) -> dict:
        return self._request("GET", f"/v2/invoicing/invoices/{invoice_id}")

    def cancel_invoice(self, invoice_id: str, note: str | None = None) -> dict:
        body: dict[str, Any] = {"send_to_invoicer": False, "send_to_recipient": True}
        if note:
            body["note"] = note
        return self._request("POST", f"/v2/invoicing/invoices/{invoice_id}/cancel", json=body) or {}

    def record_invoice_payment(self, invoice_id: str, amount: str, currency: str, note: str | None = None,
                               method: str = "PAYPAL") -> dict:
        """Mark a sent invoice as paid outside the invoice's own checkout (e.g. the buyer paid by Payout)."""
        from datetime import date as _date
        body: dict[str, Any] = {"method": method, "payment_date": _date.today().isoformat(),
                                "amount": {"currency_code": currency, "value": amount}}
        if note:
            body["note"] = note
        return self._request("POST", f"/v2/invoicing/invoices/{invoice_id}/payments", json=body) or {}

    def list_invoices(self, page_size: int = 20) -> dict:
        return self._request("GET", "/v2/invoicing/invoices", params={"page_size": page_size, "total_required": "true"})

    # --- reporting ---------------------------------------------------------
    def get_balance(self, currency: str) -> dict | None:
        """PayPal's balance snapshot: {"value": float, "as_of": iso}. PayPal refreshes it about hourly,
        so callers subtract what they sent after as_of. None if PayPal will not tell us."""
        try:
            res = self._request("GET", "/v1/reporting/balances", params={"currency_code": currency})
        except PayPalError:
            return None
        for bal in res.get("balances", []):
            if bal.get("currency") == currency:
                return {"value": float(bal["available_balance"]["value"]), "as_of": res.get("as_of_time") or ""}
        return None

    def list_transactions(self, start_iso: str, end_iso: str, page_size: int = 100) -> dict:
        return self._request("GET", "/v1/reporting/transactions",
                             params={"start_date": start_iso, "end_date": end_iso, "fields": "all",
                                     "page_size": page_size})


def _qty(q: Any) -> str:
    q = float(q)
    return str(int(q)) if q.is_integer() else f"{q:g}"


def _json(r: httpx.Response) -> Any:
    if not r.content:
        return {}
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text}
