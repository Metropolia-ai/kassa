# Kassa demo video (Remotion)

Script: `../docs/video-script.md`. Look, pipeline and clip manifest contract: `../docs/video-production.md`.
Output: `out/kassa-demo.mp4`, 1920x1080, 30 fps, H.264 + AAC, voice-over only (no music).

## Commands
```bash
npm run audio     # voice-over: one mp3 per scene (edge-tts, en-GB-RyanNeural, -5 %) + src/audioConfig.ts
npm run render    # full video -> out/kassa-demo.mp4 (17 min on the hub, 20 Oct)
npm run still -- --frame=1500   # one frame -> out/still.png
npm run studio    # live preview in the browser
npm run sheet     # contact sheet of the render -> out/sheet.png (one frame every 5 s)
```
All render commands use the system Chrome (`--browser-executable=/usr/bin/google-chrome`).

## Clips and the manifest
- Render only when the recorder is done: a clip deleted or rewritten during a render makes it fail (404).
- The recordings go to `video/clips/` with `video/clips/manifest.json` (contract in docs/video-production.md).
- `public/clips` is a symlink to `video/clips`. It must point to an **absolute** path, because Remotion copies
  `public/` into a temporary bundle and keeps symlinks as they are. `scripts/link-clips.mjs` creates it and runs
  automatically before `render`, `still` and `studio` (npm `pre*` scripts). The link is in `.gitignore`.
- The manifest is read **at render time** in the browser (`calculateMetadata` in `src/Root.tsx` ->
  `loadMedia()` in `src/manifest.ts`): `fetch(staticFile("clips/manifest.json"))`, then every file it lists is
  probed (video duration and size, image size). So new clips need no code change: drop them in, `npm run render`.
- A clip that is missing renders as a grey window frame labelled `clip: <id>`; a missing still as `still: <id>`.
  No manifest at all: the default file names (`intro.mp4`, `limits.mp4`, `scene1.mp4` ... `paypal-paid.png`,
  `paypal-cancelled.png`) are tried, with no events. No events = no callouts; stamps then fall back to fixed
  times that follow the voice-over.

Scene order: intro, rules, scene1, scene3, scene2, chat, closing (the duplicate comes straight after scene1).
Scene -> clip: intro -> `intro`, rules -> `limits`, scene1/2/3 -> `scene1/2/3` (split), chat -> `chat`,
stills `paypal-paid` (end of scene1) and `paypal-cancelled` (end of scene3). The closing card has no clip.
Clip area for single and split scenes: 1840x1035 (margins 40).

### Which part of a clip is shown (`segmentsFor()` in `src/manifest.ts`)
Chosen from the manifest events; a clip is sped up at most 1.3x (`MAX_RATE`), what still does not fit is cut
from the end, a clip that runs out holds its last frame.
- scene1: the whole take if it fits at <= 1.3x, else from the Send click minus 1 s.
- scene3: from the "toast ... re-sent" event minus 2.5 s (the first ~39 s are the wait for the re-send).
- scene2: from the "card under Needs you" event minus 8 s to the last "drawer closed" + 0.3 s.
- chat: two pieces: from 1.7 s before the click to 4 s after it ("Kassa is working"), then from 1 s before
  "answer appears" to 3.1 s after "Activity log visible".
- intro, limits: the whole clip.

### How events become callouts (`src/overlays.tsx`)
Labels are fixed words picked by the event text; raw event text is never shown.
| event text contains | label |
|---|---|
| `click ... Send invoice` | Mika presses Send |
| `toast` + `New bill` | the invoice arrives |
| `click bill row` / `drawer open` | Erik opens the bill (one callout for both) |
| `card under` / `card appears` | Erik's decision |
| `click Pay 1` | one click |
| `re-sent` | re-sent by their system |
| `Refused` (capital R) | refused |
| `Withdrawn` (capital W) | withdrawn |
| `answer appears` (chat) | the answer |
`message: ...` events draw nothing; they light the step chips. Any other event: no callout. Every click with
`x`,`y` gets an ink dot. Click callouts start 0.6 s before the click. Positions: the event's optional
`"box": [x, y, w, h]`, else the click point, else boxes measured on the recordings (toast bottom-left of a window,
the rows that change in scene2/scene3, the decision card, the chat answer).

Focus moves: each click callout (and the chat answer) eases a 1.35x zoom onto its point over 12 frames, holds while
the callout is on, eases back. While the bill drawer is open on the right (from "drawer open" to "drawer
closed", or the scene end) the camera holds 1.25x on the lower right (the messages). The centre is clamped, so the
paper behind the frame never shows; the two title bars follow the seam between the windows.

Step chips (bottom left, under the caption), fixed words lit at their events: scene1 asked, explained, agreed,
paid, confirmed; scene3 arrives, asked, withdrawn; scene2 checked, your turn, one click, reissued, paid.

Stamps: scene1 SETTLED with the seconds from the outcome text ("in 25 s") and 0 PEOPLE; scene3 WITHDRAWN, 0 PEOPLE;
scene2 YOUR TURN at the card, PAID with "1 decision by a person" at "Settled in".

## Durations
Scene length = max(voice-over + 0.6 s, the scene minimum from the script's timecodes), except where the
recording sets it (`LENGTH` in `src/timeline.ts`: scene1 41 s, scene2 38 s, chat 18.7 s), never shorter than
the voice-over + 0.6 s. Total 2:54.8. Transitions are a paper wipe of 8 frames out and 8 in, inside the
scenes, so the total is exactly the sum of the scenes. Voice-over timings for the animations come from the
sentence cues edge-tts writes next to each mp3 (`public/audio/<scene>.srt`).

## Files
- `src/Root.tsx`: compositions `KassaDemo` (and the old `Smoke` test).
- `src/KassaDemo.tsx`: the scene series, one `<Audio>` per scene.
- `src/scenes/*`: Intro, Rules, Split (scene1, scene2, scene3), Chat, Closing.
- `src/components.tsx`: paper, caption chip, paper wipe, stamp, window frame + clip, callout, ink dot, PiP.
- `src/theme.ts`: Kassa colours; Schibsted Grotesk from `public/fonts/*.woff2` (downloaded from Google Fonts,
  bundled locally so the render does not depend on the network).
- `scripts/make_audio.py`: voice-over from the script table (texts taken verbatim from the Voice-over column).
