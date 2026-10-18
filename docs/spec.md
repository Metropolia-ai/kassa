# Kassa — agentic accounts payable & receivable on PayPal

Entry for PayPal AI Hackathon 2026 (Devpost). Deadline 12 Nov 2026 12:00 PST.
Target prizes: Best Use of Agentic Commerce, Best Use of PayPal + AI, Best Use of AG Grid, Best Use of Render, overall top 3.

## Problem
Small studios and freelancers lose hours every week on supplier bills and customer invoices: reading PDFs, retyping amounts, chasing approvals, paying, and then reconciling. Existing AP tools are built for finance departments, not for a four-person company.

## What Kassa does
An AI agent that owns the money loop of a small company, with a human approval gate:

1. **Inbox.** Supplier invoices arrive as email text, PDF text or a photo transcript (upload or sample inbox).
2. **Extraction.** The agent (Claude, tool use) extracts supplier, PayPal email, invoice number, dates, amount, currency, line items and a confidence score. Without an API key a rule-based extractor runs so the app works in demo mode.
3. **Policy.** Duplicate invoice number, unknown supplier, amount above `AUTO_PAY_LIMIT`, due date in the past, or low confidence → `needs_approval`. Otherwise `approved` for auto-pay. Every decision carries a written reason.
4. **Pay.** Approved bills are paid with the PayPal **Payouts API** (sandbox). Batch id and item status are stored and polled.
5. **Bill customers.** From chat ("invoice Fläkt 15 000 € for the pilot, due in 14 days") the agent creates and sends a PayPal **Invoice** (Invoicing API v2).
6. **Reconcile.** Payout status and invoice status are pulled back; the ledger shows what was paid, what is pending, what is overdue.
7. **Audit.** Every tool call the agent makes (PayPal or internal) is written to an immutable log with input, output and the agent's stated reason. The approval queue shows the reason next to each pending action.

## Agentic commerce angle
The agent holds a scoped set of tools: `list_bills`, `extract_bill`, `evaluate_policy`, `pay_bill`, `request_approval`, `create_customer_invoice`, `send_customer_invoice`, `get_payout_status`, `list_customer_invoices`. Money-moving tools refuse to run unless the bill is in `approved` state, which only policy or a human can set. The agent cannot approve its own payments.

## Stack
- Python 3.12, FastAPI, SQLite, httpx. One process, no build step.
- PayPal REST: OAuth2 client credentials, Payouts v1, Invoicing v2, Transaction Search v1 (reconciliation).
- Anthropic Claude (tool use) for extraction and chat; rule-based fallback.
- UI: single HTML page, AG Grid Community (CDN) for bills, ledger, customer invoices; chat panel; approval queue.
- Hosting: Render free web service (`render.yaml`).

## Repo layout
```
kassa/
  app/main.py          FastAPI app, routes, static UI
  app/paypal_client.py PayPal REST client (OAuth, payouts, invoices, transactions)
  app/store.py         SQLite schema and queries
  app/extract.py       LLM + rule-based invoice extraction
  app/policy.py        approval policy
  app/agent.py         tool-using agent for chat and the inbox pipeline
  app/static/index.html
  samples/             sample supplier invoices (email/PDF text)
  tests/
  render.yaml, requirements.txt, .env.example, LICENSE (MIT), README.md
```

## Demo script (video ≤3 min)
0:00 problem in one sentence, open dashboard (empty ledger).
0:20 drop three sample invoices → agent extracts, two auto-approved, one flagged (amount above limit, reason shown).
1:00 approve flagged one in queue → agent pays all three via Payouts; status PENDING→SUCCESS in ledger (sandbox).
1:40 chat: "invoice Fläkt 15 000 € for SafeSkillVR pilot, due 14 days" → PayPal invoice created and sent; link opens PayPal-hosted invoice.
2:20 audit log: every action with reason; agent refused to pay a duplicate.
2:45 stack slide, GitHub link.

## Milestones
- 19 Oct: PayPal client + store + extraction + policy with tests, runs locally against sandbox.
- 21 Oct: UI with AG Grid, chat agent, approval queue.
- 24 Oct: deployed on Render, README, sample data; Erik creates public GitHub repo.
- by 5 Nov: video, Devpost text; submit from Erik's Devpost account no later than 10 Nov.
