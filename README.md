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

## Access key
The hosted demo is gated: the page asks for an access key once and stores it in the browser; every API call sends it as `X-Kassa-Key`. Without it the API returns 401, so nobody can spend the LLM budget or use the PayPal sandbox. Judges get the key in the Devpost testing instructions.

## Demo walkthrough
1. **Load sample inbox.** The company already works with two trusted suppliers (seeded from `samples/suppliers.json`). Of five bills, two are auto-approved (trusted supplier, under the limit; one is overdue and flagged "pay now"), two go to the approval queue (a new supplier above the limit, and a fake "urgent wire" with no invoice), one is rejected as a duplicate.
2. Click **Pay all approved**: Payouts batches are created in the sandbox; **Refresh PayPal status** shows `SUCCESS` (sandbox personal account) or `UNCLAIMED` (an address with no sandbox account; normal in sandbox).
3. In the queue, approve Nordic Voice with "trust supplier" and pay it; reject the fake wire.
4. **Load sample invoices** sends three customer invoices through PayPal Invoicing, or use **New invoice** or chat: `invoice Acme acme@example.com 1500 EUR for the pilot`. Open the link to see the PayPal payment page.
5. Audit log shows each step and the one refusal (agent tried to pay an unapproved bill).

## Kassa × Kassa: two companies' agents settle with each other

The same app has a second mode. Two companies run in one deployment, each with its own Kassa, PayPal
account and books. The supplier's agent issues a real PayPal invoice, the buyer's agent checks it against
its purchase order, they argue the difference within the limits their owners set, the buyer pays by
Payout and the supplier records the payment on the invoice. When the gap is bigger than an owner allowed,
that owner gets a card with both agents' summaries and decides in one click; the agents finish the paperwork.

Policy decides, the model only writes the words: `app/duet.py` works out which action each owner's policy
allows, the language model phrases the message. Without a model key the agents speak in plain templates.

Three scenarios live in `samples/duet/scenarios.json`: extra hours ordered in writing (settled by the agents
alone), a second scene agreed only in a call (the owners decide), the same work invoiced twice under a new
number (refused and withdrawn, nobody looks).

Run it locally with `DUET=1` and two companies in the environment (see `.env.example`, prefixes `CO_A_`
and `CO_B_`), then open `/`. The single-company dashboard stays at `/solo`. Routes are under `/api/duet/`.

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
