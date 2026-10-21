# Devpost gallery: Kassa (PayPal AI Hackathon)

All images are PNG, 1800x1200 (3:2), light theme. Screens 01-09 are real screenshots of the hosted demo
(https://kassa-duet.vercel.app) taken on 21 Oct 2026 after one full run of the flow from a clean reset.

| File | What it shows |
|---|---|
| 01-bills.png | Frappua, "Bills to pay": header with company, balance and "Pays on its own up to 2000 EUR"; the 1 800 EUR bill (Paid, owner decided), the Refused duplicate, the 337 EUR bill Paid by the agents, older Paid bills. |
| 02-limits.png | Frappua, the "Agent limits" dialog: 10 % over what was agreed, never more than 150 EUR, 25 % when the extra work was ordered in writing. |
| 03-ready-to-send.png | Pixelforge, "Invoices sent" with the "Ready to send" block: the two drafts with their source lines ("Drafted by Kassa from your work log ..."), before anything was sent. |
| 04-drawer-settled.png | Frappua, drawer of the 337.00 bill: agreed vs invoiced table (40 vs 50 render hours) and the first messages between the two bookkeepers. |
| 04b-drawer-settled-end.png | The same drawer scrolled to the end: last messages and the outcome line "Settled by the agents in 23 s, no one interrupted". |
| 05-needs-you.png | Frappua, the decision card under "Needs you" for the 2 400 EUR invoice: Pixelforge wants 1 800 EUR, the agent may go to 1 320 EUR; buttons incl. "Pay 1 800.00 EUR as asked". |
| 06-duplicate.png | Frappua, drawer of the Refused duplicate PF-2026-0444: "withdrawn by Pixelforge Oy: same work as PF-2026-0443", the three messages and the Withdrawn outcome line. |
| 07-invoices-sent.png | Pixelforge, "Invoices sent" after the flow: reissued PF-2026-0445R Paid, PF-2026-0445 and the duplicate Withdrawn, PF-2026-0443 Paid. |
| 08-ask-kassa.png | Frappua, "Ask Kassa": "Why did we pay Pixelforge Oy more than we agreed?" and the answer explaining both overpayments. |
| 09-activity.png | Frappua, "Activity" tab: every action with who did it and the reason given at the time. |
| 10-architecture.png | Architecture infographic, rendered from architecture.html with headless Chrome. |
| thumbnail.png | Closing card of video/out/kassa-demo.mp4 (frame at 2:54), padded to 3:2 with the paper colour. |

Re-render the infographic:
`google-chrome --headless=new --hide-scrollbars --screenshot=$PWD/10-architecture.png --window-size=1800,1200 file://$PWD/architecture.html`
