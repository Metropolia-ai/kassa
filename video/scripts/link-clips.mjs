// Makes public/clips point at ../clips with an ABSOLUTE target. Remotion copies public/ into a temp
// bundle and keeps symlinks as they are, so a relative link would break there. Runs before render/still/studio.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const video = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const target = path.join(video, "clips");
const link = path.join(video, "public", "clips");
fs.mkdirSync(target, { recursive: true });
try { fs.rmSync(link, { recursive: false, force: true }); } catch {}
fs.symlinkSync(target, link, process.platform === "win32" ? "junction" : "dir");
console.log(`public/clips -> ${target}`);
