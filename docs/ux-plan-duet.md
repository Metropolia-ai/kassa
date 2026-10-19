# Kassa x Kassa: UX plan (product view, one company per screen)

## User
The owner of a 3-10 person studio (Dima at Frappua; Mika at Pixelforge Oy). Knows e-mail, PayPal, Excel;
does not know "purchase order", "payout batch", "MARKED_AS_PAID". Works on a laptop, 1366x768 or wider,
sometimes a phone. Opens Kassa when it asks, or when a supplier asks "why did you pay less?".

Assumptions (A1-A4, to confirm with Dima):
- A1: small companies have no formal purchase orders; "what we agreed" comes from a quote or an e-mail.
- A2: the owner wants to see the other company's agent only inside the bill's thread, never its settings.
- A3: one person per company decides; no approval chains.
- A4: for the hackathon the supplier is a second company that also runs Kassa; when it does not, the same
  thread would go by e-mail (not built, one sentence in the guide).

## Tasks
1. Dima: an invoice from Pixelforge arrived. Nothing to do: see that it was checked, argued and paid, and why.
   Done = the bill row says Paid with "Settled by the agents in 14 s, no one interrupted" and the thread is one click away.
2. Dima: Kassa needs him. Decide in one click with the numbers in front of him. Done = the card is gone,
   the bill goes on to Paid, the thread shows his decision.
3. Mika: send the October invoice to Frappua and get paid without chasing. Done = the invoice row says Paid,
   PayPal confirms, no e-mail written.
4. Dima, a week later: "Why did we pay Pixelforge 337 and not 272?" Ask Kassa, get the reason with evidence.
5. Dima, once: set what the agent may do alone, in three plain sentences.

## Screens and steps (labels as written)
Frappua's Kassa (`/?co=frappua`), the existing dashboard shell:
- Header: `Frappua`, `PayPal sandbox, balance EUR 93 000`, `Pays on its own up to [500] EUR`, link `Agent limits`, link `Switch to Pixelforge Oy`.
- `Needs you`: bills held by policy (as before) and decision cards from the agent:
  "Pixelforge Oy wants 1 800, your agent may go to 1 320" with buttons `Pay 1 800`, `Offer 1 500`, `Pay the order amount 1 200`, `Offer another amount`, `Reject the invoice`.
- `Bills to pay`: rows with stamps Paid / Sent / Held / Refused / **Checking** ("Checking with Pixelforge Oy's agent").
  Click a row: the bill drawer: what we agreed vs what is invoiced (differences in colour), evidence, the thread
  (one line per message, owner's decisions marked), PayPal invoice and payout links, the outcome line.
- `Activity`: every action with its reason, as before.
- `Ask Kassa`: "Why did we pay Pixelforge 337?" answers from the thread.

Pixelforge's Kassa (`/?co=pixelforge`): same shell, supplier role:
- `Invoices sent` tab opens first. Above the table: `Ready to send` with three drafts:
  "October render, 50 h" `Send invoice`, "Character animation, 2 scenes" `Send invoice`, "October render, resent" `Send invoice`.
- Rows: invoice number, customer `Frappua (uses Kassa)`, amount, status: Sent / Being checked / Paid / Withdrawn, `Open in PayPal`.
- `Needs you`: "Frappua's owner offers 1 500, below the 75 % floor you set" with `Accept 1 500` / `Decline`.

Both: threads advance on their own while a window is open (the page polls `/api/duet/tick` every 2 s).
Feedback: a toast when a bill arrives ("New bill from Pixelforge Oy, 337.00 EUR. Kassa is checking it."),
when it settles ("Paid 337.00 EUR to Pixelforge Oy. Settled by the agents in 14 s."), when a card appears.

## Walk (four questions) - fixed in the design
- Step "send invoice": the label is the user's verb; the result is a row with `Sent` and then `Being checked by Frappua`.
- Step "see it arrive": a toast plus a new row at the top with `Checking`; nothing to press.
- Step "decide": the card names the amounts and consequences; the safe option (order amount) is not styled as dangerous; `Reject` is red and last.
- Step "know it worked": the row says Paid and the drawer shows the PayPal payout and the receipt message.

## Off the happy path
- Two windows pressing at once: `tick` is idempotent per thread; a step that fails leaves the thread where it was and shows the error in the thread.
- PayPal slow: the stamp stays `Sent` until PayPal confirms; `Check PayPal status` asks now.
- Repeat: sending the resent draft twice is the duplicate case by design; sending the other drafts twice makes new invoice numbers.
- Empty state: seeded history (two months of paid bills and invoices) so the books never look newborn; the first visit opens the guide.
- Session: the access key stays in the browser; both company views share it.
