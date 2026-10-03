// Records the demo GIF frames from the running app, driven over CDP.
//   chrome.exe --headless=new --remote-debugging-port=9223 --user-data-dir=<fresh> about:blank
//   node dev/record.mjs <cdpPort> <appUrl> <cardUrl> <outDir>
// Writes numbered PNGs plus manifest.json (delay in ms per frame) for dev/make_gif.py.
// The app must be running in _demo/ against dev/demo_ollama.py, whose reply delay is what
// the "Checking your fit..." frames sit on.
import { mkdirSync, writeFileSync } from "node:fs";

const [port, appUrl, cardUrl, outDir] = process.argv.slice(2);
if (!port || !appUrl || !cardUrl || !outDir) {
  console.error("usage: node dev/record.mjs <cdpPort> <appUrl> <cardUrl> <outDir>");
  process.exit(2);
}
mkdirSync(outDir, { recursive: true });

const W = 720, H = 880;
const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = targets.find((t) => t.type === "page");
if (!page) throw new Error("no CDP page target");

const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => {
  ws.addEventListener("open", res);
  ws.addEventListener("error", rej);
});

let nextId = 0;
const waiting = new Map();
ws.addEventListener("message", (e) => {
  const msg = JSON.parse(e.data);
  if (msg.id && waiting.has(msg.id)) {
    const { res, rej } = waiting.get(msg.id);
    waiting.delete(msg.id);
    msg.error ? rej(new Error(msg.error.message)) : res(msg.result);
  }
});
const send = (method, params = {}) =>
  new Promise((res, rej) => {
    const id = ++nextId;
    waiting.set(id, { res, rej });
    ws.send(JSON.stringify({ id, method, params }));
  });
const evaluate = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
  return r.result.value;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const frames = [];
let n = 0;
async function grab(delay) {
  const { data } = await send("Page.captureScreenshot", { format: "png" });
  const name = `f${String(++n).padStart(3, "0")}.png`;
  writeFileSync(`${outDir}/${name}`, Buffer.from(data, "base64"));
  frames.push({ file: name, delay });
}

await send("Page.enable");
await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "light" }] });
await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });

// Title card.
await send("Page.navigate", { url: cardUrl });
await sleep(900);
await grab(2200);

// The app: feed at the top, then the tracked card. The cache-buster is only here so a re-run
// picks up an edited index.html; the app's own routes ignore the query string.
await send("Page.navigate", { url: appUrl + "?r=" + Date.now() });
for (let i = 0; i < 40; i++) {
  const ready = await evaluate(
    "document.querySelectorAll('#feed .feed-item').length && document.querySelectorAll('#list .card.opp').length"
  );
  if (ready) break;
  await sleep(250);
}
await sleep(500);
await grab(1500);

// Scroll down to the card in steps, so the movement reads as a scroll and not a jump.
const cardTop = await evaluate(
  "Math.round(document.querySelector('#list .card.opp').getBoundingClientRect().top + scrollY) - 24"
);
for (let i = 1; i <= 6; i++) {
  await evaluate(`window.scrollTo(0, ${Math.round((cardTop * i) / 6)})`);
  await sleep(60);
  await grab(80);
}
await grab(700);

async function clickAct(act) {
  await evaluate(
    `document.querySelector('#list .card.opp button[data-act="${act}"]').click()`
  );
}

// Fit check: the button's own waiting text, then the three lists.
await clickAct("match");
await sleep(250);
await grab(500);
await sleep(500);
await grab(500);
await sleep(1400);
for (let i = 0; i < 2; i++) await grab(400);
const afterFit = await evaluate(
  "Math.round(document.querySelector('#list .card.opp').getBoundingClientRect().bottom)"
);
for (let i = 1; i <= 5; i++) {
  await evaluate(`window.scrollBy(0, ${Math.round((300 * i) / 5)})`);
  await sleep(50);
  await grab(80);
}
await grab(900);

// Draft: same beat, then the message itself.
await evaluate("window.scrollTo(0, " + cardTop + ")");
await sleep(300);
await grab(400);
await clickAct("draft");
await sleep(250);
await grab(500);
await sleep(500);
await grab(600);
await sleep(1400);
await grab(500);
for (let i = 1; i <= 6; i++) {
  await evaluate(`window.scrollBy(0, ${Math.round((420 * i) / 6)})`);
  await sleep(50);
  await grab(80);
}
await grab(1400);

// Outro card.
await send("Page.navigate", { url: cardUrl + "?outro" });
await sleep(900);
await grab(2600);

writeFileSync(`${outDir}/manifest.json`, JSON.stringify({ width: W, height: H, frames }, null, 1));
console.log(`${frames.length} frames, page bottom was ${afterFit}px`);
ws.close();
