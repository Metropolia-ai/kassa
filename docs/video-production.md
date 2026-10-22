# Kassa demo video: production plan

Script: docs/video-script.md (2:45). Target: 1920x1080, 30 fps, H.264 + AAC, no music.
Everything lives in `video/` (Remotion project, Node 18, renders with the system Chrome).

## Pipeline
1. **Screen clips** recorded from the hosted demo on a virtual display (Xvfb :99, 1920x1080), Chrome in `--app`
   mode (no tabs, no address bar), cursor hidden; ffmpeg x11grab at 30 fps. Output `video/clips/*.mp4` and
   `video/clips/manifest.json`.
2. **Voice-over** per scene with edge-tts (`/root/Frappua/projects/paypal-agent/.venv/bin/python -m edge_tts`),
   voice `en-GB-RyanNeural`, rate -5 %. Output `video/public/audio/<scene>.mp3`. Scene length = max(audio + 0.6 s,
   the clip segment it shows).
3. **Composition** in Remotion: title cards, framed clips with animated callouts, stamps, the architecture
   infographic, captions, closing card. Render `video/out/kassa-demo.mp4`.

## Look
Kassa's own language: ledger paper `#E3EAE0`, sheet `#F0F4EE`, ink `#1B2A3F`, pencil `#56645E`, green `#1F6B45`,
red `#B42318`, amber `#855700`, purple for the other company `#5B3A8C`. Font Schibsted Grotesk (Google Fonts).
Rubber-stamp animation (scale from 1.6 with a slight rotation, 0.35 s) for every outcome word: SETTLED, PAID,
WITHDRAWN, YOUR TURN. Clips sit in a thin window frame with a 10 px shadow on paper; two frames side by side for
the split scenes. Callouts: a circle that draws itself around the element plus a short label; a small ink dot
marks each click. Captions bottom-left, 36 px, ink on a paper chip. No stock icons, no gradients, no 3D.

## Clip manifest contract (`video/clips/manifest.json`)
```json
{ "recorded_at": "2026-10-20T18:00:00Z",
  "clips": [
    { "id": "intro", "file": "intro.mp4", "layout": "single", "company": "frappua",
      "events": [ { "t": 2.0, "what": "page loaded, bills visible" } ] },
    { "id": "limits", "file": "limits.mp4", "layout": "single", "events": [ { "t": 1.5, "what": "click Agent limits", "x": 940, "y": 48 }, { "t": 2.2, "what": "dialog open" } ] },
    { "id": "scene1", "file": "scene1.mp4", "layout": "split",
      "events": [ { "t": 3.0, "what": "click Send invoice", "x": 110, "y": 600 }, { "t": 6.5, "what": "toast New bill (right)" },
                  { "t": 9.0, "what": "click bill row (right)", "x": 1200, "y": 500 }, { "t": 12.0, "what": "message: asked" },
                  { "t": 20.0, "what": "message: explained" }, { "t": 27.0, "what": "message: agreed" },
                  { "t": 33.0, "what": "message: paid" }, { "t": 38.0, "what": "message: confirmed, outcome line" } ] },
    { "id": "scene2", "file": "scene2.mp4", "layout": "split", "events": [ "... send, card appears (right), click Pay 1 800, reissued (left), paid" ] },
    { "id": "scene3", "file": "scene3.mp4", "layout": "split", "events": [ "... toast re-sent, Checking, Refused (right), Withdrawn (left)" ] },
    { "id": "chat", "file": "chat.mp4", "layout": "single", "events": [ "... question typed, answer appears, Activity tab" ] },
    { "id": "paypal-paid", "file": "paypal-paid.png", "layout": "still" },
    { "id": "paypal-cancelled", "file": "paypal-cancelled.png", "layout": "still" }
  ] }
```
`t` is seconds from the start of that clip; `x`,`y` are screen coordinates (1920x1080) of a click when there was one.
The composition reads the manifest and places callouts at `events`; missing clips render as a labelled grey frame
so the composition can be built before the recordings exist.

## Recording notes
- Reset the demo first (`POST /api/duet/reset` with the access key) so the numbers match the script.
- Left window: Pixelforge `?co=pixelforge`, right window: Frappua `?co=frappua`, each 960x1080, `--app=` mode,
  separate `--user-data-dir`. Enter the access key into the gate dialog with xdotool (click the field, type, Enter).
- Single-window scenes use one Frappua window at 1920x1080.
- The bookkeepers' messages take 5–15 s each (real model, real PayPal); record continuously and log the moments.
- The re-sent duplicate arrives ~45 s after the first invoice settles; keep recording scene 3 from the end of scene 1
  or start a new clip and wait.
- PayPal stills: the invoice's `pay_url` (recipient view, no login) after it is paid and after it is cancelled.
