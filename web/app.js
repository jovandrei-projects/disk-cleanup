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
  ["folders", "Folders"],
  ["types", "File types"],
  ["age", "Age"],
  ["biggest", "Biggest files"],
  ["video", "Video"],
  ["empty", "Empty folders"],
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

async function renderRecommended() {
  busy();
  const d = await api("/api/candidates");
  const A = d.items.filter(c => c.tier === "A");
  const B = d.items.filter(c => c.tier === "B");
  const sum = xs => xs.reduce((a, c) => a + c.bytes_disk, 0);

  const section = (title, sub, items) => {
    if (!items.length) return "";
    return '<h3 style="margin:20px 0 6px;font-size:13px">' +
      title + " - " + items.length.toLocaleString() + " candidates, " +
      size(sum(items)) + "</h3>" +
      '<p class="hint" style="margin:0 0 8px">' + sub + "</p>" + treeHTML(items);
  };

  view.innerHTML =
    '<div class="note">Everything the other views know about, condensed into two ' +
    'lists. <b>Safe</b> means empty, regenerable, or already deleted once. ' +
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
    section("Decide", "Big, dormant or redundant - review before anything happens.", B);

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
  folders: renderFolders, types: renderTypes, age: renderAge,
  biggest: renderBiggest, video: renderVideo, empty: renderEmpty,
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
