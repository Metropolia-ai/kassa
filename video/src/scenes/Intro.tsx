import React from "react";
import { Easing, Sequence, interpolate, useCurrentFrame } from "remotion";
import { Caption, ClipStage, STD, Stamp, clamp, fadeIn, slideIn } from "../components";
import { eventsOf, planClip, type DemoProps } from "../manifest";
import { C } from "../theme";
import { sec } from "../timeline";

// Times follow the voice-over (public/audio/intro.srt).
const T = { read: 2.4, check: 4.6, chase: 6.9, pay: 10.2, chip: 13.6, kassa: 16.6, sub: 18.5 };

const Bar: React.FC<{ w: number; c?: string; h?: number }> = ({ w, c = C.rule, h = 16 }) => (
  <div style={{ width: w, height: h, background: c, borderRadius: 3 }} />
);

const Invoice: React.FC = () => (
  <div style={{ width: 640, height: 820, background: C.paper, border: `1px solid ${C.rule}`, borderRadius: 4, boxShadow: `0 18px 40px ${C.shade}`, padding: "56px 60px", boxSizing: "border-box", display: "flex", flexDirection: "column", gap: 22 }}>
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
      <div style={{ fontSize: 56, fontWeight: 800, letterSpacing: "0.08em" }}>INVOICE</div>
      <div style={{ fontSize: 26, color: C.pencil }}>No. 0418</div>
    </div>
    <div style={{ fontSize: 28, color: C.pencil }}>from a supplier, to you</div>
    <div style={{ height: 2, background: C.ink, margin: "8px 0 10px" }} />
    {[360, 300, 420, 260, 380].map((w, i) => (
      <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Bar w={w} />
        <Bar w={90} />
      </div>
    ))}
    <div style={{ height: 1, background: C.rule, margin: "10px 0" }} />
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <div style={{ fontSize: 30, fontWeight: 700 }}>Total due</div>
      <Bar w={140} c={C.ink} h={22} />
    </div>
    <div style={{ marginTop: "auto", display: "flex", gap: 14 }}>
      <Bar w={200} h={12} />
      <Bar w={120} h={12} />
    </div>
  </div>
);

export const Intro: React.FC<DemoProps & { frames: number }> = ({ manifest, media, frames }) => {
  const f = useCurrentFrame();
  const kassaAt = sec(T.kassa);
  const plan = planClip("intro", media.intro, eventsOf(manifest, "intro"), frames, kassaAt);

  // part 1: the invoice and its stamps
  const sheetX = slideIn(f, 4, 900, 22);
  const sheetRot = interpolate(f, [4, 26], [8, -2.5], { ...clamp, easing: Easing.out(Easing.cubic) });
  const out = interpolate(f, [kassaAt - 12, kassaAt + 4], [0, 1], { ...clamp, easing: Easing.in(Easing.cubic) });
  const day = Math.round(interpolate(f, [sec(T.read), sec(13.0)], [1, 14], clamp));
  const counterO = fadeIn(f, sec(T.read) - 6);

  // part 2: the clip and the wordmark
  const clipO = fadeIn(f, kassaAt - 4, 14);
  const clipScale = interpolate(f, [kassaAt - 4, kassaAt + 16], [0.94, 1], { ...clamp, easing: Easing.out(Easing.cubic) });

  return (
    <>
      {f >= kassaAt - 6 ? (
        <Sequence from={kassaAt - 6} layout="none">
          <ClipStage rect={STD} plan={plan} panes={[{ label: "Frappua · Erik's Kassa · Bills to pay", color: C.green }]} opacity={clipO} scale={clipScale} />
        </Sequence>
      ) : null}
      {f >= kassaAt - 6 ? <div style={{ position: "absolute", inset: 0, background: `rgba(227,234,224,${0.35 * clipO})` }} /> : null}

      {out < 1 ? (
        <div style={{ position: "absolute", inset: 0, opacity: 1 - out, transform: `translateY(${-out * 60}px)` }}>
          <div style={{ position: "absolute", left: 250, top: 110, transform: `translateX(${sheetX}px) rotate(${sheetRot}deg)` }}>
            <Invoice />
            <Stamp at={sec(T.read)} text="Read" color={C.ink} size={84} x={190} y={300} rotate={-8} />
            <Stamp at={sec(T.check)} text="Check" color={C.amber} size={84} x={440} y={430} rotate={5} />
            <Stamp at={sec(T.chase)} text="Chase" color={C.red} size={84} x={220} y={570} rotate={-3} />
            <div style={{ position: "absolute", left: 420, top: 500, fontSize: 84, fontWeight: 800, color: C.pencil, opacity: fadeIn(f, sec(T.chase) + 20) }}>…</div>
            <Stamp at={sec(T.pay)} text="Pay" color={C.green} size={96} x={460} y={700} rotate={-6} />
          </div>
          <div style={{ position: "absolute", left: 1080, top: 230, width: 720, opacity: counterO }}>
            <div style={{ fontSize: 36, color: C.pencil, fontWeight: 600 }}>from invoice to payment</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 24, marginTop: 4 }}>
              <span style={{ fontSize: 110, fontWeight: 800 }}>Day</span>
              <span style={{ fontSize: 200, fontWeight: 900, fontVariantNumeric: "tabular-nums", minWidth: 230, lineHeight: 1 }}>{day}</span>
            </div>
            <div style={{ marginTop: 60, opacity: fadeIn(f, sec(T.chip)), transform: `translateY(${slideIn(f, sec(T.chip), 30)}px)` }}>
              <div style={{ display: "inline-block", background: C.paper, border: `3px solid ${C.ink}`, borderRadius: 999, padding: "12px 38px 16px", fontSize: 72, fontWeight: 800, whiteSpace: "nowrap" }}>$10–13 per invoice</div>
              <div style={{ fontSize: 26, color: C.pencil, marginTop: 16, marginLeft: 12 }}>Ardent Partners benchmarks, as cited</div>
            </div>
          </div>
        </div>
      ) : null}

      <Stamp at={kassaAt} text="Kassa" color={C.ink} size={190} x={960} y={470} rotate={-3} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 640, textAlign: "center", opacity: fadeIn(f, sec(T.sub)), zIndex: 31 }}>
        <span style={{ background: C.paper, padding: "10px 30px 14px", borderRadius: 8, fontSize: 52, fontWeight: 700, boxShadow: `0 6px 18px ${C.shade}` }}>It does that job, on PayPal.</span>
      </div>
      <Caption text="The job nobody has time for" from={10} />
    </>
  );
};
