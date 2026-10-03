// Re-shoots the article screenshots from a running app instance.
//   chrome.exe --headless=new --remote-debugging-port=9223 --user-data-dir=<fresh> about:blank
//   node dev/shoot.mjs <cdpPort> <appUrl> <outDir> <light|dark> [shots to write, e.g. 02,04]
// The CLI ignores colour-scheme flags on some hosts, so the theme is set through CDP instead.
import { writeFileSync } from "node:fs";

const [port, url, outDir, scheme] = process.argv.slice(2);
if (!port || !url || !outDir) {
  console.error("usage: node dev/shoot.mjs <cdpPort> <appUrl> <outDir> <light|dark>");
  process.exit(2);
}

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
const events = [];
ws.addEventListener("message", (e) => {
  const msg = JSON.parse(e.data);
  if (msg.id && waiting.has(msg.id)) {
    const { res, rej } = waiting.get(msg.id);
    waiting.delete(msg.id);
    msg.error ? rej(new Error(`${msg.error.message}`)) : res(msg.result);
  } else if (msg.method) {
    events.push(msg.method);
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

const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

await send("Page.enable");
await send("Emulation.setEmulatedMedia", {
  features: [{ name: "prefers-color-scheme", value: scheme || "light" }],
});

// Desktop: 1280 CSS px, one screen wide.
await send("Emulation.setDeviceMetricsOverride", {
  width: 1280, height: 900, deviceScaleFactor: 1, mobile: false,
});
await send("Page.navigate", { url });
for (let i = 0; i < 60; i++) {
  const n = await evaluate("document.querySelectorAll('#feed .feed-item').length");
  if (n > 0) break;
  await sleep(500);
}
await sleep(700);

const measure = () => evaluate(`(() => {
  const box = (el) => { const b = el.getBoundingClientRect();
    return { top: Math.round(b.top + scrollY), bottom: Math.round(b.bottom + scrollY) }; };
  return JSON.stringify({
    page: document.documentElement.scrollHeight,
    rows: [...document.querySelectorAll('#feed .feed-item')].map(box),
    more: box(document.getElementById('feedMore')),
    opps: Object.fromEntries([...document.querySelectorAll('#list .card.opp')]
      .map((c) => [c.querySelector('h3').textContent.trim(), box(c)])),
  });
})()`).then((s) => JSON.parse(s));

const shot = async (name, clip) => {
  const { data } = await send("Page.captureScreenshot", {
    format: "png", captureBeyondViewport: true, clip: { x: 0, scale: 1, ...clip },
  });
  writeFileSync(`${outDir}/${name}`, Buffer.from(data, "base64"));
  console.log(`${name}\t${clip.width}x${clip.height} @${clip.y}`);
};

const m = await measure();
const only = (process.argv[6] || "01,02,03,04,05").split(",");
const oppKeys = Object.keys(m.opps);
const find = (needle) => m.opps[oppKeys.find((k) => k.includes(needle))];
// The fit-and-draft card comes from whichever instance holds that screenshot's data.
const fitCard = process.env.FIT_CARD || "Global Hack Week";

const six = m.rows[5];
if (only.includes("01")) {
  // Cut at the divider above row 6, not at row 5's own bottom: the row's box stops before its
  // padding, so a bottom measured from the element itself clips the next title in half.
  await shot("01-feed.png", { y: 0, width: 1280, height: six.top - 12 });
}
if (only.includes("05")) {
  await shot("05-feed-sources.png", {
    y: six.top - 12, width: 1280, height: m.more.bottom + 16 - (six.top - 12),
  });
}

const loeb = find("Loeb");
const un = find("UN Global Compact");
if (only.includes("03") && loeb && un) {
  await shot("03-deadline-honesty.png", {
    y: loeb.top - 18, width: 1280, height: un.bottom + 12 - (loeb.top - 18),
  });
}

const gh = find(fitCard);
if (only.includes("02") && gh) {
  await shot("02-card-fit-draft.png", {
    y: gh.top - 17, width: 1280, height: gh.bottom + 12 - (gh.top - 17),
  });
} else if (only.includes("02")) {
  console.error(`no card matching "${fitCard}" — have: ${oppKeys.join(" / ")}`);
}

// Mobile: a real 390 CSS px viewport at 2x, so the shot is 780 px wide.
await send("Emulation.setDeviceMetricsOverride", {
  width: 390, height: 844, deviceScaleFactor: 2, mobile: true,
});
await sleep(700);
if (only.includes("04")) {
  const mm = await measure();
  const mobH = mm.rows[5] ? mm.rows[5].top - 8 : 1700;
  await shot("04-mobile-feed.png", { y: 0, width: 390, height: mobH });
  console.log(`mobile page height ${mm.page} css px, ${mm.rows.length} rows visible`);
}

ws.close();
