// Front-end smoke test. Run against a live server:
//
//     python app.py --no-browser        (in another shell)
//     node test_render.js
//
// This exists because a mismatched quote once shipped a page that rendered
// nothing while every JSON endpoint passed its own tests. Checking the API is
// not checking the app. Here app.js is loaded and each view is actually
// rendered against the real server, and the resulting HTML is inspected.

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const BASE = process.env.BASE || "http://127.0.0.1:8770";

// ------------------------------------------------------------- DOM stand-ins

function makeEl(id) {
  return {
    id,
    innerHTML: "",
    textContent: "",
    value: "",
    onchange: null,
    dataset: {},
    addEventListener() {},
    closest() { return null; },
  };
}

const els = new Map();
global.document = {
  getElementById(id) {
    if (!els.has(id)) els.set(id, makeEl(id));
    return els.get(id);
  },
  addEventListener() {},
};
global.alert = msg => { throw new Error("unexpected alert: " + msg); };

// Capture Node's built-in fetch before shadowing the global, or the wrapper
// below ends up calling itself.
const nodeFetch = globalThis.fetch;
// app.js fetches relative paths; give them an origin.
global.fetch = url => nodeFetch(BASE + url);

// ------------------------------------------------------------------ load app

const src = fs.readFileSync(path.join(__dirname, "web", "app.js"), "utf8");
// Expose the module-scope bindings so each view can be driven individually.
const shim = src + "\n;globalThis.__app = { RENDER, renderHeader, renderSearch, " +
  "getSnap: () => SNAP, setSnap: s => { SNAP = s; }, setDir: i => { DIR_ID = i; }, " +
  "api };\n";

vm.runInThisContext(shim, { filename: "web/app.js" });

// --------------------------------------------------------------------- tests

const view = document.getElementById("view");
let failures = 0;

function check(name, cond, detail) {
  if (cond) {
    console.log("ok   " + name);
  } else {
    failures++;
    console.log("FAIL " + name + (detail ? "  -> " + detail : ""));
  }
}

function assertRendered(name, mustContain) {
  const html = view.innerHTML;
  if (/could not load/i.test(html)) {
    return check(name, false, html.slice(0, 200));
  }
  if (html.length < 200) {
    return check(name, false, "suspiciously short: " + JSON.stringify(html.slice(0, 160)));
  }
  const missing = mustContain.filter(s => !html.includes(s));
  check(name + " (" + html.length.toLocaleString() + " chars)",
        missing.length === 0, missing.length ? "missing " + JSON.stringify(missing) : "");
}

(async function main() {
  const app = globalThis.__app;

  let snap;
  try {
    snap = await app.api("/api/snapshot");
  } catch (e) {
    console.log("FAIL could not reach " + BASE + " - is app.py running?  " + e.message);
    process.exit(1);
  }
  app.setSnap(snap);
  app.setDir(snap.root_id);
  check("snapshot loaded (" + snap.n_files.toLocaleString() + " files)", snap.n_files > 0);

  app.renderHeader();
  const meta = document.getElementById("snapmeta").textContent;
  check("header shows snapshot", meta.includes("snapshot") && meta.includes("files"), meta);
  check("usage bar drawn",
        document.getElementById("usagebar").innerHTML.includes("seg-scanned"));

  const cases = [
    ["recommended", ["Safe to remove", "Decide", 'class="tree"', "data-mark=",
                     "Duplicate files", "Duplicate folders"]],
    ["reclaim", ["Proposed batch", "Recycle Bin", "never-touch",
                 "Batch history", "marked for deletion"]],
    ["folders", ["data-dir=", "on disk here", "<table"]],
    ["types", ["By extension", "<table", "video"]],
    ["age", ["Last modified", "<table", "cannot be trusted"]],
    ["biggest", ["not touched in", "<table", "judged by"]],
    ["video", ["Folders holding local video", "<table"]],
    ["empty", ["<table", "Depth"]],
    ["software", ["<table", "registry", "Install location"]],
    ["history", ["Free space over time", "Uninstalls", "<svg",
                 "Batch history", "net since first scan"]],
  ];

  for (const [tab, must] of cases) {
    view.innerHTML = "";
    try {
      await app.RENDER[tab]();
      assertRendered("view: " + tab, must);
    } catch (e) {
      check("view: " + tab, false, e.stack.split("\n").slice(0, 2).join(" | "));
    }
  }

  view.innerHTML = "";
  try {
    await app.renderSearch("modern");
    assertRendered("view: search", ["Name matches", "<table"]);
  } catch (e) {
    check("view: search", false, e.message);
  }

  // Drilling into a subfolder is the main interaction and has its own failure
  // mode: a child id that does not resolve.
  const dir = await app.api("/api/dir?id=" + snap.root_id);
  const big = dir.subdirs[0];
  app.setDir(big.id);
  view.innerHTML = "";
  await app.RENDER.folders();
  check("drill into " + big.name, view.innerHTML.includes(big.name) ||
        view.innerHTML.includes("on disk here"));

  console.log("");
  console.log(failures ? failures + " FAILURE(S)" : "all render checks passed");
  process.exit(failures ? 1 : 0);
})();
