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

// Where an item sits in the pipeline: nothing -> marked -> (batch) -> bin ->
// emptied. The row itself only knows its decision; recycled state lives in the
// manifests, surfaced through the progress table in the sidebar.
function stageTag(decision) {
  if (decision === "delete")  return '<span class="tag st-marked">marked</span>';
  if (decision === "keep")    return '<span class="tag st-keep">keep</span>';
  if (decision === "unsure")  return '<span class="tag st-unsure">unsure</span>';
  return "";
}

// A row's tick stages a mark; nothing is committed until the bottom bar's
// apply. Rows the reclaim guard would refuse anyway get no box - a 'delete'
// mark on a protected path aborts a whole batch, so it must not be tickable.
function markBox(path, blocked) {
  if (blocked)
    return '<span class="tag" title="' +
      esc(typeof blocked === "string" ? blocked : "protected system area") +
      '">can\'t be sent to the Bin</span>';
  return '<input type="checkbox" data-mark="' + esc(path) + '"' +
    (SEL && SEL.has(path) ? " checked" : "") + ">";
}

// Every collapsible group gets a box that ticks/unticks the whole group.
// Toggling is handled in the click handler, not change - the click's default
// would both flip the box and fold the group, so it is cancelled there and
// the box state is set by hand.
function grpBox() {
  return '<input type="checkbox" class="grpbox" ' +
    'title="select or clear this whole group">';
}

// A staged tick shows a marker until it is applied; a committed mark shows the
// decided-* styling instead.
function rowCls(decision, staged) {
  return (decision ? " decided-" + decision : "") +
    (staged && decision !== "delete" ? " staged" : "");
}

function leafRow(c, label) {
  const m = age(c.mtime);
  const staged = SEL && SEL.has(c.path);
  return '<div class="trow' + rowCls(c.decision, staged) + '">' +
    markBox(c.path, !c.decision && c.guard) +
    '<span class="tname">' +
      (c.dir_id ? '<a href="#" data-dir="' + c.dir_id + '">' + esc(label) + "</a>"
                : esc(label)) +
      ' <span class="treason">' + esc(c.reason) + "</span>" +
      stageTag(c.decision) + "</span>" +
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
    "<summary>" + grpBox() + "<span class=\"tdirname\">" + esc(label) + "</span>" +
    '<span class="tstats">' + n.leaves.toLocaleString() +
      (n.leaves === 1 ? " item" : " items") + " \u2014 " + size(n.bytes) +
    "</span></summary>" +
    (n.item ? leafRow(n.item, n.name) : "") +
    "<ul>" + kids.map(nodeLI).join("") + "</ul></details></li>";
}

function treeHTML(items) {
  const root = buildTree(items);
  let top = sortedKids(root);
  // Nearly every slice's paths share the drive root, and a lone "C:" node is
  // a dead click between the group and the rows - skip it.
  if (top.length === 1 && !top[0].item && /^[A-Za-z]:$/.test(top[0].name))
    top = sortedKids(top[0]);
  return '<ul class="tree">' + top.map(nodeLI).join("") + "</ul>";
}

// A duplicate set is a group of paths, not one row: one <details> per set,
// a tickable row per copy. Ticking a copy marks it for deletion while the
// unticked copy stays - which is exactly the decision Phase 4 needs.
function dupMemberRow(m) {
  const a = age(m.mtime);
  return '<div class="trow' + rowCls(m.decision, SEL && SEL.has(m.path)) + '">' +
    markBox(m.path, m.protected && !m.decision) +
    '<span class="tname">' +
      (m.dir_id ? '<a href="#" data-dir="' + m.dir_id + '">' + esc(m.path) + "</a>"
                : esc(m.path)) +
      (m.shared ? '<span class="tag">hard link</span>' : "") +
      (m.protected ? '<span class="tag">system area - report only</span>' : "") +
      stageTag(m.decision) +
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

function dupFilesSection(dups, terrSet) {
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
  const subsections = order.concat(rest)
    .filter(k => groups[k] && (!terrSet || terrSet.has(k))).map(k => {
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
      return '<li><details class="tdir"><summary>' + grpBox() +
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
  const hidden = terrSet ? annotated.length -
      order.concat(rest).filter(k => groups[k] && terrSet.has(k))
        .reduce((a, k) => a + groups[k].length, 0) : 0;
  return head + " - " + dups.sets.length + " proven sets</h3>" +
    (stale ? '<p class="hint" style="margin:0 0 8px">Computed against snapshot ' +
      dups.computed_for + " \u2014 re-run <code>python analyze.py --dupes</code> " +
      "to refresh.</p>" : "") +
    '<p class="hint" style="margin:0 0 8px">Every copy in a set is ' +
    "byte-identical (SHA-256). Sets are split by where the copies live - " +
    "only <b>personal</b> sets are yours to prune; tick the copies you " +
    "would remove." +
    (hidden ? " " + hidden.toLocaleString() + " sets hidden by the filter." : "") +
    "</p>" + subsections;
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
      '<div class="trow' + rowCls(m.decision, SEL && SEL.has(m.path)) + '">' +
      markBox(m.path, m.protected && !m.decision) +
      '<span class="tname"><a href="#" data-dir="' + m.dir_id + '">' +
        esc(m.path) + "</a>" +
        (m.protected ? '<span class="tag">system area - report only</span>' : "") +
        stageTag(m.decision) +
      "</span>" +
      '<span class="tsize">' + size(m.bytes_disk) + "</span>" +
      '<span class="tfiles">' + m.n_files.toLocaleString() + "</span>" +
      '<span class="tage"></span>' + revealBtn(m.path) + "</div>").join("");
    return '<li><details class="tdir"><summary>' + grpBox() +
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

// Sidebar filter state. null means "everything shown"; a Set means only
// those members are shown. Persisted for the session so re-renders (e.g.
// after a mark is applied) do not lose the user's place.
let RECO = null;
let RECO_KINDS = null, RECO_STATES = null, RECO_TERR = null;

// The focused slice: which "next action" is open in the main pane, or null
// for the overview board. {t:"tier"|"kind"|"dups"|"trees", v}.
let RECO_FOCUS = null;

// Staged selection inside a focused slice. A tick never commits - the bottom
// bar applies the whole visible selection as one batch of marks. SEL holds
// every staged path so a redraw keeps the checked state; SEL_BYTES/SEL_DECID
// map the slice's paths for the bar's counts and the apply diff.
let SEL = null;
let SEL_KEY = "";
let SEL_BYTES = new Map();
let SEL_DECID = new Map();

// The pipeline a reclaimable item walks: suggested -> marked -> recycled
// (in the Bin, restorable) -> freed (bin emptied, permanent). Apps walk
// marked -> uninstalled instead.
function recoProgress(d, hist, plan) {
  const byState = {};
  for (const c of d.items) {
    const s = c.decision || "suggested";
    const g = byState[s] = byState[s] || { n: 0, bytes: 0 };
    g.n++; g.bytes += c.bytes_disk;
  }
  const freedBytes = hist.manifests
    .reduce((a, m) => a + (m.freed > 0 ? m.freed : 0), 0);
  const recycled = hist.manifests.filter(m => m.items).length;
  const appsDone = hist.apps.filter(a => a.done_at).length;
  const row = (label, n, bytes) =>
    '<tr><td>' + label + '</td><td class="num">' + n.toLocaleString() +
    '</td><td class="num">' + (bytes ? size(bytes) : "") + "</td></tr>";
  const rows = [];
  for (const s of ["suggested", "delete", "unsure", "keep"])
    if (byState[s]) rows.push(row(
      s === "delete" ? "marked" : s, byState[s].n, byState[s].bytes));
  if (plan.bin.bytes)
    rows.push(row("in Recycle Bin", plan.bin.files, plan.bin.bytes));
  if (freedBytes)
    rows.push(row("freed permanently", recycled + " batches", freedBytes));
  if (hist.apps.length)
    rows.push(row("apps uninstalled", appsDone + " / " + hist.apps.length, 0));
  return '<table class="stagetable">' + rows.join("") + "</table>";
}

function focusAttr(f) { return f ? f.t + (f.v ? ":" + f.v : "") : ""; }

// Computed "what now" - the sidebar's whole job. Pipeline steps link to the
// tab that runs them; review slices open a focused view in the main pane.
function recoActions(d, td, hist, plan) {
  const sum = xs => xs.reduce((a, c) => a + c.bytes_disk, 0);
  const acts = [];
  const actionable = plan.entries.filter(e => !e.guard);
  if (actionable.length)
    acts.push({ t: "Send marked items to the Recycle Bin",
      s: actionable.length + " marked, " + size(plan.total_disk) +
         " - reversible", focus: { t: "pipeline" } });
  if (plan.bin.bytes > 500 * 1024 * 1024)
    acts.push({ t: "Empty the Recycle Bin",
      s: size(plan.bin.bytes) + " - permanent, frees the space",
      focus: { t: "pipeline" } });
  const pendingApps = hist.apps.filter(a => !a.done_at);
  if (pendingApps.length)
    acts.push({ t: pendingApps.length + " apps still marked",
      s: size(pendingApps.reduce((a, x) => a + (x.bytes || 0), 0)) +
         " - uninstallers are Windows' job", tab: "history" });
  const A = d.items.filter(c => c.tier === "A");
  if (A.length)
    acts.push({ t: "Safe to remove", focus: { t: "tier", v: "A" },
      s: A.length.toLocaleString() + " items, " + size(sum(A)) });
  const B = d.items.filter(c => c.tier === "B");
  if (B.length)
    acts.push({ t: "Decide", focus: { t: "tier", v: "B" },
      s: B.length.toLocaleString() + " candidates, " + size(sum(B)) });
  const personalDups = d.dup_sets.sets ? d.dup_sets.sets.filter(s =>
      s.members.every(m => territoryOf(m.path) === "personal")) : [];
  if (personalDups.length) {
    const rec = personalDups.reduce((a, s) =>
      a + Math.max(0, new Set(s.members.map(m => m.ino)).size - 1) *
        s.bytes_logical, 0);
    acts.push({ t: "Pick keepers in personal duplicates",
      s: personalDups.length.toLocaleString() + " sets, ~" + size(rec) +
         " reclaimable", focus: { t: "dups", v: "personal" } });
  }
  if (td.groups && td.groups.length)
    acts.push({ t: "Duplicate folders",
      s: td.groups.length.toLocaleString() + " groups",
      focus: { t: "trees" } });
  if (!d.dup_sets.computed_for || d.dup_sets.computed_for !== SNAP.id)
    acts.push({ t: "Dup analysis is stale",
      s: "run python analyze.py --dupes against snapshot " + SNAP.id });
  if (!acts.length)
    acts.push({ t: "Nothing pending",
      s: "the pipeline is empty - rescan or review a tier" });
  const cur = focusAttr(RECO_FOCUS);
  const btns = [];
  if (RECO_FOCUS)
    btns.push('<button class="nxbtn" data-focus=""><b>&#8249; overview</b>' +
      "<span>back to the board</span></button>");
  for (const a of acts)
    btns.push('<button class="nxbtn' +
        (a.focus && focusAttr(a.focus) === cur ? " on" : "") + '"' +
        (a.tab ? ' data-tab="' + a.tab + '"' : "") +
        (a.focus ? ' data-focus="' + focusAttr(a.focus) + '"' : "") + ">" +
      "<b>" + esc(a.t) + "</b><span>" + esc(a.s) + "</span></button>");
  return btns.join("");
}

// The filter checkboxes, embedded in the focused view where they apply rather
// than living permanently in the sidebar. The delegated change handler
// rebuilds a filter Set from these full lists, so they must be reachable.
function recoFilters(d, wantStates, wantKinds, wantTerrs) {
  const sum = xs => xs.reduce((a, c) => a + c.bytes_disk, 0);
  const box = (attr, val, label, detail, set) =>
    '<label class="flt"><input type="checkbox" ' + attr + '="' + val + '"' +
      (!set || set.has(val) ? " checked" : "") +
      "><span>" + esc(label) + "</span>" +
      '<span class="fltdet">' + esc(detail || "") + "</span></label>";
  const kinds = {};
  for (const c of d.items) (kinds[c.kind] = kinds[c.kind] || []).push(c);
  const terrs = {};
  if (d.dup_sets.sets)
    for (const s of d.dup_sets.sets) {
      const t = [...new Set(s.members.map(m => territoryOf(m.path)))].sort()
        .join("+");
      terrs[t] = (terrs[t] || 0) + 1;
    }
  RECO.opts = { states: ["none", "delete", "unsure", "keep"],
                kinds: Object.keys(kinds), terrs: Object.keys(terrs) };
  const cols = [];
  if (wantStates)
    cols.push('<div class="filtcol"><div class="side-h">decision</div>' +
      [["none", "suggested"], ["delete", "marked"], ["unsure", "unsure"],
       ["keep", "keep"]]
        .map(([v, l]) => box("data-fstate", v, l, "", RECO_STATES)).join("") +
      "</div>");
  if (wantKinds)
    cols.push('<div class="filtcol"><div class="side-h">category</div>' +
      Object.entries(kinds).sort((a, b) => sum(b[1]) - sum(a[1]))
        .map(([k, list]) => box("data-fkind", k, (KIND_META[k] || [k])[0],
          list.length.toLocaleString() + " / " + size(sum(list)),
          RECO_KINDS)).join("") + "</div>");
  if (wantTerrs)
    cols.push('<div class="filtcol"><div class="side-h">dup territory</div>' +
      Object.entries(terrs).sort((a, b) => b[1] - a[1])
        .map(([t, n]) => box("data-fterr", t,
          (DUP_TERRITORY_META[t] || ["mixed: " + t])[0],
          n.toLocaleString() + " sets", RECO_TERR)).join("") + "</div>");
  return cols.join("");
}

// Toggle one filter value. null means "everything"; a smaller Set means
// only those show. Re-checking every box collapses back to null.
function recoToggle(which, val, on) {
  const all = RECO.opts[which];
  const cur = which === "states" ? RECO_STATES
            : which === "kinds" ? RECO_KINDS : RECO_TERR;
  const set = new Set(cur || all);
  if (on) set.add(val); else set.delete(val);
  const next = set.size === all.length ? null : set;
  if (which === "states") RECO_STATES = next;
  else if (which === "kinds") RECO_KINDS = next;
  else RECO_TERR = next;
  drawReco();
}

async function renderRecommended() {
  busy();
  const [d, td, hist, plan, dec, rst, bst, ebs] = await Promise.all([
    api("/api/candidates"), api("/api/treedups"),
    api("/api/history"), api("/api/reclaim"), api("/api/decisions"),
    api("/api/refresh_status"),
    // Older servers lack the status endpoints; treat them as idle.
    api("/api/reclaim_status").catch(() => ({ running: false })),
    api("/api/emptybin_status").catch(() => ({ running: false }))]);
  RECO = { d, td, hist, plan, marks: {},
           st: { refresh: rst, batch: bst, emptybin: ebs } };
  mergeMarks(dec);
  drawReco();
}

// The decisions map is keyed on path, so it covers tree-dup members too -
// the treedups API never joins them. Merge here so every slice ticks alike.
function mergeMarks(dec) {
  const marks = {};
  for (const m of dec.decisions) marks[m.path] = m.choice;
  RECO.marks = marks;
  if (RECO.td.groups)
    for (const g of RECO.td.groups)
      for (const m of g.members) m.decision = marks[m.path];
}

function drawReco() {
  const { d, td, hist, plan } = RECO;
  view.innerHTML =
    '<div class="reco">' +
    '<aside class="reco-side">' +
      '<div class="sideblock"><div class="side-h">next actions</div>' +
        recoActions(d, td, hist, plan) + "</div>" +
      '<div class="sideblock"><div class="side-h">progress</div>' +
        recoProgress(d, hist, plan) + "</div>" +
    "</aside>" +
    '<div class="reco-main' +
      (RECO_FOCUS && RECO_FOCUS.t !== "pipeline" ? " padbar" : "") + '">' +
    (RECO_FOCUS ? focusBody() : overviewBody()) +
    "</div></div>";

  const ex = document.getElementById("expandall");
  if (ex) ex.onclick = () =>
    view.querySelectorAll("details.tdir").forEach(x => x.open = true);
  const co = document.getElementById("collapseall");
  if (co) co.onclick = () =>
    view.querySelectorAll("details.tdir").forEach(x => x.open = false);
  if (RECO_FOCUS && RECO_FOCUS.t === "pipeline") wirePipeline();
  else if (RECO_FOCUS) updateSelBar();
  // Filter boxes, focus links and bar buttons are wired through the delegated
  // document listeners below (data-fstate / data-focus / data-selact), so a
  // redraw never needs to re-bind.
}

// ------------------------------------------------------------------ overview
// The board: every unit of work as one row, so "where do I start" is answered
// by the biggest unchecked line rather than a wall of nested trees.

function overviewBody() {
  const { d, td } = RECO;
  const sum = xs => xs.reduce((a, c) => a + c.bytes_disk, 0);
  const tally = items => {
    const t = {};
    for (const c of items)
      if (c.decision) t[c.decision] = (t[c.decision] || 0) + 1;
    const parts = [];
    if (t.delete) parts.push(t.delete.toLocaleString() + " marked");
    if (t.keep) parts.push(t.keep.toLocaleString() + " kept");
    if (t.unsure) parts.push(t.unsure.toLocaleString() + " unsure");
    return parts.join(" \u00b7 ");
  };
  const brow = (label, n, bytes, status, focus, sub, note) =>
    '<tr class="brow' + (sub ? " sub" : "") + '" data-focus="' + focus + '">' +
    '<td class="name">' + esc(label) +
      (note ? '<div class="path">' + esc(note) + "</div>" : "") + "</td>" +
    '<td class="num">' + n + "</td>" +
    '<td class="num">' + (bytes ? size(bytes) : "") + "</td>" +
    '<td class="num dim">' + esc(status || "") + "</td>" +
    '<td class="num">&#8594;</td></tr>';

  let rows = "";
  for (const [tier, label, note] of [
      ["A", "Safe to remove", "empty, regenerable or already deleted once"],
      ["B", "Decide", "big, dormant or redundant - review before it goes"]]) {
    const items = d.items.filter(c => c.tier === tier);
    if (!items.length) continue;
    rows += brow(label, items.length.toLocaleString(), sum(items),
                 tally(items), "tier:" + tier, false, note);
    const kinds = {};
    for (const c of items) (kinds[c.kind] = kinds[c.kind] || []).push(c);
    for (const [k, list] of Object.entries(kinds)
        .sort((a, b) => sum(b[1]) - sum(a[1])))
      // The Bin's own row goes straight to the send/empty step - recycling it
      // would just move it inside itself, which the guard refuses anyway.
      rows += brow((KIND_META[k] || [k])[0], list.length.toLocaleString(),
                   sum(list), tally(list),
                   k === "recycle_bin" ? "pipeline" : "kind:" + k, true);
  }
  if (d.dup_sets.sets && d.dup_sets.sets.length) {
    const groups = {};
    for (const s of d.dup_sets.sets) {
      const t = [...new Set(s.members.map(m => territoryOf(m.path)))].sort()
        .join("+");
      const g = groups[t] = groups[t] || { n: 0, rec: 0, marked: 0 };
      g.n++;
      g.rec += Math.max(0, new Set(s.members.map(m => m.ino)).size - 1) *
        s.bytes_logical;
      g.marked += s.members.filter(m => m.decision === "delete").length;
    }
    const all = { n: 0, rec: 0, marked: 0 };
    for (const g of Object.values(groups)) {
      all.n += g.n; all.rec += g.rec; all.marked += g.marked;
    }
    rows += brow("Duplicate files", all.n.toLocaleString() + " sets", all.rec,
      all.marked ? all.marked.toLocaleString() + " copies marked" : "", "dups",
      false, "byte-identical sets - the size is what keeping one copy frees");
    for (const [t, g] of Object.entries(groups)
        .sort((a, b) => b[1].rec - a[1].rec))
      rows += brow((DUP_TERRITORY_META[t] || ["mixed: " + t])[0],
        g.n.toLocaleString() + " sets", g.rec,
        g.marked ? g.marked.toLocaleString() + " marked" : "",
        "dups:" + t, true);
  }
  if (td.groups && td.groups.length) {
    const rec = td.groups.reduce((a, g) => a + g.reclaimable, 0);
    const mk = td.groups.reduce((a, g) =>
      a + g.members.filter(m => m.decision === "delete").length, 0);
    rows += brow("Duplicate folders",
      td.groups.length.toLocaleString() + " groups", rec,
      mk ? mk.toLocaleString() + " marked" : "", "trees", false,
      "whole folders that are copies of each other");
  }
  return '<div class="note">Everything the inventory flagged, as units of ' +
    'work. Pick a next step on the left or a row below - each opens a focused ' +
    'list where ticks are staged and applied from the bar at the bottom. ' +
    'Nothing is deleted here: marks land on the "Send to the Recycle Bin" ' +
    'step, which asks again before anything moves.</div>' +
    '<table><thead><tr><th>What needs a look</th><th class="num">items</th>' +
    '<th class="num">on disk</th><th class="num">status</th>' +
    '<th class="num"></th></tr></thead><tbody>' + rows + "</tbody></table>";
}

// -------------------------------------------------------------------- focus
// One slice fills the main pane. Ticks stage a selection; the bottom bar
// applies it as marks (and unmarks what you unticked), or marks keeps.

function kindGroups(items, flat) {
  const sum = xs => xs.reduce((a, c) => a + c.bytes_disk, 0);
  if (!items.length) return "";
  if (flat) return treeHTML(items);
  const groups = {};
  for (const c of items) (groups[c.kind] = groups[c.kind] || []).push(c);
  return Object.values(groups)
    .sort((a, b) => sum(b) - sum(a))
    .map((list, gi) => {
      const meta = KIND_META[list[0].kind] || [list[0].kind, list[0].reason || ""];
      return '<details class="tdir"' + (gi === 0 ? " open" : "") + "><summary>" +
        grpBox() +
        '<span class="tdirname">' + esc(meta[0]) + "</span>" +
        '<span class="tstats">' + list.length.toLocaleString() +
          (list.length === 1 ? " item" : " items") + ", " +
          size(sum(list)) + "</span></summary>" +
        '<p class="hint" style="margin:4px 0 8px">' + esc(meta[1]) + "</p>" +
        treeHTML(list) + "</details>";
    }).join("");
}

function focusBody() {
  const { d, td } = RECO;
  const f = RECO_FOCUS;
  const shownState = c => !RECO_STATES || RECO_STATES.has(c.decision || "none");
  const terrOf = s =>
    [...new Set(s.members.map(m => territoryOf(m.path)))].sort().join("+");
  // A row is markable when the guard does not refuse it; a refused row that
  // already carries a decision keeps its box so it can still be unmarked.
  const markable = c => !c.guard || !!c.decision;

  let title = "", sub = "", slice = [], elsewhere = [],
      wantStates = false, wantKinds = false, wantTerrs = false;
  const build = () => {
    if (f.t === "tier" || f.t === "kind") {
      const items = d.items.filter(c =>
        (f.t === "kind" ? c.kind === f.v : c.tier === f.v) &&
        shownState(c) &&
        (f.t === "kind" || !RECO_KINDS || RECO_KINDS.has(c.kind)));
      const meta = f.t === "kind" ? (KIND_META[f.v] || [f.v, ""])
        : f.v === "A"
          ? ["Safe to remove",
             "Empty, regenerable or already deleted once. Rows come " +
             "pre-ticked as a draft - the group boxes exclude what you want " +
             "kept, then apply on the bar below."]
          : ["Decide",
             "Big, dormant or redundant - the tool can put the number in " +
             "front of you but only you know if you still want it. Tick " +
             "what goes; marks are staged until you apply them."];
      title = meta[0]; sub = meta[1];
      const act = items.filter(markable);
      elsewhere = items.filter(c => !markable(c));
      slice = act.map(c => ({ p: c.path, b: c.bytes_disk, dec: c.decision,
        tier: c.tier }));
      wantStates = true; wantKinds = f.t === "tier";
      return kindGroups(act, f.t === "kind") + elsewhereSection(elsewhere);
    }
    if (f.t === "dups") {
      const terrSet = f.v ? new Set([f.v]) : RECO_TERR;
      const meta = f.v ? (DUP_TERRITORY_META[f.v] || ["Duplicates", ""])
        : ["Duplicate files",
           "Every copy in a set is byte-identical (SHA-256). Pick the keeper " +
           "in each set and tick the rest - 'all but 1st copy' drafts that " +
           "choice for you."];
      title = meta[0]; sub = meta[1];
      for (const s of d.dup_sets.sets || []) {
        if (terrSet && !terrSet.has(terrOf(s))) continue;
        for (const m of s.members)
          slice.push({ p: m.path, b: m.bytes_disk || m.bytes_logical,
            dec: m.decision, blocked: !!(m.protected && !m.decision) });
      }
      wantTerrs = !f.v;
      return dupFilesSection(d.dup_sets, terrSet);
    }
    if (f.t === "trees") {
      title = "Duplicate folders";
      sub = "Folders identical name-for-name and size-for-size at every " +
            "level. Pick the copy to keep and tick the rest.";
      for (const g of td.groups || [])
        for (const m of g.members)
          slice.push({ p: m.path, b: m.bytes_disk, dec: m.decision,
                       blocked: !!(m.protected && !m.decision) });
      return dupTreesSection(td);
    }
    if (f.t === "pipeline") {
      title = "Send to the Recycle Bin";
      sub = "The last two steps, in order. Step 1 moves every marked row to " +
            "the Bin - reversible, and each batch is logged so it can be put " +
            "back. Step 2 empties the Bin - permanent, and the only step " +
            "that actually frees the space. Afterwards the folders that " +
            "changed are rescanned and the snapshot reloads itself, so the " +
            "numbers everywhere update within about a minute. No rescan is " +
            "scheduled otherwise: a full walk stays manual (python scan.py).";
      slice = [];
      return pipelineBody();
    }
    return null;
  };

  // The slice's markable paths are known before the content is rendered,
  // because SEL decides the checked state of every box inside it. preSlice
  // ignores the display filters so staged ticks survive a narrowed view, and
  // guard-refused rows are left out - they get no box to tick.
  const preSlice = [];
  if (f.t === "tier" || f.t === "kind")
    for (const c of d.items)
      if ((f.t === "kind" ? c.kind === f.v : c.tier === f.v) && markable(c))
        preSlice.push({ p: c.path, b: c.bytes_disk, dec: c.decision,
                        tier: c.tier });
  else if (f.t === "dups") {
    const tset = f.v ? new Set([f.v]) : null;
    for (const s of d.dup_sets.sets || []) {
      if (tset && !tset.has(terrOf(s))) continue;
      for (const m of s.members)
        preSlice.push({ p: m.path, b: m.bytes_disk || m.bytes_logical,
          dec: m.decision, blocked: !!(m.protected && !m.decision) });
    }
  } else if (f.t === "trees")
    for (const g of td.groups || [])
      for (const m of g.members)
        preSlice.push({ p: m.path, b: m.bytes_disk, dec: m.decision,
                        blocked: !!(m.protected && !m.decision) });
  initSel(preSlice);
  const content = build();
  if (content === null) { RECO_FOCUS = null; return overviewBody(); }

  const totalBytes = slice.reduce((a, r) => a + r.b, 0);
  const fInner = recoFilters(d, wantStates, wantKinds, wantTerrs);
  // The pipeline is buttons, not ticks - no staged-selection bar for it.
  const hasMarks = f.t !== "pipeline";
  return '<div class="focushead">' +
      '<a href="#" data-focus="">&#8249; all recommendations</a>' +
      '<span class="focustitle">' + esc(title) + "</span>" +
      (hasMarks
        ? '<span class="tstats">' + slice.length.toLocaleString() +
          " rows \u00b7 " + size(totalBytes) + "</span>"
        : "") +
      "</div>" +
    '<p class="hint">' + esc(sub) + "</p>" +
    (fInner
      ? '<details class="filt"><summary>narrow this list</summary>' +
        '<div class="filtcols">' + fInner + "</div></details>"
      : "") +
    (hasMarks
      ? '<div class="controls"><button id="expandall">expand all</button>' +
        '<button id="collapseall">collapse all</button></div>'
      : "") +
    (content || '<p class="hint">Nothing matches those filters.</p>') +
    (hasMarks ? '<div class="selbar" id="selbar"></div>' : "");
}

// Where a guard-refused row actually gets dealt with - "handled elsewhere"
// only helped if you already knew where elsewhere was.
function elsewhereNote(c) {
  const g = c.guard || "";
  const running = g.match(/^AppData of a running app \((.+)\)$/);
  if (running)
    return "in use by " + running[1] + " - close the app and it can be marked";
  if (c.kind === "recycle_bin")
    return "already in the Bin - step 2 of 'Send to the Recycle Bin' frees it";
  if (/^c:\\\$recycle\.bin/i.test(c.path))
    return "already in the Bin - emptied from 'Send to the Recycle Bin'";
  if (c.kind === "winupdate")
    return "Windows' own tools clear this (Disk Cleanup)";
  if (c.kind === "wer")
    return "Windows error reporting manages these";
  if (g === "not on disk") return "already gone - the next rescan drops it";
  return g || "system area - this tool never touches it";
}

// Rows the batch can never act on, set apart so every row above has a real
// checkbox. They are listed for completeness - nothing here wants a manual
// delete, each row names what handles it.
function elsewhereSection(items) {
  if (!items.length) return "";
  const shown = items.slice(0, 200);
  const rows = shown.map(c => {
    const m = age(c.mtime);
    return '<div class="trow"><span class="tname" title="' + esc(c.path) + '">' +
      (c.dir_id ? '<a href="#" data-dir="' + c.dir_id + '">' + esc(c.path) + "</a>"
                : esc(c.path)) +
      ' <span class="treason">' + esc(elsewhereNote(c)) + "</span></span>" +
      '<span class="tsize">' + size(c.bytes_disk) + "</span>" +
      '<span class="tfiles">' +
        (c.n_files > 1 ? c.n_files.toLocaleString() : "") + "</span>" +
      '<span class="tage ' + m.cls + '">' + m.text + "</span>" +
      revealBtn(c.path) + "</div>";
  }).join("");
  return '<details class="tdir elsewhere"><summary>' +
    '<span class="tdirname">Handled elsewhere - can\'t be sent to the Bin</span>' +
    '<span class="tstats">' + items.length.toLocaleString() + " items \u00b7 " +
      size(items.reduce((a, c) => a + c.bytes_disk, 0)) + "</span></summary>" +
    '<p class="hint" style="margin:4px 0 8px">These sit under paths a batch ' +
    "is not allowed to touch. Nothing here asks you to delete by hand - each " +
    "row names what actually deals with it.</p>" +
    rows +
    (items.length > shown.length
      ? '<p class="hint" style="margin:4px 0 0">\u2026 and ' +
        (items.length - shown.length).toLocaleString() + " more.</p>"
      : "") +
    "</details>";
}

// SEL holds the staged selection for the current focus. It resets when the
// slice changes; a redraw of the same slice keeps it.
function initSel(slice) {
  SEL_BYTES = new Map();
  SEL_DECID = new Map();
  for (const r of slice) { SEL_BYTES.set(r.p, r.b); SEL_DECID.set(r.p, r.dec); }
  const key = focusAttr(RECO_FOCUS);
  if (SEL_KEY === key && SEL) return;
  SEL_KEY = key;
  SEL = new Set(slice.filter(r => r.dec === "delete").map(r => r.p));
  // Tier A is the one slice where "take all of it" is a sane draft: every
  // row is empty, regenerable or already deleted once. Still just staged.
  for (const r of slice)
    if (!r.dec && !r.blocked && r.tier === "A") SEL.add(r.p);
}

function syncStaged(b) {
  const row = b.closest(".trow");
  if (row)
    row.classList.toggle("staged",
      b.checked && SEL_DECID.get(b.dataset.mark) !== "delete");
}

// Rebuild the bottom bar's counts from the rendered boxes - the bar reports
// (and apply acts on) what is shown, so a narrowed filter narrows both.
function updateSelBar() {
  const bar = document.getElementById("selbar");
  if (!bar) return;
  const boxes = [...view.querySelectorAll("input[data-mark]")];
  let n = 0, bytes = 0, diff = 0, marked = 0, mbytes = 0;
  for (const b of boxes) {
    const p = b.dataset.mark, cur = SEL_DECID.get(p), sz = SEL_BYTES.get(p) || 0;
    if (cur === "delete") { marked++; mbytes += sz; }
    if (b.checked) { n++; bytes += sz; if (cur !== "delete") diff++; }
    else if (cur === "delete") diff++;
  }
  const dupSlice =
    RECO_FOCUS && (RECO_FOCUS.t === "dups" || RECO_FOCUS.t === "trees");
  bar.innerHTML =
    '<span class="selstats"><b>' + n.toLocaleString() + "</b> selected \u00b7 " +
      size(bytes) + "</span>" +
    '<button data-selact="all">select all</button>' +
    '<button data-selact="none">clear</button>' +
    (dupSlice
      ? '<button data-selact="rest" title="tick every copy but the first ' +
        'shown in each set">all but 1st copy</button>' : "") +
    '<button data-selact="copy">copy paths</button>' +
    '<span class="selflex"></span>' +
    '<button data-selact="keep"' + (n ? "" : " disabled") +
      ">mark checked as keep</button>" +
    '<button class="primary" data-selact="del"' + (diff ? "" : " disabled") +
      ">" + (diff ? "apply " + diff.toLocaleString() + " mark(s)"
                  : "marks up to date") + "</button>" +
    (marked
      ? '<a href="#" data-focus="pipeline" class="selreview">' +
        marked.toLocaleString() + " marked \u00b7 " + size(mbytes) +
        " \u2192 send to the Recycle Bin</a>" : "");
  // Group boxes mirror what their rows ended up as: all ticked, none, or
  // a mix (indeterminate).
  view.querySelectorAll("input.grpbox").forEach(g => {
    const det = g.closest("details");
    const bs = det
      ? [...det.querySelectorAll("input[data-mark]")] : [];
    const n = bs.filter(b => b.checked).length;
    g.checked = bs.length > 0 && n === bs.length;
    g.indeterminate = n > 0 && n < bs.length;
  });
}

function selAction(act) {
  const boxes = [...view.querySelectorAll("input[data-mark]")];
  if (act === "copy") {
    navigator.clipboard.writeText(
      boxes.filter(b => b.checked).map(b => b.dataset.mark).join("\n"));
    return;
  }
  if (act === "all" || act === "none") {
    const on = act === "all";
    for (const b of boxes) {
      b.checked = on;
      if (on) SEL.add(b.dataset.mark); else SEL.delete(b.dataset.mark);
      syncStaged(b);
    }
    updateSelBar();
    return;
  }
  if (act === "rest") {
    // Draft a keeper pick for duplicate slices: tick every copy but the
    // first shown in each set. Positional, not wisdom - adjust after.
    let groups;
    if (RECO_FOCUS.t === "dups") {
      const terrSet = RECO_FOCUS.v ? new Set([RECO_FOCUS.v]) : RECO_TERR;
      groups = (RECO.d.dup_sets.sets || [])
        .filter(s => !terrSet || terrSet.has(
          [...new Set(s.members.map(m => territoryOf(m.path)))].sort()
            .join("+")))
        .map(s => s.members.map(m => m.path));
    } else {
      groups = (RECO.td.groups || []).map(g => g.members.map(m => m.path));
    }
    const boxSet = new Set(boxes.map(b => b.dataset.mark));
    for (const members of groups)
      for (const p of members.filter(p => boxSet.has(p)).slice(1))
        SEL.add(p);
    for (const b of boxes) {
      b.checked = SEL.has(b.dataset.mark);
      syncStaged(b);
    }
    updateSelBar();
    return;
  }
  if (act === "del") applyMarks("delete");
  if (act === "keep") applyMarks("keep");
}

// Commit the visible selection as one batch: checked rows become 'delete'
// (or 'keep'), and a ticked-off row that was marked is unmarked to 'unsure'.
// Rows hidden by the filter are not touched.
async function applyMarks(choice) {
  const boxes = [...view.querySelectorAll("input[data-mark]")];
  const pairs = [];
  for (const b of boxes) {
    const p = b.dataset.mark, cur = SEL_DECID.get(p);
    if (choice === "delete") {
      if (b.checked && cur !== "delete") pairs.push([p, "delete"]);
      else if (!b.checked && cur === "delete") pairs.push([p, "unsure"]);
    } else if (b.checked && cur !== "keep") {
      pairs.push([p, "keep"]);
    }
  }
  if (!pairs.length) return;
  try {
    await apiPost("/api/decide", { decisions: pairs });
    const [d, plan, dec] = await Promise.all([
      api("/api/candidates"), api("/api/reclaim"), api("/api/decisions")]);
    RECO.d = d;
    RECO.plan = plan;
    mergeMarks(dec);
    drawReco();
  } catch (e2) {
    alert("marks not saved: " + e2.message);
  }
}

// ------------------------------------------------------------------ pipeline
//
// The last step of Recommended, where 'delete' marks become deletions: each
// path is checked against the never-touch list, then moved to the Recycle
// Bin and logged to a manifest under data/manifests/. Nothing runs from this
// view loading; the only way anything moves is a button, and a batch that
// contains a protected path aborts entirely. After anything moves, the
// server rescans the affected folders and reloads the snapshot on its own -
// the numbers here (and in the header) update without a manual rescan.

let LAST_BATCH = null;

// One line describing what the background workers are doing right now.
// Shown in-place by the poller; the slice only re-renders when a run ends.
function pipeStatusText() {
  const st = (RECO && RECO.st) || {};
  const b = st.batch || {}, r = st.refresh || {}, e = st.emptybin || {};
  if (b.running)
    return "Sending marked items to the Bin - a large batch can take " +
      "minutes. The page stays usable.";
  if (e.running)
    return "Emptying the Recycle Bin - a large bin can take a minute or " +
      "more. The page stays usable.";
  if (r.running)
    return "Rescanning the folders that changed: " + r.done.length + " of " +
      (r.done.length + (r.queue || []).length) +
      " done - about a minute each.";
  if (r.reloading) return "Loading the new snapshot...";
  if (b.error) return "Batch failed: " + b.error;
  if (e.error) return "Emptying failed: " + e.error;
  if (r.error) return "Rescan failed: " + r.error;
  if (r.reloaded) return "Snapshot updated - the numbers shown are current.";
  return "";
}

// While a batch, empty or rescan is running, poll its status dict and keep
// the status line current. When everything settles, pull the (already
// server-side reloaded) snapshot and rebuild the slice so every number
// reflects what just happened.
let PIPE_POLL = null;
function ensurePipePoll() {
  if (PIPE_POLL) return;
  PIPE_POLL = setInterval(async () => {
    if (!RECO || TAB !== "recommended" ||
        !RECO_FOCUS || RECO_FOCUS.t !== "pipeline") {
      clearInterval(PIPE_POLL); PIPE_POLL = null; return;
    }
    let b, r, e;
    try {
      [b, r, e] = await Promise.all([
        api("/api/reclaim_status"), api("/api/refresh_status"),
        api("/api/emptybin_status")]);
    } catch (e2) { return; }  // a dropped poll is not fatal; try next tick
    RECO.st = { batch: b, refresh: r, emptybin: e };
    const el = document.getElementById("pipestatus");
    if (el) el.innerHTML = pipeStatusText();
    const active = b.running || e.running || r.running || r.reloading;
    if (active) return;
    clearInterval(PIPE_POLL); PIPE_POLL = null;
    if (b.result && (!LAST_BATCH || LAST_BATCH.batch !== b.result.batch))
      LAST_BATCH = b.result;
    if (b.result || e.result || r.reloaded) {
      SNAP = await api("/api/snapshot");
      renderHeader();
      await renderRecommended();
    }
  }, 2000);
}

function pipelineBody() {
  const d = RECO.plan, st = RECO.st || {};
  const bst = st.batch || {}, ebs = st.emptybin || {}, rst = st.refresh || {};
  const refused = d.entries.filter(e => e.guard);
  const anyRunning = bst.running || ebs.running || rst.running || rst.reloading;

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

  const last = LAST_BATCH
    ? '<h3 class="step">Last run: ' + esc(LAST_BATCH.batch || "not run") +
        "</h3>" +
      '<p class="hint">' + (LAST_BATCH.ok
        ? (LAST_BATCH.restore
            ? "Restored."
            : "Recycled - volume free delta " + size(LAST_BATCH.freed) +
              " (near zero is expected: the bytes sit in the Bin until " +
              "step 2).") +
          " Manifest: " + esc(LAST_BATCH.manifest || "") + "."
        : esc(LAST_BATCH.error || "did not run")) + "</p>" +
      table(["Path", "Result"], LAST_BATCH.results
        ? LAST_BATCH.results.map(r => "<tr><td class=\"name\">" + esc(r.path) +
            "</td><td>" + (r.ok ? (LAST_BATCH.restore ? "restored" : "recycled")
                              : "FAILED: " + esc(r.error)) +
            "</td></tr>").join("")
        : "")
    : "";

  return '<div class="cards">' +
      card(d.entries.length.toLocaleString(), "marked for the Bin") +
      card(size(d.total_disk), "would free on disk") +
      card(refused.length.toLocaleString(), "refused by the guard") +
      card(size(d.bin.bytes), "in the Recycle Bin") +
    "</div>" +
    '<div class="note" id="pipestatus">' + pipeStatusText() + "</div>" +
    '<h3 class="step">1 &middot; Send the marked rows to the Bin</h3>' +
    (d.entries.length
      ? table(["Path", "On disk", "Files", "Modified", "Status", ""], erows)
      : '<p class="hint">Nothing is marked yet - tick rows in any ' +
        '<a href="#" data-focus="">recommendation</a> and apply them, and ' +
        "they show up here.</p>") +
    '<div class="controls">' +
      '<button id="runbatch"' +
        (d.can_run && !anyRunning ? "" : " disabled") +
        ">send to the Recycle Bin</button>" +
      '<span class="path">' +
        (d.can_run
          ? d.actionable + " item" + (d.actionable === 1 ? "" : "s") +
            ", " + size(d.total_disk) + " - reversible, logged to a manifest"
          : refused.length
            ? "blocked - unmark the refused rows first"
            : "nothing marked") +
      "</span></div>" +
    '<h3 class="step">2 &middot; Empty the Recycle Bin</h3>' +
    '<div class="controls"><button id="emptybin"' +
      (d.bin.bytes && !anyRunning ? "" : " disabled") +
      ">empty it permanently</button>" +
      '<span class="path">' + d.bin.files.toLocaleString() + " items, " +
      size(d.bin.bytes) + " at the last scan \u2014 permanent, already " +
      "deleted once. The Bin is rescanned afterwards on its own.</span></div>" +
    last +
    '<p class="hint" style="margin-top:16px">Past batches - including ' +
    'restoring one - live on the <a href="#" data-tab="history">History</a> ' +
    "tab.</p>";
}

// The buttons exist only while the pipeline slice is open; wire them after
// each drawReco and (re)start the status poller if work is in flight.
function wirePipeline() {
  const rb = document.getElementById("runbatch");
  if (rb) rb.onclick = async () => {
    if (!confirm("Send " + RECO.plan.actionable +
                 " marked item(s) to the Recycle Bin?"))
      return;
    try {
      await apiPost("/api/reclaim");
      RECO.st.batch = { running: true };
      drawReco();
      ensurePipePoll();
    } catch (e2) {
      alert("batch did not start: " + e2.message);
    }
  };
  const eb = document.getElementById("emptybin");
  if (eb) eb.onclick = async () => {
    if (!confirm("Empty the Recycle Bin? This is permanent.")) return;
    try {
      await apiPost("/api/emptybin");
      RECO.st.emptybin = { running: true };
      drawReco();
      ensurePipePoll();
    } catch (e2) {
      alert("empty did not start: " + e2.message);
    }
  };
  const st = RECO.st || {};
  const r = st.refresh || {}, b = st.batch || {}, e = st.emptybin || {};
  if (b.running || e.running || r.running || r.reloading) ensurePipePoll();
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
      "<td>" + (m.items ? '<a href="#" data-restore="' + esc(m.batch) +
                          '">restore</a>'
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

  // A "next action" or a board row opens its slice in the main pane; an empty
  // data-focus returns to the overview board.
  const fb = e.target.closest("[data-focus]");
  if (fb && RECO) {
    e.preventDefault();
    const v = fb.dataset.focus;
    RECO_FOCUS = !v ? null
      : v === "trees" ? { t: "trees" }
      : v === "dups" ? { t: "dups" }
      : { t: v.split(":")[0], v: v.split(":")[1] };
    if (TAB !== "recommended") show("recommended");
    else { window.scrollTo(0, 0); drawReco(); }
    return;
  }

  const sa = e.target.closest("[data-selact]");
  if (sa) {
    e.preventDefault();
    selAction(sa.dataset.selact);
    return;
  }

  // Group box in a collapsible summary. preventDefault stops both the box's
  // own flip and the <details> fold, so the wanted state is computed and set
  // by hand: all ticked -> clear the group, otherwise tick all of it.
  const gb = e.target.closest("input.grpbox");
  if (gb) {
    e.preventDefault();
    if (!SEL) return;
    const det = gb.closest("details");
    const boxes = det
      ? [...det.querySelectorAll("input[data-mark]")] : [];
    const on = !(boxes.length && boxes.every(b => b.checked));
    for (const b of boxes) {
      b.checked = on;
      if (on) SEL.add(b.dataset.mark); else SEL.delete(b.dataset.mark);
      syncStaged(b);
    }
    gb.checked = on;
    updateSelBar();
    return;
  }

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
      .then(() => TAB === "recommended" ? renderRecommended() : show(TAB));
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
        RECO_FOCUS = { t: "pipeline" };
        if (TAB !== "recommended") show("recommended");
        else drawReco();
      });
  }
});

// A tick on a Recommended row only stages the mark - the bottom bar's apply
// commits the whole visible selection as one batch of decisions.
document.addEventListener("change", e => {
  const mark = e.target.closest("input[data-mark]");
  if (!mark) {
    // Filter boxes inside the Recommended focus view.
    if (!RECO || TAB !== "recommended" || !RECO.opts) return;
    const box = e.target.closest(
      "input[data-fstate],input[data-fkind],input[data-fterr]");
    if (!box) return;
    const which = box.dataset.fstate !== undefined ? "states"
      : box.dataset.fkind !== undefined ? "kinds" : "terrs";
    recoToggle(which,
      box.dataset.fstate || box.dataset.fkind || box.dataset.fterr,
      box.checked);
    return;
  }
  if (!SEL) return;  // no staged slice active - nothing should have a box
  const p = mark.dataset.mark;
  if (mark.checked) SEL.add(p); else SEL.delete(p);
  syncStaged(mark);
  updateSelBar();
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
    show("recommended");
  } catch (e) { fail(e); }
})();
