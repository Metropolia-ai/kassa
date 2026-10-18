# Kassa — an AI agent that runs a small company's money loop on PayPal

Supplier bills come in by email. Kassa reads them, checks them against a payment policy, asks a human only when the policy says so, pays through **PayPal Payouts**, bills customers through **PayPal Invoicing**, and writes every action to an audit log with the reason the agent gave.

Built for the [PayPal AI Hackathon 2026](https://paypal-ai-hackathon.devpost.com). MIT licensed.

## What it does
1. **Inbox.** Drop supplier invoices as text, `.eml` or `.pdf` (or load the sample inbox).
2. **Extraction.** Claude (tool use, forced schema) pulls supplier, PayPal email, invoice number, dates, total, currency, line items and a confidence score. Without an API key a rule-based extractor runs, so the app works end to end in demo mode.
3. **Policy.** Duplicates are rejected. Unknown suppliers, amounts above the auto-pay limit, missing data, past due dates and low confidence go to the **approval queue** with a written reason. Everything else is approved automatically.
4. **Pay.** Approved bills are paid with the PayPal Payouts API; batch id and item status are tracked and refreshed.
5. **Bill.** From chat ("invoice Fläkt pilot 15000 EUR to buyer@example.com, due 14 days") the agent creates and sends a PayPal invoice and shows the payer link.
6. **Audit.** Every tool call, by agent or human, is logged with input, output and reason. The agent **cannot** approve its own payments: `pay_bill` refuses anything not in `approved` state, and only policy or a human can set it.

## Run it
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in PayPal sandbox client id/secret and MERCHANT_EMAIL
uvicorn app.main:app --reload
# open http://127.0.0.1:8000
```
PayPal credentials: Developer Dashboard → Apps & Credentials → Sandbox → your app. For `MERCHANT_EMAIL` use the sandbox **business** account email (Testing Tools → Sandbox Accounts). Payouts go to any email; a sandbox **personal** account email shows `SUCCESS` immediately, other addresses stay `UNCLAIMED` (that is sandbox behaviour, not a bug).

Optional LLM: set `OPENROUTER_API_KEY` + `LLM_MODEL` (any OpenAI-compatible endpoint works via `OPENAI_API_KEY`/`OPENAI_BASE_URL`), or `ANTHROPIC_API_KEY`. Without a key, extraction is rule-based and chat understands a few commands (`list bills`, `pay approved bills`, `pay #3`, `invoice …`, `refresh status`).

## Demo walkthrough
1. **Load sample inbox.** Five bills: two go to the queue (first time we see the supplier), one is rejected as a duplicate, one is overdue, one is a fake "urgent wire" with no invoice.
2. **Approve** Pixelforge with "trust supplier". Click **Pay all approved**: a Payouts batch is created in the sandbox; **Refresh PayPal status** shows `SUCCESS`.
3. Re-send a Pixelforge bill with a new number under the limit: it is paid without asking.
4. Chat: `invoice Acme acme@example.com 1500 EUR for the pilot` → a PayPal invoice is created and sent; open the link.
5. Audit log shows each step and the one refusal (agent tried to pay an unapproved bill).

## Stack
Python 3.12 · FastAPI · SQLite locally, Postgres (Neon) on Vercel · httpx · LLM with function calling via OpenRouter/OpenAI-compatible API or Anthropic · AG Grid Community for the three tables · PayPal REST (OAuth2, Payouts v1, Invoicing v2).

## Deploy on Vercel
`vercel.json` runs the app as a Python function and calls `/api/refresh` once a day (Hobby plan allows daily crons only); on top of that the app refreshes PayPal statuses lazily when the dashboard loads, at most every 10 minutes, so no paid plan is needed. Set env vars in the project: PayPal keys, `MERCHANT_EMAIL`, `DATABASE_URL` (Neon Postgres, free tier), and the LLM key. Vercel has no persistent disk, so `DATABASE_URL` is required there.

## Tests
```bash
pytest -q
```
The suite uses a fake PayPal client; nothing leaves your machine.

## Layout
```
app/main.py           FastAPI routes, static UI
app/agent.py          tools, approvals, payouts, chat loop
app/policy.py         approval policy (pure function)
app/extract.py        Claude extraction + rule-based fallback
app/paypal_client.py  thin PayPal REST client
app/store.py          SQLite
app/static/index.html dashboard
samples/              sample supplier invoices
tests/
```
