import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";

export const C = {
  ledger: "#E3EAE0",
  sheet: "#F0F4EE",
  paper: "#FAFBF8",
  rule: "#C9D4C6",
  ink: "#1B2A3F",
  pencil: "#56645E",
  green: "#1F6B45",
  red: "#B42318",
  amber: "#855700",
  purple: "#5B3A8C",
  shade: "rgba(27,42,63,0.22)",
};

export const FONT = "'Schibsted Grotesk', system-ui, sans-serif";

// Locally bundled woff2 (public/fonts), so the render never depends on fonts.gstatic.com.
loadFont({
  family: "Schibsted Grotesk",
  url: staticFile("fonts/SchibstedGrotesk-latin.woff2"),
  weight: "400 900",
  unicodeRange:
    "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD",
}).catch(() => undefined);
loadFont({
  family: "Schibsted Grotesk",
  url: staticFile("fonts/SchibstedGrotesk-latin-ext.woff2"),
  weight: "400 900",
  unicodeRange:
    "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF",
}).catch(() => undefined);
