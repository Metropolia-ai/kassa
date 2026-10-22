import React from "react";
import { AbsoluteFill, Easing, Freeze, Img, OffthreadVideo, Sequence, interpolate, useCurrentFrame } from "remotion";
import { C, FONT } from "./theme";
import { FPS, WIPE, sec } from "./timeline";
import type { Box, ClipPlan, MediaInfo } from "./manifest";

export type Rect = { x: number; y: number; w: number; h: number };
export const BAR = 30; // window title bar height
/** Clip area for single and split scenes: 1840 px wide (margins 40), 16:9, title bar above. */
export const FULL: Rect = { x: 40, y: 38, w: 1840, h: 1035 };

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/* ---------- background, caption, wipe ---------- */

export const Paper: React.FC<{ children?: React.ReactNode }> = ({ children }) => (
  <AbsoluteFill style={{ background: C.ledger, fontFamily: FONT, color: C.ink }}>{children}</AbsoluteFill>
);

export const Caption: React.FC<{ text: string; from?: number; bottom?: number }> = ({ text, from = 6, bottom = 34 }) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [from, from + 10], [0, 1], clamp);
  const x = interpolate(f, [from, from + 12], [-30, 0], { ...clamp, easing: Easing.out(Easing.cubic) });
  return (
    <div
      style={{
        position: "absolute", left: 56, bottom, opacity: o, zIndex: 45, transform: `translateX(${x}px)`,
        background: C.sheet, border: `1px solid ${C.rule}`, borderLeft: `6px solid ${C.ink}`, borderRadius: 6,
        padding: "10px 24px 12px", fontSize: 36, fontWeight: 600, color: C.ink, boxShadow: `0 6px 18px ${C.shade}`,
        whiteSpace: "nowrap",
      }}
    >
      {text}
    </div>
  );
};

/** A sheet of paper that sweeps off at the start of a scene and back on at its end. */
export const PaperWipe: React.FC<{ frames: number; wipeIn?: boolean; wipeOut?: boolean }> = ({ frames, wipeIn = true, wipeOut = true }) => {
  const f = useCurrentFrame();
  let x: number | null = null;
  if (wipeIn && f < WIPE) x = interpolate(f, [0, WIPE], [0, 2000], { ...clamp, easing: Easing.in(Easing.cubic) });
  if (wipeOut && f >= frames - WIPE) x = interpolate(f, [frames - WIPE, frames - 1], [-2000, 0], { ...clamp, easing: Easing.out(Easing.cubic) });
  if (x === null) return null;
  return (
    <div style={{ position: "absolute", top: 0, bottom: 0, left: 0, width: 1920, transform: `translateX(${x}px)`, background: C.sheet, boxShadow: `0 0 30px ${C.shade}`, borderLeft: `2px solid ${C.rule}`, borderRight: `2px solid ${C.rule}` }} />
  );
};

/* ---------- stamp ---------- */

/** A stamp is a verdict, not a label: it lands, stays this long, then lifts so the screen is readable again. */
export const STAMP_LIFE = sec(3.5);

export const Stamp: React.FC<{
  at: number; text: string; sub?: string; color?: string; size?: number; rotate?: number;
  x: number; y: number; // centre on screen
  hideAt?: number;
}> = ({ at, text, sub, color = C.green, size = 110, rotate = -4, x, y, hideAt = at + STAMP_LIFE }) => {
  const f = useCurrentFrame() - at;
  if (f < 0 || f + at > hideAt + 10) return null;
  const d = sec(0.35);
  const p = interpolate(f, [0, d], [0, 1], { ...clamp, easing: Easing.bezier(0.2, 0.9, 0.3, 1.15) });
  const scale = interpolate(p, [0, 1], [1.6, 1]);
  const rot = interpolate(p, [0, 1], [rotate - 7, rotate]);
  let o = interpolate(f, [0, 4], [0, 1], clamp);
  if (hideAt !== undefined) o *= interpolate(f + at, [hideAt, hideAt + 8], [1, 0], clamp);
  return (
    <div style={{ position: "absolute", left: x, top: y, transform: `translate(-50%, -50%) scale(${scale}) rotate(${rot}deg)`, opacity: o, zIndex: 30 }}>
      <div
        style={{
          color, border: `${Math.max(5, size / 14)}px solid ${color}`, borderRadius: 10, padding: `${size * 0.08}px ${size * 0.28}px ${size * 0.1}px`,
          background: "rgba(250,251,248,0.94)", fontWeight: 800, letterSpacing: "0.07em", textTransform: "uppercase",
          textAlign: "center", lineHeight: 1.05, whiteSpace: "nowrap", boxShadow: `0 4px 0 ${color}22`,
        }}
      >
        <div style={{ fontSize: size }}>{text}</div>
        {sub ? <div style={{ fontSize: size * 0.42, marginTop: size * 0.08, letterSpacing: "0.09em", textTransform: "none" }}>{sub}</div> : null}
      </div>
    </div>
  );
};

/* ---------- window frames and clips ---------- */

/** The clip pieces laid end to end, then the last frame held. */
const ClipVideo: React.FC<{ plan: ClipPlan }> = ({ plan }) => {
  const f = useCurrentFrame();
  const style = { width: "100%", height: "100%", objectFit: "cover" as const };
  const last = plan.laid[plan.laid.length - 1];
  const video = (l: ClipPlan["laid"][number]) => (
    <OffthreadVideo src={plan.src!} trimBefore={Math.round(l.from * FPS) || undefined} playbackRate={plan.rate} muted style={style} />
  );
  return (
    <>
      {plan.laid.map((l, i) => (
        <Sequence key={i} from={l.start} durationInFrames={Math.max(1, l.frames)} layout="none">
          {video(l)}
        </Sequence>
      ))}
      {f >= last.start + last.frames ? (
        <Sequence from={last.start} layout="none">
          <Freeze frame={Math.max(0, last.frames - 2)}>{video(last)}</Freeze>
        </Sequence>
      ) : null}
    </>
  );
};

export const Placeholder: React.FC<{ label: string }> = ({ label }) => (
  <div style={{ position: "absolute", inset: 0, background: "#CDD3CC", display: "flex", alignItems: "flex-start", justifyContent: "center", paddingTop: "12%", boxSizing: "border-box" }}>
    <div style={{ fontSize: 40, fontWeight: 600, color: "#6E7A74", letterSpacing: "0.04em", fontFamily: "ui-monospace, monospace", background: "#CDD3CC", padding: "0 20px" }}>{label}</div>
  </div>
);

type Pane = { label: string; color: string };

/** A focus move: zoom z centred on (x, y) in clip coordinates, eased in from `at`, held to `until`. */
export type Zoom = { at: number; until: number; x: number; y: number; z: number };
export const ZOOM_EASE = 12;

/** Current zoom: the strongest zoom wins the scale, the centre is the weighted mix (smooth pans). */
export function zoomAt(f: number, zooms: Zoom[]): { z: number; x: number; y: number } {
  let zmax = 1, wx = 0, wy = 0, ws = 0;
  for (const zm of zooms) {
    const up = interpolate(f, [zm.at, zm.at + ZOOM_EASE], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
    const down = interpolate(f, [zm.until, zm.until + ZOOM_EASE], [1, 0], { ...clamp, easing: Easing.inOut(Easing.cubic) });
    const w = Math.min(up, down);
    if (w <= 0) continue;
    zmax = Math.max(zmax, 1 + (zm.z - 1) * w);
    wx += zm.x * w; wy += zm.y * w; ws += w;
  }
  return ws > 0 ? { z: zmax, x: wx / ws, y: wy / ws } : { z: 1, x: 960, y: 540 };
}

/**
 * A clip in a thin window frame on paper. layout "split": one 1920x1080 recording that holds both
 * windows, drawn as two frames over its two halves. `zooms` move the camera inside the frame; the
 * centre is clamped so the frame is always filled, and the two title bars follow the seam.
 */
export const ClipStage: React.FC<{
  rect: Rect; plan: ClipPlan; split?: boolean; panes: Pane[]; opacity?: number; scale?: number; bar?: number; zooms?: Zoom[];
  children?: (s: number) => React.ReactNode;
}> = ({ rect, plan, split, panes, opacity = 1, scale = 1, bar = BAR, zooms = [], children }) => {
  const f = useCurrentFrame();
  const s = rect.w / 1920;
  const W = rect.w, H = rect.h;
  const zm = zoomAt(f, zooms);
  const z = zm.z;
  const cx = Math.min(Math.max(zm.x * s, W / (2 * z)), W - W / (2 * z));
  const cy = Math.min(Math.max(zm.y * s, H / (2 * z)), H - H / (2 * z));
  const tx = W / 2 - cx * z, ty = H / 2 - cy * z;
  const seam = Math.min(W, Math.max(0, tx + (W / 2) * z)); // where the middle of the recording is on screen
  const bars = split
    ? [{ x: 0, w: seam - 5, pane: panes[0] }, { x: seam + 5, w: W - seam - 5, pane: panes[1] }]
    : [{ x: 0, w: W, pane: panes[0] }];
  return (
    <div style={{ position: "absolute", left: rect.x, top: rect.y - bar, width: W, height: H + bar, opacity, transform: `scale(${scale})`, transformOrigin: "50% 50%" }}>
      <div style={{ position: "absolute", inset: 0, background: C.sheet, border: `1px solid ${C.rule}`, borderRadius: 8, boxShadow: `0 10px 10px -2px ${C.shade}, 0 0 10px ${C.shade}` }} />
      {split ? <div style={{ position: "absolute", left: seam - 5, width: 10, top: 0, height: bar, background: C.ledger }} /> : null}
      {bars.map((b, i) =>
        b.w > 0 ? (
          <div key={i} style={{ position: "absolute", left: b.x, width: b.w, top: 0, height: bar, overflow: "hidden", display: "flex", alignItems: "center", padding: "0 14px", gap: 10, fontSize: 21, fontWeight: 600, color: b.pane?.color ?? C.pencil, whiteSpace: "nowrap", boxSizing: "border-box", opacity: b.w > 260 ? 1 : 0 }}>
            <span style={{ width: 10, height: 10, borderRadius: 5, background: b.pane?.color ?? C.pencil, flexShrink: 0 }} />
            {b.pane?.label}
          </div>
        ) : null,
      )}
      <div style={{ position: "absolute", left: 1, top: bar, width: W - 2, height: H - 1, overflow: "hidden", borderRadius: "0 0 7px 7px" }}>
        <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H, transformOrigin: "0 0", transform: `translate(${tx}px, ${ty}px) scale(${z})` }}>
          {plan.present && plan.src ? <ClipVideo plan={plan} /> : <Placeholder label={`clip: ${plan.id}`} />}
          {split ? <div style={{ position: "absolute", left: W / 2 - 5, width: 10, top: -2, bottom: -2, background: C.ledger, borderLeft: `1px solid ${C.rule}`, borderRight: `1px solid ${C.rule}` }} /> : null}
          {children ? <div style={{ position: "absolute", inset: 0 }}>{children(s)}</div> : null}
        </div>
      </div>
    </div>
  );
};

/* ---------- callouts ---------- */

/** A circle that draws itself around a box (clip coordinates), with a short label. */
export const Callout: React.FC<{ at: number; box: Box; label?: string; s: number; dur?: number; color?: string; areaW: number; areaH: number }> = ({
  at, box, label, s, dur = sec(3.2), color = C.red, areaW, areaH,
}) => {
  const f = useCurrentFrame() - at;
  if (f < 0 || f > dur + 10) return null;
  const draw = interpolate(f, [0, sec(0.55)], [1, 0], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const o = interpolate(f, [dur, dur + 10], [1, 0], clamp);
  const pad = 18;
  const x = box[0] * s - pad, y = box[1] * s - pad, w = box[2] * s + 2 * pad, h = box[3] * s + 2 * pad;
  const lo = interpolate(f, [sec(0.35), sec(0.6)], [0, 1], clamp);
  // label above the ellipse when there is room, else below; kept inside the clip area
  const labelH = 52;
  const big = h > areaH * 0.45;
  const above = !big && y - labelH - 8 > 0;
  // big areas: label to the left of the frame when there is room, so it does not cover the text inside
  const bigLeft = big && x > 340;
  const ly = big ? Math.max(16, y + pad + 10) : above ? y - labelH - 6 : Math.min(y + h + 6, areaH - labelH - 4);
  const lx = bigLeft ? x - 330 : Math.max(6, Math.min(x + w / 2 - 160, areaW - 330));
  return (
    <div style={{ position: "absolute", inset: 0, opacity: o, zIndex: 20 }}>
      <svg width={areaW} height={areaH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        {h > areaH * 0.45 ? (
          // large areas (the drawer): a rectangle drawn inside the clip, an ellipse would leave the frame
          <rect x={Math.max(4, x + pad - 6)} y={Math.max(4, y + pad - 6)} width={Math.min(areaW - 8, w - 2 * pad + 12)} height={Math.min(areaH - 8 - Math.max(4, y + pad - 6), h - 2 * pad + 12)} rx={14} fill="none" stroke={color} strokeWidth={5} pathLength={1} strokeDasharray={1} strokeDashoffset={draw} />
        ) : (
          <ellipse cx={x + w / 2} cy={y + h / 2} rx={w / 2} ry={h / 2} fill="none" stroke={color} strokeWidth={5} pathLength={1} strokeDasharray={1} strokeDashoffset={draw} transform={`rotate(-2 ${x + w / 2} ${y + h / 2})`} strokeLinecap="round" />
        )}
      </svg>
      {label ? (
        <div style={{ position: "absolute", left: lx, top: ly, opacity: lo, width: 320, display: "flex", justifyContent: bigLeft ? "flex-end" : "center" }}>
          <div style={{ background: C.paper, color: C.ink, border: `2px solid ${color}`, borderRadius: 6, padding: "5px 16px 7px", fontSize: 30, fontWeight: 700, whiteSpace: "nowrap", boxShadow: `0 4px 12px ${C.shade}` }}>
            {label}
          </div>
        </div>
      ) : null}
    </div>
  );
};

/** A small ink dot that marks a click. */
export const InkDot: React.FC<{ at: number; x: number; y: number; s: number }> = ({ at, x, y, s }) => {
  const f = useCurrentFrame() - at;
  if (f < 0 || f > sec(1.6)) return null;
  const pop = interpolate(f, [0, 4, 8], [0.2, 1.25, 1], clamp);
  const o = interpolate(f, [sec(1.1), sec(1.6)], [1, 0], clamp);
  const ring = interpolate(f, [0, sec(0.6)], [10, 46], clamp);
  const ro = interpolate(f, [0, sec(0.6)], [0.8, 0], clamp);
  return (
    <div style={{ position: "absolute", left: x * s, top: y * s, zIndex: 25, opacity: o }}>
      <div style={{ position: "absolute", width: ring * 2, height: ring * 2, left: -ring, top: -ring, borderRadius: "50%", border: `3px solid ${C.ink}`, opacity: ro }} />
      <div style={{ position: "absolute", width: 22, height: 22, left: -11, top: -11, borderRadius: "50%", background: C.ink, transform: `scale(${pop})`, boxShadow: `0 0 0 3px ${C.paper}` }} />
    </div>
  );
};

/** Picture-in-picture still (PayPal page) in its own window frame. */
export const Pip: React.FC<{ at: number; info: MediaInfo | undefined; id: string; cx: number; cy: number; w: number; label: string }> = ({ at, info, id, cx, cy, w, label }) => {
  const f = useCurrentFrame() - at;
  if (f < 0) return null;
  const ar = info?.present && info.width && info.height ? info.height / info.width : 9 / 16;
  const h = Math.min(w * ar, 560);
  const ww = h / ar;
  const p = interpolate(f, [0, 10], [0, 1], { ...clamp, easing: Easing.out(Easing.back(1.4)) });
  return (
    <div style={{ position: "absolute", left: cx - ww / 2, top: cy - (h + BAR) / 2, width: ww, height: h + BAR, transform: `scale(${0.85 + 0.15 * p}) rotate(${(1 - p) * 3 + 1}deg)`, opacity: p, zIndex: 40, background: C.sheet, border: `1px solid ${C.rule}`, borderRadius: 8, boxShadow: `0 14px 30px ${C.shade}`, overflow: "hidden" }}>
      <div style={{ height: BAR, display: "flex", alignItems: "center", padding: "0 14px", gap: 10, fontSize: 21, fontWeight: 600, color: C.ink }}>
        <span style={{ width: 10, height: 10, borderRadius: 5, background: C.ink }} />
        {label}
      </div>
      <div style={{ position: "absolute", left: 0, top: BAR, width: ww, height: h }}>
        {info?.present && info.src ? <Img src={info.src} style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "top" }} /> : <Placeholder label={`still: ${id}`} />}
      </div>
    </div>
  );
};

export const fadeIn = (f: number, at: number, d = 10) => interpolate(f, [at, at + d], [0, 1], clamp);
export const slideIn = (f: number, at: number, from: number, d = 14) =>
  interpolate(f, [at, at + d], [from, 0], { ...clamp, easing: Easing.out(Easing.cubic) });
export { clamp, FPS };
