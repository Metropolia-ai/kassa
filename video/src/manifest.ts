import { staticFile } from "remotion";
import { getImageDimensions, getVideoMetadata } from "@remotion/media-utils";
import { FPS } from "./timeline";

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

export type ClipPlan = {
  id: string;
  present: boolean;
  src?: string;
  trimBefore: number; // frames into the clip
  rate: number; // playbackRate
  playable: number; // frames (scene-relative to the clip's appearance) before the clip runs out and freezes
  appearAt: number; // scene frame the clip appears at
  segStart: number; // seconds into the clip shown at appearAt
  /** clip time (s) -> scene frame */
  at: (t: number) => number;
};

/**
 * Picks the clip segment for a scene: from 1.5 s before the first event to 3 s after the last one
 * (whole clip when there are no events). If that segment is longer than the time the clip is on
 * screen, it plays faster (up to 3x); if the clip is too short it is shifted earlier and then
 * freezes on its last frame.
 */
export function planClip(id: string, info: MediaInfo | undefined, events: ClipEvent[], sceneFrames: number, appearAt = 0): ClipPlan {
  const visibleSec = (sceneFrames - appearAt) / FPS;
  const dur = info?.present && info.durationSec ? info.durationSec : visibleSec;
  let segStart = 0;
  let segEnd = dur;
  if (events.length) {
    segStart = Math.max(0, events[0].t - 1.5);
    segEnd = Math.min(dur, events[events.length - 1].t + 3);
  }
  const need = Math.max(0.1, segEnd - segStart);
  const rate = need > visibleSec ? Math.min(need / visibleSec, 3) : 1;
  segStart = Math.max(0, Math.min(segStart, dur - visibleSec * rate));
  const playable = Math.max(1, Math.floor(((dur - segStart) / rate) * FPS) - 2);
  return {
    id,
    present: !!info?.present,
    src: info?.src,
    trimBefore: Math.round(segStart * FPS),
    rate,
    playable,
    appearAt,
    segStart,
    at: (t: number) => Math.round(appearAt + ((t - segStart) / rate) * FPS),
  };
}
