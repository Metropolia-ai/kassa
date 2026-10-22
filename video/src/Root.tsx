import React from "react";
import { Composition, AbsoluteFill, useCurrentFrame, interpolate, spring, useVideoConfig } from "remotion";
import "./theme";
import { KassaDemo } from "./KassaDemo";
import { loadMedia, type DemoProps } from "./manifest";
import { FPS, TOTAL_FRAMES } from "./timeline";

const Smoke: React.FC = () => {
  const frame = useCurrentFrame(); const { fps } = useVideoConfig();
  const s = spring({ frame, fps, config: { damping: 12 } });
  const op = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: "clamp" });
  return <AbsoluteFill style={{ background: "#E3EAE0", justifyContent: "center", alignItems: "center", fontFamily: "sans-serif" }}>
    <div style={{ transform: `scale(${s}) rotate(-3deg)`, opacity: op, border: "6px solid #1F6B45", color: "#1F6B45", padding: "12px 28px", fontSize: 96, fontWeight: 800, letterSpacing: 6 }}>SETTLED</div>
  </AbsoluteFill>;
};

const defaults: DemoProps = { manifest: null, media: {} };

export const Root: React.FC = () => (
  <>
    <Composition id="Smoke" component={Smoke} durationInFrames={60} fps={30} width={1920} height={1080} />
    <Composition
      id="KassaDemo"
      component={KassaDemo}
      durationInFrames={TOTAL_FRAMES}
      fps={FPS}
      width={1920}
      height={1080}
      defaultProps={defaults}
      calculateMetadata={async () => ({ props: await loadMedia(), durationInFrames: TOTAL_FRAMES })}
    />
  </>
);
