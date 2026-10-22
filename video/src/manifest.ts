import { staticFile } from "remotion";
import { getImageDimensions, getVideoMetadata } from "@remotion/media-utils";
import { FPS, MAX_RATE } from "./timeline";

export type Box = [number, number, number, number]; // x, y, w, h in 1920x1080 clip coordinates
export type ClipEvent = { t: number; what: string; x?: number; y?: number; box?: Box };
export type ClipEntry = { id: string; file: string; layout: "single" | "split" | "still"; company?: string; events?: unknown[] };
export type Manifest = { recorded_at?: string; clips: ClipEntry[] };
export type MediaInfo = { present: boolean; src?: string; durationSec?: number; width?: number; height?: number };
export type DemoProps = { manifest: Manifest | null; media: Record<string, MediaInfo> };

const withTimeout = <T,>(p: Promise<T>, ms: number) =>
  Promise.race([p, new Promise<T>((_, rej) => setTimeout(() => rej(new Error("timeout")), ms))]);

/**
 * Runs in the browser (calculateMetadata) at render time: reads public/clips/manifest.json
 * (public/clips is a symlink to ../clips) and probes every file it lists. Anything missing is
 * marked present:false and the composition draws a labelled grey frame instead.
 */
/** Used when clips/manifest.json is missing: the default file names, no events (so no callouts). */
const DEFAULT_CLIPS: ClipEntry[] = [
  { id: "intro", file: "intro.mp4", layout: "single" },
  { id: "limits", file: "limits.mp4", layout: "single" },
  { id: "scene1", file: "scene1.mp4", layout: "split" },
  { id: "scene2", file: "scene2.mp4", layout: "split" },
  { id: "scene3", file: "scene3.mp4", layout: "split" },
  { id: "chat", file: "chat.mp4", layout: "single" },
  { id: "paypal-paid", file: "paypal-paid.png", layout: "still" },
  { id: "paypal-cancelled", file: "paypal-cancelled.png", layout: "still" },
];

export async function loadMedia(): Promise<DemoProps> {
  let manifest: Manifest | null = null;
  try {
    const r = await fetch(staticFile("clips/manifest.json"), { cache: "no-store" });
    if (r.ok) manifest = (await r.json()) as Manifest;
  } catch {
    manifest = null;
  }
  const media: Record<string, MediaInfo> = {};
  const clips = manifest?.clips?.length ? manifest.clips : DEFAULT_CLIPS;
  for (const c of clips) {
    if (!c || typeof c.file !== "string") continue;
    const src = staticFile(`clips/${c.file}`);
    try {
      if (c.layout === "still" || /\.(png|jpe?g|webp)$/i.test(c.file)) {
        const d = await withTimeout(getImageDimensions(src), 15000);
        media[c.id] = { present: true, src, width: d.width, height: d.height };
      } else {
        const m = await withTimeout(getVideoMetadata(src), 20000);
        media[c.id] = { present: true, src, durationSec: m.durationInSeconds, width: m.width, height: m.height };
      }
    } catch {
      media[c.id] = { present: false };
    }
  }
  return { manifest, media };
}

export function eventsOf(m: Manifest | null, id: string): ClipEvent[] {
  const raw = m?.clips?.find((c) => c.id === id)?.events ?? [];
  return raw
    .filter(
      (e): e is ClipEvent =>
        typeof e === "object" && e !== null && typeof (e as ClipEvent).t === "number" && typeof (e as ClipEvent).what === "string",
    )
    .sort((a, b) => a.t - b.t);
}

export type Piece = { from: number; to: number }; // seconds in the clip

export type ClipPlan = {
  id: string;
  present: boolean;
  src?: string;
  rate: number; // playbackRate, <= MAX_RATE
  appearAt: number; // scene frame the clip appears at
  /** pieces laid end to end: clip seconds -> scene frames (relative to appearAt) */
  laid: { from: number; to: number; start: number; frames: number }[];
  /** frames (relative to appearAt) after which the last frame is held */
  playable: number;
  /** clip time (s) -> scene frame, or null if that moment is cut out */
  at: (t: number) => number | null;
  /** like at(), but moments before the first piece map to the clip's first frame */
  atOrStart: (t: number) => number | null;
};

/**
 * Lays the chosen clip pieces end to end in the time the clip is on screen. Plays faster when the
 * pieces are longer than that, but never more than MAX_RATE; what still does not fit is cut from
 * the end. A clip that runs out holds its last frame.
 */
export function planPieces(id: string, info: MediaInfo | undefined, pieces: Piece[], sceneFrames: number, appearAt = 0): ClipPlan {
  const visibleSec = (sceneFrames - appearAt) / FPS;
  const dur = info?.present && info.durationSec ? info.durationSec : visibleSec;
  const ps = pieces.map((p) => ({ from: Math.max(0, p.from), to: Math.min(dur, p.to) })).filter((p) => p.to > p.from + 0.05);
  if (!ps.length) ps.push({ from: 0, to: dur });
  const total = ps.reduce((s, p) => s + p.to - p.from, 0);
  const rate = Math.min(MAX_RATE, Math.max(1, total / visibleSec));
  const laid: ClipPlan["laid"] = [];
  let start = 0;
  for (const p of ps) {
    const frames = Math.floor(((p.to - p.from) / rate) * FPS);
    laid.push({ ...p, start, frames });
    start += frames;
  }
  const at = (t: number) => {
    for (const l of laid) if (t >= l.from && t <= l.to) return Math.round(appearAt + l.start + ((t - l.from) / rate) * FPS);
    return null;
  };
  return {
    id, present: !!info?.present, src: info?.src, rate, appearAt, laid,
    playable: Math.max(1, start - 1),
    at,
    atOrStart: (t: number) => (t < laid[0].from ? appearAt : at(t)),
  };
}

const ev = (events: ClipEvent[], re: RegExp) => events.find((e) => re.test(e.what));

/** Which parts of each recording are shown (decided from the manifest events). */
export function segmentsFor(id: string, events: ClipEvent[], info: MediaInfo | undefined, sceneSec: number): Piece[] {
  const dur = info?.durationSec ?? 1e9;
  if (id === "scene1") {
    // the whole take if it fits at <= MAX_RATE, else from the Send click minus 1 s
    if (dur / sceneSec <= MAX_RATE) return [{ from: 0, to: dur }];
    const send = ev(events, /Send invoice/);
    return [{ from: send ? send.t - 1 : 0, to: dur }];
  }
  if (id === "scene3") {
    // the first ~39 s are the wait for the re-send
    const toast = ev(events, /toast.*re-sent/);
    return [{ from: toast ? toast.t - 2.5 : 0, to: dur }];
  }
  if (id === "scene2") {
    const card = ev(events, /card under|card appears/);
    const closed = [...events].reverse().find((e) => /drawer closed/.test(e.what));
    return [{ from: card ? card.t - 8 : 0, to: closed ? closed.t + 0.3 : dur }];
  }
  if (id === "chat") {
    // the click, ~4 s of "Kassa is working", then from 1 s before the answer; Activity at the end
    const click = ev(events, /^click/);
    const answer = ev(events, /answer appears/);
    const act = ev(events, /Activity log visible|click Activity/);
    if (click && answer) {
      return [
        { from: Math.max(0, click.t - 1.7), to: click.t + 4 },
        { from: answer.t - 1, to: act ? act.t + 3.1 : dur },
      ];
    }
  }
  return [{ from: 0, to: dur }];
}

/** Kept for the intro and rules clips: the whole clip. */
export function planClip(id: string, info: MediaInfo | undefined, _events: ClipEvent[], sceneFrames: number, appearAt = 0): ClipPlan {
  return planPieces(id, info, [{ from: 0, to: info?.durationSec ?? (sceneFrames - appearAt) / FPS }], sceneFrames, appearAt);
}
