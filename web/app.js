"use strict";

// ---------------------------------------------------------------- formatting

const GB = 1024 ** 3, MB = 1024 ** 2;

function size(b) {
  if (b === null || b === undefined) return "";
  if (b >= GB) return (b / GB).toFixed(b >= 10 * GB ? 0 : 1) + " GB";
  if (b >= MB) return (b / MB).toFixed(0) + " MB";
  if (b >= 1024) return (b / 1024).toFixed(0) + " KB";
  return b + " B";
}

// Age is the whole point of several of these views, so it gets a class as well
// as a label: anything unread for over two years is worth a second look.
function age(ts) {
  if (!ts) return { text: "-", cls: "" };
  const days = (Date.now() / 1000 - ts) / 86400;
  let text;
  if (days < 1) return { text: "today", cls: "" };
  if (days < 45) text = Math.round(days) + "d";
  else if (days < 730) text = Math.round(days / 30.4) + "mo";
  else text = (days / 365.25).toFixed(1) + "yr";
  return { text: text, cls: days > 1825 ? "verystale" : days > 730 ? "stale" : "" };
}

function esc(s) {
  return String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function pct(a, b) { return b ? (100 * a / b).toFixed(1) + "%" : "-"; }

async function api(path) {
  const r = await fetch(path);
  const j = await r.json();
  if (j.error) throw new Error(j.error);
  return j;
}

async function apiPost(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const j = await r.json();
  if (j.error) throw new Error(j.error);
  return j;
}

function revealBtn(path) {
  return '<button class="reveal" title="show in Explorer" data-reveal="' +
    esc(path) + '">&#9656;</button>';
}

// A size cell with a proportional bar behind the number.
function barCell(bytes, max) {
  const w = max > 0 ? Math.max(0.4, 100 * bytes / max) : 0;
  return '<td class="num bar"><i style="width:' + w.toFixed(1) + '%"></i>' +
    '<u>' + size(bytes) + '</u></td>';
}

// ------------------------------------------------------------------- state

let SNAP = null;
let TAB = "folders";
let DIR_ID = null;
let SORT = "size";
const view = document.getElementById("view");

const TABS = [
  ["recommended", "Recommended"],
  ["reclaim", "Reclaim"],
  ["history", "History"],
  ["folders", "Folders"],
  ["types", "File types"],
  ["age", "Age"],
  ["biggest", "Biggest files"],
  ["video", "Video"],
  ["empty", "Empty folders"],
  ["software", "Software"],
];

function busy() { view.innerHTML = '<div class="loading">loading...</div>'; }

function fail(e) {
  view.innerHTML = '<div class="note">could not load: ' + esc(e.message) + "</div>";
}

// -------------------------------------------------------------------- header

function renderHeader() {
  const s = SNAP;
  document.getElementById("snapmeta").textContent =
    "snapshot " + s.id + " of " + s.root + ", taken " +
    new Date(s.started_at * 1000).toLocaleString() +
    " \u2014 " + s.n_files.toLocaleString() + " files, " +
    s.n_dirs.toLocaleString() + " folders" +
    (s.elevated ? "" : " \u2014 not elevated");

  const total = s.volume_total_bytes;
  const scanned = s.bytes_disk;
  const unacc = Math.max(0, s.used_bytes - scanned);
  const free = s.volume_free_bytes;
  document.getElementById("usagebar").innerHTML =
    '<span class="seg-scanned" style="width:' + (100 * scanned / total) + '%"></span>' +
    '<span class="seg-unaccounted" style="width:' + (100 * unacc / total) + '%"></span>' +
    '<span class="seg-free" style="width:' + (100 * free / total) + '%"></span>';
  document.getElementById("usagelegend").innerHTML =
    '<span><i class="swatch" style="background:var(--disk)"></i>' + size(scanned) +
      " measured</span>" +
    '<span><i class="swatch" style="background:#454b57"></i>' + size(unacc) +
      " unaccounted</span>" +
    '<span><i class="swatch" style="background:#2a3f33"></i>' + size(free) +
      " free</span>" +
    '<span>' + size(s.cloud_bytes) + " cloud-only (not on disk)</span>";

  const nav = document.getElementById("tabs");
  nav.innerHTML = TABS.map(t =>
    '<button data-tab="' + t[0] + '"' + (t[0] === TAB ? ' class="on"' : "") + ">" +
    t[1] + "</button>").join("");
}

// ------------------------------------------------------------------- folders

async function renderFolders() {
  busy();
  const d = await api("/api/dir?id=" + (DIR_ID || SNAP.root_id) + "&sort=" + SORT);
  DIR_ID = d.dir.id;

  const crumb = d.breadcrumb.map((c, i) =>
    (i ? '<span>\\</span>' : "") +
    '<a href="#" data-dir="' + c.id + '">' + esc(c.name) + "</a>").join("");

  const max = Math.max(
    ...d.subdirs.map(x => x.total_bytes_disk),
    ...d.files.map(x => x.bytes_disk), 1);

  let rows = d.subdirs.map(x => {
    const a = age(x.newest_mtime);
    let tags = "";
    if (x.total_bytes_cloud > 0)
      tags += '<span class="tag cloud">' + size(x.total_bytes_cloud) + " cloud</span>";
    if (x.regenerable) tags += '<span class="tag regen">regenerable</span>';
    if (x.total_files === 0 && x.total_dirs === 0)
      tags += '<span class="tag empty">empty</span>';
    // A reparse point we did not descend into: a junction or symlink, so its
    // contents are counted wherever the target lives, not here.
    if (x.reparse_tag && x.total_files === 0 && (x.attrs & 0x400))
      tags += '<span class="tag link">link</span>';
    return "<tr>" +
      '<td class="name">\u{1F4C1} <a href="#" data-dir="' + x.id + '">' +
        esc(x.name) + "</a>" + tags + "</td>" +
      barCell(x.total_bytes_disk, max) +
      '<td class="num">' + size(x.total_bytes_logical) + "</td>" +
      '<td class="num">' + x.total_files.toLocaleString() + "</td>" +
      '<td class="num ' + a.cls + '">' + a.text + "</td>" +
      "<td>" + revealBtn(x.path) + "</td></tr>";
  }).join("");
  // note: `a` above is built from newest_mtime, not access time

  rows += d.files.map(x => {
    const a = age(x.mtime);
    return "<tr>" +
      '<td class="name">' + esc(x.name) +
        (x.cloud_only ? '<span class="tag cloud">cloud only</span>' : "") + "</td>" +
      barCell(x.bytes_disk, max) +
      '<td class="num">' + size(x.bytes_logical) + "</td>" +
      '<td class="num"></td>' +
      '<td class="num ' + a.cls + '">' + a.text + "</td>" +
      "<td>" + revealBtn(d.dir.path + "\\" + x.name) + "</td></tr>";
  }).join("");

  view.innerHTML =
    '<div class="crumb">' + crumb + "</div>" +
    '<div class="cards">' +
      card(size(d.dir.total_bytes_disk), "on disk here") +
      card(size(d.dir.total_bytes_logical), "logical") +
      card(size(d.dir.total_bytes_cloud), "cloud-only") +
      card(d.dir.total_files.toLocaleString(), "files") +
      card(d.dir.total_dirs.toLocaleString(), "subfolders") +
    "</div>" +
    '<div class="controls"><label>sort by</label><select id="sortsel">' +
      opt("size", "size on disk") + opt("logical", "logical size") +
      opt("files", "file count") + opt("oldest", "least recently modified") +
      opt("name", "name") +
    "</select>" +
    (d.files_truncated ? '<span class="path">only the first 3000 files shown</span>' : "") +
    "</div>" +
    table(["Name", "On disk", "Logical", "Files", "Modified", ""], rows,
          "This folder is empty.");

  document.getElementById("sortsel").value = SORT;
  document.getElementById("sortsel").onchange = e => { SORT = e.target.value; renderFolders(); };
}

function card(b, label) { return '<div class="card"><b>' + b + "</b><span>" + label + "</span></div>"; }
function opt(v, t) { return '<option value="' + v + '">' + t + "</option>"; }

function table(heads, rows, emptyMsg) {
  if (!rows) return '<div class="note">' + (emptyMsg || "Nothing to show.") + "</div>";
  return "<table><thead><tr>" +
    heads.map((h, i) => '<th' + (i ? ' class="num"' : "") + ">" + h + "</th>").join("") +
    "</tr></thead><tbody>" + rows + "</tbody></table>";
}

// --------------------------------------------------------------------- types

async function renderTypes() {
  busy();
  const d = await api("/api/types");
  const max = Math.max(...d.groups.map(g => g.bytes_disk), 1);
  const total = SNAP.bytes_disk;

  const grows = d.groups.map(g => "<tr>" +
    '<td class="name"><a href="#" data-grp="' + esc(g.grp) + '">' + esc(g.grp) + "</a></td>" +
    barCell(g.bytes_disk, max) +
    '<td class="num">' + pct(g.bytes_disk, total) + "</td>" +
    '<td class="num">' + size(g.bytes_logical) + "</td>" +
    '<td class="num">' + g.n.toLocaleString() + "</td>" +
    '<td class="num">' + (g.cloud_files || 0).toLocaleString() + "</td></tr>").join("");

  const emax = Math.max(...d.exts.map(e => e.bytes_disk), 1);
  const erows = d.exts.map(e => "<tr>" +
    '<td class="name">.' + esc(e.ext) + "</td>" +
    barCell(e.bytes_disk, emax) +
    '<td class="num">' + esc(e.grp) + "</td>" +
    '<td class="num">' + size(e.bytes_logical) + "</td>" +
    '<td class="num">' + e.n.toLocaleString() + "</td></tr>").join("");

  view.innerHTML =
    '<p class="hint">Grouped by what the file is. <b>On disk</b> is what deleting it ' +
    'would actually free; <b>logical</b> counts OneDrive placeholders that occupy ' +
    'nothing locally. Where the two diverge wildly, the bytes are in the cloud, ' +
    'and removing them frees cloud quota rather than disk. Click a group to list ' +
    'its biggest files.</p>' +
    table(["Group", "On disk", "Share", "Logical", "Files", "Cloud-only"], grows) +
    '<h3 style="margin:26px 0 8px;font-size:13px">By extension, top 60</h3>' +
    table(["Extension", "On disk", "Group", "Logical", "Files"], erows);
}

// ----------------------------------------------------------------------- age

async function renderAge() {
  busy();
  const d = await api("/api/ages");
  const total = SNAP.bytes_disk;
  // Modified-time leads, because access times on this machine are not usable.
  const max = Math.max(...d.buckets.map(b => b.mtime.bytes_disk), 1);
  const rows = d.buckets.map(b => "<tr>" +
    '<td class="name">' + esc(b.label) + "</td>" +
    barCell(b.mtime.bytes_disk, max) +
    '<td class="num">' + pct(b.mtime.bytes_disk, total) + "</td>" +
    '<td class="num">' + b.mtime.n.toLocaleString() + "</td>" +
    '<td class="num dim">' + size(b.atime.bytes_disk) + "</td>" +
    '<td class="num dim">' + b.atime.n.toLocaleString() + "</td></tr>").join("");

  const h = d.atime_health;
  const days = h.top_days.map(x =>
    new Date(x.day * 1000).toLocaleDateString() + " (" + x.n.toLocaleString() + ")"
  ).join(", ");

  view.innerHTML =
    (h.trustworthy ? "" :
      '<div class="note"><b>Access times on this machine cannot be trusted, so this ' +
      'table leads with modification time.</b> Windows does record last-access ' +
      'times here, but it records reads by <i>any</i> process, and antivirus, ' +
      'search indexing and backup all sweep the whole disk. Two things give it ' +
      'away: ' + h.swept_files.toLocaleString() + ' files (' + size(h.swept_bytes) +
      ') were "read" in the last six months despite not being modified for over ' +
      'two years; and access stamps pile onto a few calendar days rather than ' +
      'spreading out \u2014 busiest days: ' + esc(days) + '. The single busiest ' +
      'accounts for ' + (100 * h.busiest_day_share).toFixed(0) + '% of all files. ' +
      'A person does not open a third of a disk in one day; a scanner does.</div>') +
    '<p class="hint">Bucketed by <b>last modified</b>, which reflects when content ' +
    'actually changed. Last-read figures are shown dimmed on the right for ' +
    'comparison only. Neither tells you whether you still <i>want</i> something ' +
    '\u2014 a film you love and rewatch yearly looks identical to one you ' +
    'abandoned.</p>' +
    table(["Last modified", "On disk", "Share", "Files",
           "Last read (unreliable)", "Files"], rows) +
    '<p class="hint" style="margin-top:14px">To act on the old end of this, go to ' +
    '<a href="#" data-tab="biggest">Biggest files</a>, set a minimum size and a ' +
    '"not touched in" filter.</p>';
}

// ------------------------------------------------------------- biggest files

let BIG = { grp: "all", min_mb: 100, years: 0, cloud: false, basis: "mtime" };

async function renderBiggest() {
  busy();
  const q = "/api/biggest?limit=400&grp=" + encodeURIComponent(BIG.grp) +
    "&min_mb=" + BIG.min_mb + "&years=" + BIG.years + "&cloud=" + (BIG.cloud ? 1 : 0) +
    "&basis=" + BIG.basis;
  const d = await api(q);
  const max = Math.max(...d.files.map(f => f.bytes_disk), 1);
  const sum = d.files.reduce((a, f) => a + f.bytes_disk, 0);

  const rows = d.files.map(f => {
    const m = age(f.mtime), a = age(f.atime);
    return "<tr>" +
      '<td class="name">' + esc(f.name) +
        (f.cloud_only ? '<span class="tag cloud">cloud only</span>' : "") +
        '<div class="path">' + esc(f.dir_path) + "</div></td>" +
      barCell(f.bytes_disk, max) +
      '<td class="num ' + m.cls + '">' + m.text + "</td>" +
      '<td class="num dim">' + a.text + "</td>" +
      '<td class="num">' + esc(f.grp || "other") + "</td>" +
      "<td>" + revealBtn(f.dir_path + "\\" + f.name) +
        '<a href="#" data-dir="' + f.dir_id + '" title="open folder">&#8599;</a></td></tr>';
  }).join("");

  view.innerHTML =
    '<div class="controls">' +
      '<label>group</label><select id="bgrp">' +
        ["all", "video", "audio", "image", "archive", "installer", "disk_image",
         "document", "code", "database", "other"].map(g => opt(g, g)).join("") +
      "</select>" +
      '<label>at least</label><select id="bmin">' +
        [10, 50, 100, 250, 500, 1000].map(m => opt(m, m + " MB")).join("") + "</select>" +
      '<label>not touched in</label><select id="byears">' +
        [[0, "any time"], [0.5, "6 months"], [1, "1 year"], [2, "2 years"],
         [5, "5 years"]].map(y => opt(y[0], y[1])).join("") + "</select>" +
      '<label>judged by</label><select id="bbasis">' +
        opt("mtime", "modified (reliable)") + opt("atime", "read (unreliable here)") +
      "</select>" +
      '<label><input type="checkbox" id="bcloud"' + (BIG.cloud ? " checked" : "") +
        "> include cloud-only</label>" +
      '<span class="path">' + d.files.length + " shown, " + size(sum) + "</span>" +
    "</div>" +
    (BIG.basis === "atime" ?
      '<div class="note">Filtering on read time on this machine mostly filters out ' +
      'files that a virus scanner happened to touch. See <a href="#" data-tab="age">' +
      'Age</a> for why.</div>' : "") +
    table(["Name and folder", "On disk", "Modified", "Read", "Group", ""], rows,
          "No files match those filters.");

  const set = (id, val, key, cast) => {
    const el = document.getElementById(id);
    el.value = val;
    el.onchange = e => { BIG[key] = cast(e.target.value); renderBiggest(); };
  };
  set("bgrp", BIG.grp, "grp", String);
  set("bmin", BIG.min_mb, "min_mb", Number);
  set("byears", BIG.years, "years", Number);
  set("bbasis", BIG.basis, "basis", String);
  document.getElementById("bcloud").onchange = e => {
    BIG.cloud = e.target.checked; renderBiggest();
  };
}

// --------------------------------------------------------------------- video

async function renderVideo() {
  busy();
  const [folders, files] = await Promise.all([
    api("/api/folders_by?grp=video&limit=40"),
    api("/api/biggest?grp=video&min_mb=700&limit=250&cloud=0"),
  ]);
  const fmax = Math.max(...folders.folders.map(f => f.bytes_disk), 1);
  const ftotal = folders.folders.reduce((a, f) => a + f.bytes_disk, 0);

  const frows = folders.folders.map(f => {
    const m = age(f.mtime);
    return "<tr>" +
      '<td class="name"><a href="#" data-dir="' + f.dir_id + '">' + esc(f.path) + "</a></td>" +
      barCell(f.bytes_disk, fmax) +
      '<td class="num">' + f.n.toLocaleString() + "</td>" +
      '<td class="num ' + m.cls + '">' + m.text + "</td>" +
      "<td>" + revealBtn(f.path) + "</td></tr>";
  }).join("");

  const vmax = Math.max(...files.files.map(f => f.bytes_disk), 1);
  const vrows = files.files.map(f => {
    const m = age(f.mtime);
    return "<tr>" +
      '<td class="name">' + esc(f.name) + '<div class="path">' + esc(f.dir_path) +
        "</div></td>" +
      barCell(f.bytes_disk, vmax) +
      '<td class="num ' + m.cls + '">' + m.text + "</td>" +
      "<td>" + revealBtn(f.dir_path + "\\" + f.name) + "</td></tr>";
  }).join("");

  view.innerHTML =
    '<div class="note">Video is the largest single category on this disk by a wide ' +
    'margin, so it gets its own screen. Only files actually on the disk are counted ' +
    'here \u2014 cloud-only video is excluded, because deleting it would not free ' +
    'local space. Personal footage and downloaded media are worth judging by ' +
    'different standards: one is irreplaceable, the other is not.</div>' +
    '<div class="cards">' + card(size(ftotal), "local video in these folders") +
      card(files.files.length.toLocaleString(), "files over 700 MB") + "</div>" +
    '<h3 style="margin:8px 0;font-size:13px">Folders holding local video</h3>' +
    table(["Folder", "On disk", "Files", "Modified", ""], frows) +
    '<h3 style="margin:26px 0 8px;font-size:13px">Individual files over 700 MB</h3>' +
    table(["Name and folder", "On disk", "Modified", ""], vrows);
}

// --------------------------------------------------------------------- empty

async function renderEmpty() {
  busy();
  const d = await api("/api/empty");
  const rows = d.dirs.map(x => "<tr>" +
    '<td class="name"><a href="#" data-dir="' + x.id + '">' + esc(x.path) + "</a></td>" +
    '<td class="num">' + x.depth + "</td>" +
    "<td>" + revealBtn(x.path) + "</td></tr>").join("");
  view.innerHTML =
    '<p class="hint">Folders containing no files and no subfolders anywhere beneath ' +
    'them, hidden files included \u2014 the scan reads every entry, so nothing is ' +
    'lurking. They free no space; this is a tidiness list. A few will be ' +
    'placeholders an application recreates on launch, so deleting those buys ' +
    'nothing permanent.</p>' +
    table(["Folder", "Depth", ""], rows, "No empty folders found.");
}

// -------------------------------------------------------------- recommended

// Candidates rendered as a `tree`-style hierarchy: sorted by name at every
// level, collapsible, with the candidate itself on the leaf. A chain of nested
// folders that each contain a single thing is merged into one "a\b\c" label -
// tree shows every level, but an eight-deep unary chain is not information.
function buildTree(items) {
  const root = { name: "", children: new Map(), item: null, leaves: 0, bytes: 0 };
  for (const c of items) {
    const parts = c.path.split("\\");
    let node = root;
    node.leaves++; node.bytes += c.bytes_disk;
    for (let i = 0; i < parts.length; i++) {
      const seg = parts[i] || "\\";
      const key = seg.toLowerCase();
      if (!node.children.has(key))
        node.children.set(key, { name: seg, children: new Map(),
                                 item: null, leaves: 0, bytes: 0 });
      node = node.children.get(key);
      node.leaves++; node.bytes += c.bytes_disk;
      if (i === parts.length - 1) node.item = c;
    }
  }
  return root;
}

function sortedKids(node) {
  return [...node.children.values()].sort(
    (a, b) => a.name.localeCompare(b.name, "en", { sensitivity: "base" }));
}

function leafRow(c, label) {
  const m = age(c.mtime);
  return '<div class="trow' + (c.decision ? " decided-" + c.decision : "") + '">' +
    '<input type="checkbox" data-mark="' + esc(c.path) + '"' +
      (c.decision === "delete" ? " checked" : "") + ">" +
    '<span class="tname">' +
      (c.dir_id ? '<a href="#" data-dir="' + c.dir_id + '">' + esc(label) + "</a>"
                : esc(label)) +
      ' <span class="treason">' + esc(c.reason) + "</span></span>" +
    '<span class="tsize">' + size(c.bytes_disk) + "</span>" +
    '<span class="tfiles">' + (c.n_files > 1 ? c.n_files.toLocaleString() : "") + "</span>" +
    '<span class="tage ' + m.cls + '">' + m.text + "</span>" +
    revealBtn(c.path) + "</div>";
}

function nodeLI(child) {
  // Collapse chains where each node has a single child and no candidate of its
  // own; the label accumulates the whole chain so depth stays meaningful.
  let label = child.name, n = child;
  while (n.children.size === 1 && !n.item) {
    n = [...n.children.values()][0];
    label += "\\" + n.name;
  }
  const kids = sortedKids(n);
  if (n.item && kids.length === 0)
    return "<li>" + leafRow(n.item, label) + "</li>";
  return '<li><details class="tdir"' + (n.leaves <= 6 ? " open" : "") + ">" +
    "<summary><span class=\"tdirname\">" + esc(label) + "</span>" +
    '<span class="tstats">' + n.leaves.toLocaleString() +
      (n.leaves === 1 ? " item" : " items") + " \u2014 " + size(n.bytes) +
    "</span></summary>" +
    (n.item ? leafRow(n.item, n.name) : "") +
    "<ul>" + kids.map(nodeLI).join("") + "</ul></details></li>";
}

function treeHTML(items) {
  const root = buildTree(items);
  return '<ul class="tree">' + sortedKids(root).map(nodeLI).join("") + "</ul>";
}

// A duplicate set is a group of paths, not one row: one <details> per set,
// a tickable row per copy. Ticking a copy marks it for deletion while the
// unticked copy stays - which is exactly the decision Phase 4 needs.
function dupMemberRow(m) {
  const a = age(m.mtime);
  return '<div class="trow' + (m.decision ? " decided-" + m.decision : "") + '">' +
    '<input type="checkbox" data-mark="' + esc(m.path) + '"' +
      (m.decision === "delete" ? " checked" : "") + ">" +
    '<span class="tname">' +
      (m.dir_id ? '<a href="#" data-dir="' + m.dir_id + '">' + esc(m.path) + "</a>"
                : esc(m.path)) +
      (m.shared ? '<span class="tag">hard link</span>' : "") +
      (m.protected ? '<span class="tag">system area - report only</span>' : "") +
    "</span>" +
    '<span class="tsize">' + size(m.bytes_disk) + "</span>" +
    '<span class="tfiles"></span>' +
    '<span class="tage ' + a.cls + '">' + a.text + "</span>" +
    revealBtn(m.path) + "</div>";
}

// Which part of the disk a path lives in, for the duplicate split. A copy
// under Windows/Program Files is the OS's business; a copy under AppData is
// best cleared via uninstall/cache passes; a copy elsewhere under the user
// profile is a personal file the user can safely judge.
function territoryOf(path) {
  const p = path.toLowerCase();
  if (p.startsWith("c:\\windows\\") || p.startsWith("c:\\program files\\") ||
      p.startsWith("c:\\program files (x86)\\") ||
      p.startsWith("c:\\programdata\\") || p.startsWith("c:\\$recycle.bin\\"))
    return "system";
  if (p.includes("\\appdata\\")) return "appdata";
  return "personal";
}

const DUP_TERRITORY_META = {
  personal: ["Personal files only",
    "Every copy lives in your own folders - the safe pool. Pick the keeper, " +
    "tick the rest."],
  appdata: ["App data only",
    "Copies inside application folders - these shrink when the app is " +
    "uninstalled or its cache cleared, not by deleting files."],
  system: ["System areas only",
    "Windows/Program Files redundancy - the OS's own copies. Report only, " +
    "nothing to do here."],
};

function dupFilesSection(dups) {
  const head = '<h3 style="margin:20px 0 6px;font-size:13px">Duplicate files';
  if (!dups || dups.computed_for == null)
    return head + "</h3>" +
      '<p class="hint" style="margin:0 0 8px">Not computed yet \u2014 run ' +
      '<code>python analyze.py --dupes</code> once. It hashes only files that ' +
      'share an exact size, keeps the result in the database, and takes a few ' +
      "minutes the first time.</p>";
  if (!dups.sets.length)
    return head + " - none</h3>" +
      '<p class="hint" style="margin:0 0 8px">No byte-identical duplicates ' +
      "at the 1 MB floor.</p>";
  const stale = dups.computed_for !== SNAP.id;
  // Hard links mean N names can point at M < N physical copies; only
  // physical copies cost disk, and one of them has to stay anyway.
  const annotated = dups.sets.map(s => {
    const phys = new Set(s.members.map(m => m.ino)).size;
    const territories = [...new Set(s.members.map(m => territoryOf(m.path)))].sort();
    return { s, phys, rec: Math.max(0, phys - 1) * s.bytes_logical,
             territory: territories.join("+") };
  }).sort((a, b) => b.rec - a.rec);
  const groups = {};
  for (const a of annotated)
    (groups[a.territory] = groups[a.territory] || []).push(a);
  const order = ["personal", "appdata", "system"];
  const rest = Object.keys(groups).filter(k => !order.includes(k)).sort();
  const subsections = order.concat(rest).filter(k => groups[k]).map(k => {
    const list = groups[k];
    const rec = list.reduce((a, x) => a + x.rec, 0);
    const meta = DUP_TERRITORY_META[k] ||
      ["Mixed: " + k.replace(/\+/g, " + "),
       "Copies span territories - deleting your copy is fine, but leave the " +
       "system/app copies alone."];
    const shown = list.slice(0, 200);
    const lis = shown.map(({ s, phys, rec }) => {
      const names = phys < s.n
        ? s.n + " names, " + phys + " physical copies \u2014 "
        : s.n + " identical copies \u2014 ";
      return '<li><details class="tdir"><summary>' +
        '<span class="tdirname">' + names + size(s.bytes_logical) +
          " each</span>" +
        '<span class="tstats">' +
          (phys > 1 ? "removing all but one frees " + size(rec)
                    : "one physical copy - nothing to reclaim") +
          " \u2014 sha256 " + esc(s.sha256) + "\u2026</span></summary>" +
        s.members.map(dupMemberRow).join("") + "</details></li>";
    }).join("");
    return '<details class="tdir"' + (k === "personal" ? " open" : "") + '><summary>' +
      '<span class="tdirname">' + meta[0] + "</span>" +
      '<span class="tstats">' + list.length.toLocaleString() + " sets, " +
        size(rec) + " reclaimable</span></summary>" +
      '<p class="hint" style="margin:4px 0 8px">' + meta[1] +
        (list.length > shown.length
          ? " Biggest " + shown.length + " of " + list.length + " shown."
          : "") + "</p>" +
      '<ul class="tree">' + lis + "</ul></details>";
  }).join("");
  return head + " - " + dups.sets.length + " proven sets</h3>" +
    (stale ? '<p class="hint" style="margin:0 0 8px">Computed against snapshot ' +
      dups.computed_for + " \u2014 re-run <code>python analyze.py --dupes</code> " +
      "to refresh.</p>" : "") +
    '<p class="hint" style="margin:0 0 8px">Every copy in a set is ' +
    "byte-identical (SHA-256). Sets are split by where the copies live - " +
    "only <b>personal</b> sets are yours to prune; tick the copies you " +
    "would remove.</p>" +
    subsections;
}

function dupTreesSection(t) {
  const head = '<h3 style="margin:20px 0 6px;font-size:13px">Duplicate folders';
  if (!t || !t.groups || !t.groups.length)
    return head + " - none</h3>" +
      '<p class="hint" style="margin:0 0 8px">No folders with identical ' +
      "names-and-sizes throughout.</p>";
  const lis = t.groups.map(g => {
    const tag = g.proven === true
      ? '<span class="tag regen">proven identical</span>'
      : '<span class="tag">' + esc(g.note || "unverified") + "</span>";
    const rows = g.members.map(m =>
      '<div class="trow"><input type="checkbox" data-mark="' + esc(m.path) + '">' +
      '<span class="tname"><a href="#" data-dir="' + m.dir_id + '">' +
        esc(m.path) + "</a>" +
        (m.protected ? '<span class="tag">system area - report only</span>' : "") +
      "</span>" +
      '<span class="tsize">' + size(m.bytes_disk) + "</span>" +
      '<span class="tfiles">' + m.n_files.toLocaleString() + "</span>" +
      '<span class="tage"></span>' + revealBtn(m.path) + "</div>").join("");
    return '<li><details class="tdir"><summary>' +
      '<span class="tdirname">' + g.n + " copies of the same folder \u2014 " +
        size(g.bytes_disk) + " each " + tag + "</span>" +
      '<span class="tstats">removing all but one frees ' +
        size(g.reclaimable) + "</span></summary>" +
      rows + "</details></li>";
  }).join("");
  return head + " - " + t.groups.length + " groups</h3>" +
    '<p class="hint" style="margin:0 0 8px">Folders whose contents match ' +
    "name-for-name and size-for-size at every level. Small ones were also " +
    "hash-proven; larger ones are labelled so.</p>" +
    '<ul class="tree">' + lis + "</ul>";
}

// Friendly names + one-line explanation per candidate kind, so the
// Recommended view can group a thousand rows into a handful of decisions.
const KIND_META = {
  recycle_bin:  ["Recycle Bin contents",
    "Already deleted once - emptying frees the space permanently."],
  regenerable:  ["Build output & package caches",
    "node_modules, build/, target/ and friends - regenerated the next time " +
    "the project builds."],
  appdata_cache: ["App caches",
    "Cache folders inside AppData - apps rebuild them on next use. The guard " +
    "refuses caches of apps that are running."],
  empty_dir:    ["Empty folders",
    "Directories with nothing inside - tidiness more than space."],
  macos_junk:   ["macOS metadata litter",
    "._* and .DS_Store files copied in from a Mac - safe to remove."],
  winupdate:    ["Windows Update staging",
    "Downloaded update payloads already installed - Disk Cleanup territory."],
  wer:          ["Windows error reports",
    "Crash-report archives Windows keeps for diagnostics."],
  vm_image:     ["Emulator / VM images",
    "Android AVDs and emulator disks - recreatable from the SDK manager, " +
    "but annoying to rebuild if you still use them."],
  stale_large:  ["Large files untouched 2+ years",
    "Big files that have not been modified in a long time - verify before " +
    "removing."],
  installer:    ["Installers & disc images",
    "Setup files already run - the installed app does not need them."],
  archive:      ["Large archives",
    "zips/ISOs sitting on disk - extract once, keep the result, drop the " +
    "rest?"],
  cloud_archive:["Cloud-only archives (OneDrive)",
    "Removing frees OneDrive quota, NOT local disk - they are not stored " +
    "here."],
  old_download: ["Old downloads",
    "Files that have sat in Downloads for over a year."],
  stale_video:  ["Large videos untouched 2+ years",
    "Watched already, or never will be?"],
};

async function renderRecommended() {
  busy();
  const [d, td] = await Promise.all([
    api("/api/candidates"), api("/api/treedups")]);
  const A = d.items.filter(c => c.tier === "A");
  const B = d.items.filter(c => c.tier === "B");
  const sum = xs => xs.reduce((a, c) => a + c.bytes_disk, 0);

  const section = (title, sub, items) => {
    if (!items.length) return "";
    const groups = {};
    for (const c of items)
      (groups[c.kind] = groups[c.kind] || []).push(c);
    const subs = Object.values(groups)
      .sort((a, b) => sum(b) - sum(a))
      .map(list => {
        const meta = KIND_META[list[0].kind] ||
          [list[0].kind, list[0].reason || ""];
        return '<details class="tdir"><summary>' +
          '<span class="tdirname">' + esc(meta[0]) + "</span>" +
          '<span class="tstats">' + list.length.toLocaleString() +
            (list.length === 1 ? " item" : " items") + ", " +
            size(sum(list)) + "</span></summary>" +
          '<p class="hint" style="margin:4px 0 8px">' + esc(meta[1]) +
            "</p>" + treeHTML(list) + "</details>";
      }).join("");
    return '<h3 style="margin:20px 0 6px;font-size:13px">' +
      title + " - " + items.length.toLocaleString() + " candidates, " +
      size(sum(items)) + "</h3>" +
      '<p class="hint" style="margin:0 0 8px">' + sub + "</p>" + subs;
  };

  view.innerHTML =
    '<div class="note">Everything the other views know about, condensed into ' +
    'groups. <b>Safe</b> means empty, regenerable, or already deleted once. ' +
    '<b>Decide</b> means real data: the tool can put the number in front of you ' +
    'but only you know if you still want it. Tick what you would remove; marks ' +
    'are saved and survive rescans. Nothing here deletes anything yet \u2014 ' +
    'that is Phase 4, and it will use this list.</div>' +
    '<div class="cards">' +
      card(size(sum(A)), "safe tier total") +
      card(size(sum(B)), "needs a decision") +
      card(A.length.toLocaleString(), "safe candidates") +
      card(B.length.toLocaleString(), "decision items") +
    "</div>" +
    '<div class="controls"><button id="copychecked">copy checked paths</button>' +
      '<button id="expandall">expand all</button>' +
      '<button id="collapseall">collapse all</button>' +
      '<span class="path" id="copied"></span></div>' +
    section("Safe to remove", "Empty, regenerable, or already in the Bin.", A) +
    section("Decide", "Big, dormant or redundant - review before anything happens.", B) +
    dupFilesSection(d.dup_sets) +
    dupTreesSection(td);

  document.getElementById("copychecked").onclick = async () => {
    const paths = [...document.querySelectorAll("input[data-mark]:checked")]
      .map(x => x.dataset.mark);
    await navigator.clipboard.writeText(paths.join("\n"));
    document.getElementById("copied").textContent =
      paths.length + " paths copied";
  };
  document.getElementById("expandall").onclick = () =>
    view.querySelectorAll("details.tdir").forEach(x => x.open = true);
  document.getElementById("collapseall").onclick = () =>
    view.querySelectorAll("details.tdir").forEach(x => x.open = false);
}

// ------------------------------------------------------------------ reclaim
//
// Phase 4. The 'delete' marks from Recommended become a batch here: each path
// is checked against the never-touch list, then moved to the Recycle Bin and
// logged to a manifest under data/manifests/. Nothing runs from this page
// loading; the only way anything moves is the button, and even that aborts the
// whole batch if any mark is refused.

let LAST_BATCH = null;

async function renderReclaim() {
  busy();
  const [d, rst] = await Promise.all([
    api("/api/reclaim"), api("/api/refresh_status")]);
  const refused = d.entries.filter(e => e.guard);

  const status = e => e.guard
    ? '<span class="tag empty">refused: ' + esc(e.guard) + "</span>"
    : e.src === "missing"
      ? '<span class="tag">not in snapshot - size unknown</span>'
      : '<span class="tag regen">will recycle</span>';

  const max = Math.max(...d.entries.map(x => x.bytes_disk), 1);
  const erows = d.entries.map(e => {
    const a = age(e.mtime);
    return "<tr>" +
      '<td class="name">' + esc(e.path) +
        (e.cloud_only ? ' <span class="tag cloud">cloud only - frees quota, not disk</span>' : "") +
        (e.bytes_cloud ? ' <span class="tag cloud">' + size(e.bytes_cloud) + " cloud inside</span>" : "") +
      "</td>" +
      barCell(e.bytes_disk, max) +
      '<td class="num">' + (e.n_files > 1 ? e.n_files.toLocaleString() : "") + "</td>" +
      '<td class="num ' + a.cls + '">' + a.text + "</td>" +
      "<td>" + status(e) + "</td>" +
      "<td>" + revealBtn(e.path) +
        ' <a href="#" data-unmark="' + esc(e.path) + '">unmark</a></td></tr>';
  }).join("");

  const mrows = d.manifests.map(m => {
    const label = m.items ? m.ok + "/" + m.items + " recycled" : "bin emptied";
    return "<tr>" +
      '<td class="name">' + esc(m.batch) + "</td>" +
      '<td class="num">' + label + "</td>" +
      '<td class="num">' + (m.freed == null ? "" : size(m.freed)) + "</td>" +
      "<td>" + (m.items
        ? '<a href="#" data-restore="' + esc(m.batch) + '">restore</a>'
        : '<span class="tag">permanent</span>') + "</td></tr>";
  }).join("");

  const last = LAST_BATCH
    ? '<h3 style="margin:20px 0 6px;font-size:13px">Last batch: ' +
      esc(LAST_BATCH.batch || "not run") + "</h3>" +
      '<p class="hint">' + (LAST_BATCH.ok
        ? "Freed " + size(LAST_BATCH.freed) + ". Manifest: " +
          esc(LAST_BATCH.manifest) + "."
        : esc(LAST_BATCH.error || "did not run")) + "</p>" +
      table(["Path", "Result"], LAST_BATCH.results
        ? LAST_BATCH.results.map(r => "<tr><td class=\"name\">" + esc(r.path) +
            "</td><td>" + (r.ok ? (LAST_BATCH.restore ? "restored" : "recycled")
                              : "FAILED: " + esc(r.error)) +
            "</td></tr>").join("")
        : "") +
      (LAST_BATCH.ok && LAST_BATCH.parents.length
        ? '<div class="controls"><button id="refreshnow">update the snapshot ' +
          "(" + LAST_BATCH.parents.length + " subtree" +
          (LAST_BATCH.parents.length > 1 ? "s" : "") + ")</button>" +
          '<span class="path">runs scan.py --refresh on ' +
          LAST_BATCH.parents.map(esc).join(", ") + "</span></div>"
        : "")
    : "";

  const refreshLine = rst.running
    ? '<div class="note">Refreshing the snapshot: ' +
      rst.done.length + " of " + (rst.done.length + rst.queue.length) +
      " done. Takes about a minute per subtree.</div>"
    : (rst.done.length
      ? '<div class="note">Refresh finished. <a href="#" id="reloadsnap">' +
        "Load the new snapshot</a> to see the freed space here.</div>"
      : "");

  view.innerHTML =
    '<div class="note">This is where marks become deletions. Paths marked ' +
    '<b>delete</b> on the Recommended tab are listed here; pressing the button ' +
    "sends them to the <b>Recycle Bin</b> and writes a manifest under " +
    "<code>data/manifests/</code> so the batch can be put back. The " +
    "never-touch list is enforced before anything moves \u2014 a batch that " +
    "contains a protected path refuses entirely.</div>" +
    '<div class="cards">' +
      card(d.entries.length.toLocaleString(), "marked for deletion") +
      card(size(d.total_disk), "would free on disk") +
      card(refused.length.toLocaleString(), "refused by the guard") +
      card(size(d.bin.bytes), "in the Recycle Bin") +
    "</div>" +
    refreshLine +
    '<h3 style="margin:8px 0;font-size:13px">Proposed batch</h3>' +
    (d.entries.length
      ? table(["Path", "On disk", "Files", "Modified", "Status", ""], erows)
      : '<p class="hint">Nothing is marked for deletion. Tick candidates on ' +
        'the <a href="#" data-tab="recommended">Recommended</a> tab first.</p>') +
    '<div class="controls">' +
      '<button id="runbatch"' + (d.can_run ? "" : " disabled") +
        ">send to the Recycle Bin</button>" +
      '<span class="path">' +
        (d.can_run
          ? d.actionable + " item" + (d.actionable === 1 ? "" : "s") +
            ", " + size(d.total_disk)
          : refused.length
            ? "blocked - unmark the refused rows first"
            : "nothing to run") +
      "</span></div>" +
    '<h3 style="margin:20px 0 6px;font-size:13px">The Recycle Bin itself</h3>' +
    '<div class="controls"><button id="emptybin"' +
      (d.bin.bytes ? "" : " disabled") + ">empty it permanently</button>" +
      '<span class="path">' + d.bin.files.toLocaleString() + " items, " +
      size(d.bin.bytes) + " \u2014 permanent, already deleted once</span></div>" +
    last +
    '<h3 style="margin:20px 0 6px;font-size:13px">Batch history</h3>' +
    (mrows
      ? table(["Batch", "Items", "Freed", ""], mrows)
      : '<p class="hint">No manifests yet.</p>');

  const rb = document.getElementById("runbatch");
  if (rb) rb.onclick = async () => {
    if (!confirm("Send " + d.actionable + " marked item(s) to the Recycle Bin?"))
      return;
    try {
      LAST_BATCH = await apiPost("/api/reclaim");
    } catch (e2) {
      LAST_BATCH = { batch: "", ok: false, error: e2.message,
                     results: null, parents: [] };
    }
    renderReclaim();
  };
  const eb = document.getElementById("emptybin");
  if (eb) eb.onclick = async () => {
    if (!confirm("Empty the Recycle Bin? This is permanent.")) return;
    await apiPost("/api/emptybin");
    renderReclaim();
  };
  const rf = document.getElementById("refreshnow");
  if (rf) rf.onclick = async () => {
    await apiPost("/api/refresh", { paths: LAST_BATCH.parents });
    // Poll until the background refresh finishes, then offer the reload.
    const poll = setInterval(async () => {
      const s = await api("/api/refresh_status");
      if (!s.running) { clearInterval(poll); renderReclaim(); }
    }, 3000);
    renderReclaim();
  };
  const rl = document.getElementById("reloadsnap");
  if (rl) rl.onclick = async () => {
    rl.textContent = "reloading...";
    await apiPost("/api/reload");
    SNAP = await api("/api/snapshot");
    DIR_ID = SNAP.root_id;
    renderHeader();
    renderReclaim();
  };
}

// ------------------------------------------------------------------ history
//
// The record of what cleanup did: which apps were uninstalled, which batches
// went to the Bin and what they freed, and how free space moved across
// snapshots. Exists so a removed app can be found again and reinstalled, and
// so progress is a line going up, not a memory.

function freeChart(tl) {
  if (!tl.length) return '<p class="hint">No snapshots yet.</p>';
  const W = 740, H = 200, L = 58, R = 16, T = 16, B = 34;
  const pts = tl.map(s =>
    [s.finished_at || s.started_at, s.volume_free_bytes / GB, s.id,
     s.refresh_path]);
  const t0 = pts[0][0], t1 = pts[pts.length - 1][0];
  let f0 = Math.min(...pts.map(p => p[1])), f1 = Math.max(...pts.map(p => p[1]));
  const pad = Math.max(2, (f1 - f0) * 0.18);
  f0 -= pad; f1 += pad;
  const X = t => L + (W - L - R) * (t1 > t0 ? (t - t0) / (t1 - t0) : 0.5);
  const Y = f => T + (H - T - B) * (1 - (f - f0) / (f1 - f0));

  let grid = "", labels = "";
  for (let i = 0; i <= 4; i++) {
    const f = f0 + (f1 - f0) * i / 4, y = Y(f).toFixed(1);
    grid += '<line x1="' + L + '" y1="' + y + '" x2="' + (W - R) + '" y2="' +
      y + '" stroke="#2b303a"/>';
    labels += '<text x="' + (L - 6) + '" y="' + (Number(y) + 4) +
      '" fill="#8b93a3" font-size="10" text-anchor="end">' +
      f.toFixed(0) + " GB</text>";
  }
  const line = pts.map(p =>
    X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1)).join(" ");
  let dots = "";
  for (const [t, f, id, rp] of pts) {
    dots += '<circle cx="' + X(t).toFixed(1) + '" cy="' + Y(f).toFixed(1) +
      '" r="3.5" fill="#5aa9e6"><title>snapshot ' + id + " \u2014 " +
      f.toFixed(1) + " GB free \u2014 " + new Date(t * 1000).toLocaleString() +
      (rp ? " \u2014 refresh of " + rp : "") + "</title></circle>" +
      '<text x="' + X(t).toFixed(1) + '" y="' + (H - 10) +
      '" fill="#8b93a3" font-size="10" text-anchor="middle">' +
      new Date(t * 1000).toLocaleDateString() + "</text>";
  }
  return '<svg width="' + W + '" height="' + H + '" role="img" ' +
    'aria-label="free space over time" style="max-width:100%">' +
    grid +
    '<polyline fill="none" stroke="#5aa9e6" stroke-width="2" points="' +
      line + '"/>' +
    dots + labels + "</svg>";
}

async function renderHistory() {
  busy();
  const d = await api("/api/history");

  const freed = d.manifests.reduce((a, m) => a + (m.freed || 0), 0);
  const tl = d.timeline;
  const freeNow = SNAP.volume_free_bytes;
  const freeStart = tl.length ? tl[0].volume_free_bytes : freeNow;
  const pending = d.apps.filter(a => !a.done_at);
  const doneBytes = d.apps.filter(a => a.done_at)
    .reduce((a, x) => a + (x.bytes || 0), 0);
  const dfree = freeNow - freeStart;
  const dfreeText = (dfree >= 0 ? "+" : "\u2212") + size(Math.abs(dfree));

  const arows = d.apps.map(a => {
    const status = a.done_at
      ? '<span class="tag regen">removed ' +
        new Date(a.done_at * 1000).toLocaleDateString() + "</span>"
      : (a.install_dir && !a.exists)
        ? '<span class="tag cloud">folder gone</span>'
        : '<span class="tag">still installed</span>';
    return "<tr>" +
      '<td class="name">' + esc(a.name) +
        (a.publisher ? '<div class="path">' + esc(a.publisher) + "</div>" : "") +
        "</td>" +
      '<td class="num">' + size(a.bytes) + "</td>" +
      '<td class="name"><div class="path">' + esc(a.install_dir || "") +
        "</div></td>" +
      '<td class="num">' +
        new Date(a.marked_at * 1000).toLocaleDateString() + "</td>" +
      "<td>" + status + "</td>" +
      "<td>" + (a.done_at ? ""
        : '<a href="#" data-udone="' + esc(a.name) + '">confirm removed</a> ') +
        '<a href="#" data-uunmark="' + esc(a.name) + '">unmark</a></td></tr>';
  }).join("");

  const mrows = d.manifests.map(m => {
    const when = m.batch.replace("batch-", "");
    const stamp = when.slice(0, 4) + "-" + when.slice(4, 6) + "-" +
      when.slice(6, 8) + " " + when.slice(9, 11) + ":" + when.slice(11, 13);
    const label = m.items ? m.ok + "/" + m.items + " recycled" : "bin emptied";
    return "<tr>" +
      '<td class="name">' + esc(m.batch) + "</td>" +
      '<td class="num">' + esc(stamp) + "</td>" +
      '<td class="num">' + label + "</td>" +
      '<td class="num">' + (m.freed == null ? "" : size(m.freed)) + "</td>" +
      "<td>" + (m.items ? '<a href="#" data-tab="reclaim">reclaim tab</a>'
                        : '<span class="tag">permanent</span>') + "</td></tr>";
  }).join("");

  view.innerHTML =
    '<div class="note">The running record of the cleanup. Uninstalls are ' +
    "tracked so a removed app can be found and reinstalled later; batches are " +
    "the file deletions logged to manifests under <code>data/manifests/</code>" +
    "; the chart is free space at each snapshot.</div>" +
    '<div class="cards">' +
      card(size(freeNow), "free now") +
      card(dfreeText, "net since first scan") +
      card(size(freed), "freed by batches") +
      card(pending.length.toLocaleString(), "apps marked to remove") +
      card(doneBytes ? size(doneBytes) : "0 B", "app footprint removed") +
    "</div>" +
    '<h3 style="margin:8px 0 6px;font-size:13px">Free space over time</h3>' +
    freeChart(tl) +
    '<h3 style="margin:20px 0 6px;font-size:13px">Uninstalls</h3>' +
    (d.apps.length
      ? table(["Application", "Size", "Install dir", "Marked", "Status", ""],
              arows)
      : '<p class="hint">No apps marked for removal yet.</p>') +
    '<p class="hint" style="margin-top:8px">Removal itself goes through ' +
    "Add/Remove Programs \u2014 press <i>confirm removed</i> once the " +
    "uninstaller has run.</p>" +
    '<h3 style="margin:20px 0 6px;font-size:13px">Batch history</h3>' +
    (mrows
      ? table(["Batch", "When", "Items", "Freed", ""], mrows)
      : '<p class="hint">No manifests yet.</p>');
}

// ------------------------------------------------------------------ software

async function renderSoftware() {
  busy();
  const d = await api("/api/software");
  const max = Math.max(...d.apps.map(a => a.real_bytes || a.est_bytes || 0), 1);
  const rows = d.apps.map(a => {
    const m = age(a.dir_mtime);
    const sz = a.real_bytes != null ? a.real_bytes : (a.est_bytes || 0);
    const loc = a.loc
      ? (a.dir_id
          ? '<a href="#" data-dir="' + a.dir_id + '">' + esc(a.loc) + "</a>"
          : esc(a.loc)) +
        (a.loc_guess ? '<span class="tag">inferred</span>' : "")
      : "";
    return "<tr>" +
      '<td class="name">' + esc(a.name) +
        (a.version ? '<span class="tag">' + esc(a.version) + "</span>" : "") +
        '<div class="path">' + esc(a.publisher) + "</div></td>" +
      barCell(sz, max) +
      '<td class="num dim">' + (a.real_bytes == null && a.est_bytes ? "registry est." : "") + "</td>" +
      '<td class="num">' + esc(a.install_date) + "</td>" +
      '<td class="num ' + m.cls + '">' + m.text + "</td>" +
      "<td>" + loc + "</td>" +
      "<td>" + (a.loc ? revealBtn(a.loc) : "") + "</td></tr>";
  }).join("");
  view.innerHTML =
    '<p class="hint">Every application registered under the Windows uninstall ' +
    "keys, sorted by footprint. <b>Size</b> is the measured on-disk size of " +
    "the install folder where it could be located; the rest show the " +
    "registry's own estimate, which is often absent or wrong. Removal goes " +
    "through Add/Remove Programs \u2014 these folders are never deleted " +
    "directly.</p>" +
    table(["Application", "Size", "", "Installed", "Content modified",
           "Install location", ""], rows,
          "No registered applications found.");
}

// -------------------------------------------------------------------- search

async function renderSearch(term) {
  busy();
  const d = await api("/api/search?q=" + encodeURIComponent(term));
  const dmax = Math.max(...d.dirs.map(x => x.total_bytes_disk), 1);
  const drows = d.dirs.map(x => {
    const a = age(x.newest_mtime);
    return "<tr>" +
      '<td class="name">\u{1F4C1} <a href="#" data-dir="' + x.id + '">' +
        esc(x.path) + "</a></td>" +
      barCell(x.total_bytes_disk, dmax) +
      '<td class="num">' + x.total_files.toLocaleString() + "</td>" +
      '<td class="num ' + a.cls + '">' + a.text + "</td>" +
      "<td>" + revealBtn(x.path) + "</td></tr>";
  }).join("");

  const fmax = Math.max(...d.files.map(x => x.bytes_disk), 1);
  const frows = d.files.map(x => {
    const a = age(x.mtime);
    return "<tr>" +
      '<td class="name">' + esc(x.name) +
        (x.cloud_only ? '<span class="tag cloud">cloud only</span>' : "") +
        '<div class="path">' + esc(x.dir_path) + "</div></td>" +
      barCell(x.bytes_disk, fmax) +
      '<td class="num ' + a.cls + '">' + a.text + "</td>" +
      "<td>" + revealBtn(x.dir_path + "\\" + x.name) + "</td></tr>";
  }).join("");

  view.innerHTML =
    '<p class="hint">Name matches for "' + esc(term) + '".</p>' +
    '<h3 style="margin:8px 0;font-size:13px">Folders</h3>' +
    table(["Folder", "On disk", "Files", "Modified", ""], drows, "No folders match.") +
    '<h3 style="margin:26px 0 8px;font-size:13px">Files</h3>' +
    table(["Name and folder", "On disk", "Modified", ""], frows, "No files match.");
}

// -------------------------------------------------------------------- routing

const RENDER = {
  recommended: renderRecommended,
  reclaim: renderReclaim,
  history: renderHistory,
  folders: renderFolders, types: renderTypes, age: renderAge,
  biggest: renderBiggest, video: renderVideo, empty: renderEmpty,
  software: renderSoftware,
};

function show(tab) {
  TAB = tab;
  renderHeader();
  RENDER[tab]().catch(fail);
}

document.addEventListener("click", e => {
  const tab = e.target.closest("[data-tab]");
  if (tab) { e.preventDefault(); show(tab.dataset.tab); return; }

  const dir = e.target.closest("[data-dir]");
  if (dir) {
    e.preventDefault();
    DIR_ID = Number(dir.dataset.dir);
    show("folders");
    return;
  }

  const grp = e.target.closest("[data-grp]");
  if (grp) {
    e.preventDefault();
    BIG = { grp: grp.dataset.grp, min_mb: 10, years: 0, cloud: false };
    show("biggest");
    return;
  }

  const rev = e.target.closest("[data-reveal]");
  if (rev) {
    e.preventDefault();
    fetch("/api/reveal?path=" + encodeURIComponent(rev.dataset.reveal))
      .then(r => r.json())
      .then(j => { if (!j.ok) alert("Could not open: " + (j.error || "unknown")); });
    return;
  }

  const un = e.target.closest("[data-unmark]");
  if (un) {
    e.preventDefault();
    apiPost("/api/decide", { path: un.dataset.unmark, choice: "unsure" })
      .then(() => renderReclaim());
    return;
  }

  const ud = e.target.closest("[data-udone]");
  if (ud) {
    e.preventDefault();
    apiPost("/api/uninstall", { action: "done", name: ud.dataset.udone })
      .then(() => renderHistory());
    return;
  }

  const uu = e.target.closest("[data-uunmark]");
  if (uu) {
    e.preventDefault();
    apiPost("/api/uninstall", { action: "unmark", name: uu.dataset.uunmark })
      .then(() => renderHistory());
    return;
  }

  const rst = e.target.closest("[data-restore]");
  if (rst) {
    e.preventDefault();
    if (!confirm("Restore batch " + rst.dataset.restore + " from the Recycle Bin?"))
      return;
    apiPost("/api/restore", { batch: rst.dataset.restore })
      .then(j => {
        LAST_BATCH = {
          batch: rst.dataset.restore + " (restore)", ok: true, restore: true,
          freed: 0, manifest: "", parents: [],
          results: j.results.map(r => ({
            path: r.path, ok: r.restored, error: r.error || "not restored",
          })),
        };
        renderReclaim();
      });
  }
});

// A tick on a Recommended row posts a decision that persists by path, so it
// survives rescans and is what Phase 4 will act on.
document.addEventListener("change", e => {
  const mark = e.target.closest("input[data-mark]");
  if (!mark) return;
  const choice = mark.checked ? "delete" : "unsure";
  fetch("/api/decide", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: mark.dataset.mark, choice }),
  }).then(r => r.json()).then(j => {
    mark.closest("tr").className = j.ok ? "decided-" + choice : "";
  });
});

let searchTimer = null;
document.getElementById("search").addEventListener("input", e => {
  const term = e.target.value.trim();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    if (term.length >= 2) { renderHeader(); renderSearch(term).catch(fail); }
    else if (term.length === 0) show(TAB);
  }, 250);
});

(async function init() {
  try {
    SNAP = await api("/api/snapshot");
    DIR_ID = SNAP.root_id;
    show("folders");
  } catch (e) { fail(e); }
})();
