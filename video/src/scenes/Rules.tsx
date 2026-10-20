import React from "react";
import { useCurrentFrame } from "remotion";
import { Caption, ClipStage, Stamp, fadeIn, type Rect } from "../components";
import { eventsOf, planClip, type DemoProps } from "../manifest";
import { Marks, marksFor } from "../overlays";
import { C } from "../theme";
import { sec } from "../timeline";

const RECT: Rect = { x: 56, y: 236, w: 1040, h: 585 };
const LINES = [
  "Accept an invoice up to 10 % over what we agreed",
  "but never more than 150 EUR over",
  "if the extra work was ordered in writing by our staff, up to 25 % over",
];
const STARTS = [3.6, 7.6, 10.0]; // seconds, follow the voice-over
const CPS = 30; // typing speed, characters per second

export const Rules: React.FC<DemoProps & { frames: number }> = ({ manifest, media, frames }) => {
  const f = useCurrentFrame();
  const events = eventsOf(manifest, "limits");
  const plan = planClip("limits", media.limits, events, frames);
  const { marks } = marksFor("limits", events, plan);
  return (
    <>
      <ClipStage rect={RECT} plan={plan} panes={[{ label: "Frappua · Erik's Kassa · Agent limits", color: C.green }]} opacity={fadeIn(f, 0, 8)}>
        {(s) => <Marks marks={marks} s={s} areaW={RECT.w} areaH={RECT.h} />}
      </ClipStage>
      <div style={{ position: "absolute", left: 1160, top: 200, width: 700 }}>
        <div style={{ fontSize: 30, fontWeight: 700, color: C.pencil, letterSpacing: "0.12em", textTransform: "uppercase", opacity: fadeIn(f, sec(2.6)) }}>Three sentences</div>
        {LINES.map((line, i) => {
          const start = sec(STARTS[i]);
          const n = Math.max(0, Math.min(line.length, Math.floor(((f - start) / 30) * CPS)));
          const typing = n > 0 && n < line.length;
          return (
            <div key={i} style={{ display: "flex", gap: 22, marginTop: 34, opacity: f >= start - 4 ? 1 : 0 }}>
              <div style={{ fontSize: 40, fontWeight: 800, color: C.green, width: 34, flexShrink: 0 }}>{i + 1}</div>
              <div style={{ fontSize: 42, lineHeight: 1.25, fontWeight: 500, color: C.ink, borderLeft: `3px solid ${C.rule}`, paddingLeft: 20, minHeight: 52 }}>
                {line.slice(0, n)}
                <span style={{ opacity: typing || (n === 0 && f >= start - 4) ? 1 : 0, color: C.green }}>|</span>
              </div>
            </div>
          );
        })}
      </div>
      <Stamp at={sec(14.7)} text="Your rules decide" color={C.green} size={84} x={1180} y={905} rotate={-3} />
      <Caption text="Your rules decide" />
    </>
  );
};
