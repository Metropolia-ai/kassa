# Kassa: demo video script (2:45)

Format: screen recording, 1920x1080, two Chrome windows side by side where the script says "split"
(left: Pixelforge Oy, Mika's Kassa; right: Frappua, Erik's Kassa). English voice-over, neutral, unhurried.
No music (the rules forbid third-party music). Short captions bottom-left name each scene. Light theme.
Everything shown is the hosted demo at kassa-duet.vercel.app with the PayPal sandbox; nothing is mocked in post.

| Time | On screen | Voice-over |
|---|---|---|
| 0:00–0:15 | Frappua's Kassa, "Bills to pay" with two months of bills. Caption: "The job nobody has time for". | Every small company has the same unpaid job: someone reads each supplier invoice, checks it against what was agreed, chases the supplier about the difference, and only then pays. Benchmarks put that at about two weeks and ten dollars of work per invoice. This is Kassa. It does that job, on PayPal. |
| 0:15–0:35 | Header, "Agent limits" dialog opens: three sentences with numbers. Then "Needs you" empty. Caption: "Your rules decide". | Kassa is an AI bookkeeper. You tell it, in three sentences, what it may do alone. Inside those limits it pays through PayPal Payouts. Outside them it brings the bill to you with the reason. Every decision is made by your rules; the model only writes the words. |
| 0:35–1:15 | Split. Left: "Ready to send", the card "October render, first half: 50 h", source line "Drafted by Kassa from your work log". Mika clicks **Send invoice**. Right: toast "New bill from Pixelforge Oy", row with stamp **Checking**; Erik clicks the row; the drawer fills in message by message: asked, explained, agreed, paid, confirmed; outcome "Settled by the agents in 14 s, no one interrupted". Cut: PayPal sandbox invoice page shows PAID. Caption: "Two bookkeepers, one invoice". | Pixelforge also runs Kassa. Mika sends the October invoice: a real PayPal invoice. Frappua's bookkeeper finds fifty hours where the order said forty, and asks. Pixelforge's bookkeeper answers from its work log: the extra ten hours were ordered by Frappua's own producer, by e-mail, on the twelfth. That is inside Erik's limit for documented changes, so it pays by PayPal Payout, and Pixelforge's bookkeeper records the payment. Fourteen seconds. Nobody was interrupted. |
| 1:15–1:55 | Split. Mika sends "Character animation, 2 scenes". Right: **Checking**, then a card under "Needs you": "Pixelforge Oy wants 1 800.00 EUR, the agent may go to 1 320.00 EUR" with the buttons. Erik clicks **Pay 1 800.00 EUR as asked**. Left: the row goes Being checked → Paid; the old invoice shows Withdrawn, the reissued one Paid. Caption: "People only when it matters". | The second invoice is double the order: a second scene, agreed only in a call, nothing in writing. The two bookkeepers go as far as their owners allowed and stop. Erik gets a card with the numbers and one click. He pays eighteen hundred. Pixelforge's bookkeeper reissues the invoice for the agreed amount, Frappua's pays it, PayPal confirms. |
| 1:55–2:15 | Right: toast "Another bill from Pixelforge Oy, €337.00, re-sent by their system"; row **Checking**, then **Refused** with "withdrawn by Pixelforge Oy: same work as PF-2026-0418, already paid". Left: row Withdrawn. Cut: PayPal invoice CANCELLED. Caption: "A duplicate, caught". | A minute later, Pixelforge's old invoicing system re-sends the first invoice under a new number. Frappua's bookkeeper recognises the same work, same amount, already paid, and asks. Pixelforge's bookkeeper checks its books and withdraws the PayPal invoice. Nobody saw it. |
| 2:15–2:35 | Right: "Ask Kassa": "Why did we pay Pixelforge Oy more than we agreed?" The answer appears with the amounts and the e-mail reference. Then the Activity tab. Caption: "Every decision, with its reason". | A week later Erik asks why they paid 337 instead of 272. Kassa answers from the conversation, with the e-mail that approved the extra hours. Every action is in the log with the reason given at the time. |
| 2:35–2:45 | Both windows. On-screen line: "Live: PayPal sandbox Invoicing v2, Payouts, record-payment; LLM via OpenRouter. Seeded: two months of history, the supplier's work log." Then the repo and demo links. | Kassa. Two bookkeepers that settle an invoice between themselves, and people only when it matters. Built on PayPal Invoicing and Payouts, open source, links below. |

## Production notes
- Record on the hub: Chrome as `erik`, two windows tiled 960 px each, `ffmpeg -f x11grab`; drive clicks with the
  computer-use MCP so the timing is repeatable. Start from "Start over" so the numbers match the script.
- The bookkeepers' messages are written by the model, so the wording differs run to run; the script quotes facts,
  not sentences. If a run wanders, record the scene again.
- Voice: synthesized English (Piper or edge-tts), or Erik's own voice if he prefers; same text.
- The "two weeks, ten dollars" opening comes from Ardent Partners' State of ePayables benchmarks as cited by
  secondary sources (9–17 days, about $10–13 per invoice). If we cannot cite the primary report, drop the numbers
  and keep "someone reads every invoice".
- The duplicate's 45-second delay (`DUET_RESEND_AFTER_S`) can be shortened for the recording.
