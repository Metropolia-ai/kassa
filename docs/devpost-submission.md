# Devpost submission: Kassa (PayPal AI Hackathon 2026)

Draft project on Devpost: https://devpost.com/submit-to/31302-paypal-ai-hackathon/manage/submissions/1251813-kassa
(Erik's account). Status: submitted 22 Oct 2026, editable until 12 Nov 2026 12:00 PT. The access key for judges goes only into the testing
instructions field, never into this file.

## Project overview
- **Project name:** Kassa
- **Elevator pitch (≤200):** An AI bookkeeper for small companies: it checks each supplier invoice against
  what was agreed, settles the difference with the supplier's own bookkeeper and pays through PayPal within
  limits you set.
- **Thumbnail:** docs/devpost/thumbnail.png (3:2)

## Project details: About the project (Markdown)

## Inspiration

Every small company has the same unpaid job. Someone reads each supplier invoice, checks it against the order, writes to the supplier about the difference, waits, and only then pays. It is not hard work, it is interrupting work, and it lands on the person who should be doing something else. Benchmarks for accounts payable put a manual invoice at days of cycle time and around ten dollars of handling.

We wanted a bookkeeper that does this job inside limits the owner writes in three sentences, pays through PayPal when the rules say it may, and brings a bill to a person only when the rules say it must. Then we asked the obvious next question: what happens when the supplier *also* has one?

## What it does

**Kassa** is an AI bookkeeper that lives on PayPal.

- It receives supplier invoices (PayPal Invoicing v2), reads them, and checks each one against what was agreed: the purchase order, the delivery log, the owner's limits.
- When the invoice differs from the order, it asks the supplier. If the supplier's company runs Kassa too, the two bookkeepers talk to each other: question, evidence, concession, agreement. Each one goes exactly as far as its owner's policy allows and no further.
- Inside the limits it pays by **PayPal Payouts** and the supplier's Kassa records the payment on the invoice (`/v2/invoicing/invoices/{id}/payments`). Outside the limits the owner gets a decision card with the numbers and one click; the bookkeepers finish the paperwork (cancel and reissue the invoice, pay, record).
- It catches what people miss: an invoice re-sent under a new number for work already paid is recognised (same supplier, same amount, within 30 days), queried, and withdrawn by the supplier's bookkeeper. Nobody is interrupted.
- Every action goes to an audit log with the reason given at the time, and the owner can ask Kassa in plain language why something was paid; the answer comes from the real conversation, with the e-mail that approved the extra hours.

The demo runs two companies in one deployment, **Pixelforge Oy** (the supplier, Mika's Kassa) and **Frappua** (the buyer, Erik's Kassa), each with its own PayPal sandbox business account, its own books and its own rules. You can switch between them and watch an invoice settle from both sides.

## How we built it

- **Policy decides, the model only writes the words.** `app/duet.py` is a state machine (new → invoiced → disputed → answered → agreed → ready → paid → settled, or needs_humans, or closed). For every step the owner's policy computes the allowed action: accept within tolerance, accept a documented change up to a higher ceiling, counter with a concession, stop at the floor, escalate. The language model (via OpenRouter) phrases the message; without a model key the agents speak in plain templates and the outcome is identical.
- **PayPal REST, sandbox:** OAuth2, Invoicing v2 (create and send, cancel, record payment), Payouts v1 (pay, refresh batch status). Sequential invoice numbers are kept in the database because PayPal remembers every number an account has used.
- **One deployment, two companies:** FastAPI on Vercel (Python serverless), Neon Postgres with a schema per company plus a shared schema for the threads. Each company's page only ever calls `/api/duet/companies/{co}/...`, so one side never reads the other side's settings.
- **The clock:** whichever browser window is open calls `POST /api/duet/tick` every 2.5 s; the engine advances every active thread, with a per-thread claim so two windows never process the same step twice.
- **UI:** static HTML, AG Grid for the tables, a ledger look with rubber stamps for statuses, a drawer that shows what was agreed, what was invoiced and what the two bookkeepers said, and a decision card when a person is needed.

## Challenges we ran into

- **PayPal's Balances API is a snapshot** (hourly or daily) and never reflected money moved in the sandbox, so the header balance is kept from an opening balance minus the Payouts ledger.
- **PayPal refuses a reused invoice number**, which killed the naive "send the same invoice twice" duplicate. The real-world version is better anyway: same work, new number, caught by matching supplier and amount.
- **Pooled Postgres connections leak `SET search_path`** between sessions; tables appeared in the wrong schema until every store used a direct connection.
- **Two windows, one thread:** an inline send and a background tick once processed the same step twice and created two PayPal invoices. Fixed with a database claim on the thread.
- Making it feel like a product rather than a scripted demo: one company per screen, a real "Send invoice" button, drafts that come from a work log, a duplicate that arrives by itself.

## Accomplishments that we're proud of

- Two AI bookkeepers settle a disputed invoice between themselves in under a minute, on real PayPal sandbox objects, and the owner reads about it afterwards.
- The agent can never pay something it was not allowed to: `pay_bill` refuses anything not approved by policy or by a person, and that is enforced in code, not in a prompt.
- The duplicate invoice is caught and withdrawn without a human ever seeing it.
- The whole thing runs on free tiers: Vercel Hobby, Neon free, PayPal sandbox.

## What we learned

- Put the rules in code and keep the model for language. The demo is deterministic where money is concerned and still reads like two people writing to each other.
- Agents talking to agents need the same things people do: a shared reference (the order), evidence (the work log), a ceiling, a floor, and an owner to call when those run out.
- Sandboxes have opinions. Half the work was learning what PayPal remembers, what it refuses, and what it only updates once an hour.

## What's next for Kassa

- Real inboxes: invoices arriving by e-mail and PDF for the buyer side, with the existing extractor.
- A supplier directory, so the first invoice from a new company is checked against its past behaviour, not just its numbers.
- PayPal production credentials and a second currency.
- A shared protocol so a Kassa can talk to another company's bookkeeper even when that bookkeeper is a person with an e-mail address.

## What is live and what is seeded

| Live in the demo | Seeded for the demo |
|---|---|
| PayPal Invoicing v2: create, send, cancel, record payment (sandbox) | Two months of ordinary paid bills on both sides |
| PayPal Payouts v1: pay and refresh status (sandbox) | The purchase orders and the supplier's work log |
| Every message the two bookkeepers write (LLM via OpenRouter) | The three invoices waiting on the supplier's side |
| Policy decisions, audit log, "Ask Kassa" | The supplier's old system re-sending an invoice after ~45 s |

## Built with (tags)
python, fastapi, paypal, paypal-invoicing, paypal-payouts, postgresql, neon, vercel, openrouter, ag-grid, html, javascript, httpx, pydantic, remotion

## "Try it out" links
- https://kassa-duet.vercel.app (hosted demo, access key in the testing instructions)
- https://github.com/Metropolia-ai/kassa (source, MIT)

## Video
https://youtu.be/UST7GK1FZNI

## Image gallery (order)
docs/devpost/01-bills.png … 10-architecture.png, see docs/devpost/README.md

## Testing instructions (for the Additional info step; paste the key from secrets/kassa-access.env)

1. Open https://kassa-duet.vercel.app and enter the access key when asked: `<KASSA_ACCESS_KEY>`. It is stored in your browser; "Lock" in the header forgets it.
2. You start as **Frappua**, the buyer. Open **Agent limits** in the header to see the three rules the bookkeeper follows. Click **Switch to Pixelforge Oy** to see the supplier's side.
3. On the Pixelforge side, under **Ready to send**, press **Send invoice** on "October render, first half: 50 h". Switch back to Frappua (or keep both open in two tabs) and watch the bill go Checking → Paid; click the row to read what the two bookkeepers said. It takes 30–60 s. About 45 s later the supplier's old system re-sends the same work under a new number: watch it arrive, get queried and be withdrawn.
4. Send "Character animation, 2 scenes" from Pixelforge. This one is double the order and only agreed in a call, so Frappua's owner gets a card under **Needs you**. Pick an option; the bookkeepers reissue, pay and record.
5. Ask Kassa (bottom of the Frappua page): "Why did we pay Pixelforge Oy more than we agreed?" Open the **Activity** tab for the audit log.
6. The demo state is shared between everyone who tests. **Start over** in the header resets both companies to the beginning (two months of history, three drafts); please use it if the screen does not match the steps above. PayPal objects are real sandbox invoices and payouts; links in the drawer open the sandbox invoice pages.

Local run without any keys: see README.md ("Run it" and "Kassa × Kassa"); with `DUET=1` and no model key the bookkeepers speak in templates and the flow is the same.
