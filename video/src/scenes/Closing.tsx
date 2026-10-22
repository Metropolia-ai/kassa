import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { clamp, fadeIn, slideIn } from "../components";
import { C } from "../theme";
import { sec } from "../timeline";

// Times follow the voice-over (public/audio/closing.srt).
const T = { boxes: 0.2, arrows: 1.6, rules: 4.4, model: 5.4, paypal: 7.4, pills: 8.0, live: 9.6, links: 11.4 };

const Box: React.FC<{ at: number; x: number; y: number; w: number; h: number; color: string; children: React.ReactNode; from?: number; bg?: string }> = ({ at, x, y, w, h, color, children, from = 40, bg = C.paper }) => {
  const f = useCurrentFrame();
  return (
    <div style={{ position: "absolute", left: x, top: y, width: w, height: h, boxSizing: "border-box", opacity: fadeIn(f, at, 10), transform: `translateY(${slideIn(f, at, from)}px)`, border: `3px solid ${color}`, borderRadius: 12, background: bg, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", boxShadow: `0 10px 10px -4px ${C.shade}` }}>
      {children}
    </div>
  );
};

const Line: React.FC<{ at: number; x1: number; y1: number; x2: number; y2: number; color?: string; head?: boolean; width?: number; dash?: boolean }> = ({ at, x1, y1, x2, y2, color = C.ink, head = true, width = 4, dash }) => {
  const f = useCurrentFrame();
  const p = interpolate(f, [at, at + 14], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  if (p <= 0) return null;
  const x = x1 + (x2 - x1) * p, y = y1 + (y2 - y1) * p;
  const a = Math.atan2(y2 - y1, x2 - x1);
  const hs = 18;
  return (
    <g>
      <line x1={x1} y1={y1} x2={x} y2={y} stroke={color} strokeWidth={width} strokeDasharray={dash ? "10 10" : undefined} strokeLinecap="round" />
      {head && p > 0.9 ? (
        <polygon points={`${x},${y} ${x - hs * Math.cos(a - 0.45)},${y - hs * Math.sin(a - 0.45)} ${x - hs * Math.cos(a + 0.45)},${y - hs * Math.sin(a + 0.45)}`} fill={color} />
      ) : null}
    </g>
  );
};

export const Closing: React.FC = () => {
  const f = useCurrentFrame();
  const at = (s: number) => sec(s);
  const pills = ["Invoicing v2", "Payouts", "record payment"];
  return (
    <>
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        {/* the two bookkeepers talk */}
        <Line at={at(T.arrows)} x1={748} y1={168} x2={1172} y2={168} color={C.ink} />
        <Line at={at(T.arrows) + 8} x1={1172} y1={222} x2={748} y2={222} color={C.ink} />
        {/* both work with PayPal */}
        <Line at={at(T.paypal)} x1={440} y1={272} x2={640} y2={362} color={C.pencil} width={3} dash head={false} />
        <Line at={at(T.paypal)} x1={1480} y1={272} x2={1280} y2={362} color={C.pencil} width={3} dash head={false} />
      </svg>

      <Box at={at(T.boxes)} x={140} y={110} w={600} h={160} color={C.green}>
        <div style={{ fontSize: 52, fontWeight: 800, color: C.green, whiteSpace: "nowrap" }}>Frappua · Kassa</div>
        <div style={{ fontSize: 30, color: C.pencil, marginTop: 4 }}>buys, pays</div>
      </Box>
      <Box at={at(T.boxes) + 6} x={1180} y={110} w={600} h={160} color={C.purple}>
        <div style={{ fontSize: 52, fontWeight: 800, color: C.purple, whiteSpace: "nowrap" }}>Pixelforge Oy · Kassa</div>
        <div style={{ fontSize: 30, color: C.pencil, marginTop: 4 }}>invoices, gets paid</div>
      </Box>
      <div style={{ position: "absolute", left: 560, width: 800, top: 44, textAlign: "center", fontSize: 36, fontWeight: 700, color: C.ink, whiteSpace: "nowrap", opacity: fadeIn(f, at(T.arrows) + 10) }}>
        invoice · query · answer · agree
      </div>

      <Box at={at(T.paypal)} x={460} y={360} w={1000} h={190} color={C.ink}>
        <div style={{ fontSize: 64, fontWeight: 800, lineHeight: 1.1 }}>PayPal</div>
        <div style={{ display: "flex", gap: 18, marginTop: 16 }}>
          {pills.map((p, i) => (
            <span key={p} style={{ fontSize: 36, fontWeight: 600, padding: "6px 26px 9px", borderRadius: 999, border: `2px solid ${C.ink}`, background: C.sheet, whiteSpace: "nowrap", opacity: fadeIn(f, at(T.pills) + i * 6, 8) }}>
              {p}
            </span>
          ))}
        </div>
      </Box>

      <Box at={at(T.rules)} x={460} y={590} w={560} h={96} color={C.green} bg="#E8F1EA" from={24}>
        <div style={{ fontSize: 44, fontWeight: 800, color: C.green, whiteSpace: "nowrap" }}>Owner's rules decide</div>
      </Box>
      <Box at={at(T.model)} x={1040} y={600} w={480} h={76} color={C.pencil} from={24}>
        <div style={{ fontSize: 27, fontWeight: 600, color: C.pencil, whiteSpace: "nowrap" }}>the model only writes the words</div>
      </Box>

      <div style={{ position: "absolute", left: 100, right: 100, top: 730, textAlign: "center", fontSize: 36, lineHeight: 1.4, color: C.ink, opacity: fadeIn(f, at(T.live), 12), transform: `translateY(${slideIn(f, at(T.live), 20)}px)` }}>
        <b>Live:</b> PayPal sandbox Invoicing, Payouts, record-payment; LLM via OpenRouter.
        <br />
        <b>Seeded:</b> two months of history, the supplier's work log.
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 880, textAlign: "center", opacity: fadeIn(f, at(T.links), 12) }}>
        <span style={{ display: "inline-block", background: C.paper, border: `3px solid ${C.ink}`, borderRadius: 10, padding: "14px 40px 18px", fontSize: 44, fontWeight: 700 }}>
          github.com/Metropolia-ai/kassa · kassa-duet.vercel.app
        </span>
      </div>
    </>
  );
};
