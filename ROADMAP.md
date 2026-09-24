# Disk cleanup - workplan

One phase at a time, in order. Mark items `[x]` as they land.

Baseline measured 2026-09-24: **C: 158.6 GB free of 952.8 GB** (794.2 GB used).
Every later phase compares against that number.

## Decisions already made

| Question | Answer |
|---|---|
| Where the tool lives | `C:\Projects\disk-cleanup` - off OneDrive, off the SD card |
| Scan scope | All of `C:\`, including Windows, Program Files, ProgramData, AppData |
| OneDrive files | Record logical size *and* on-disk size separately; **never hydrate a placeholder** |
| Viewer stack | Python stdlib `http.server` on localhost + plain HTML/JS, matching `VocalCoach/backend/web_app.py`. No new dependencies |
| Shell | Native Windows Python, not WSL. WSL reaches `C:` only through `/mnt/c`, which is far slower and cannot read OneDrive placeholder state |

## Ground rules

These hold for every phase. They exist because the failure mode here is
permanent data loss, not a wasted afternoon.

1. **Scanning and deciding are separate from deleting.** Phases 1-3 only ever
   read. Nothing is removed before Phase 4, and only from a list reviewed
   first.
2. **Deletions go to the Recycle Bin**, never permanent, and every one is
   logged with its original path and size so it can be put back.
3. **Never touch** `C:\Windows`, `C:\Program Files*`, `C:\ProgramData`,
   `$Recycle.Bin`, `System Volume Information`, `Config.Msi`, `Recovery`,
   `$SysReset`, `hiberfil.sys`, `pagefile.sys`, or any `AppData` folder of a
   running application. These are measured, listed, and reported - not edited.
   Software is removed through Add/Remove Programs, not by deleting folders.
4. **Never open or read the content of a OneDrive placeholder file.** Attribute
   reads only. Opening one downloads it and *consumes* free space.
5. **Duplicate means byte-identical, proven by hash** - not same name, not same
   size. A git repository and its copy are not duplicates of each other at the
   file level and must be handled as whole trees.
6. **The user decides what goes.** The tool's job is to rank and explain, never
   to auto-clean.

---

## Phase 0 - Groundwork

- [x] `C:\Projects` created as the local dev root, `C:\Projects\disk-cleanup` as this repo
- [x] `git init`, `.gitignore` excluding the scan database, snapshots and reports
- [x] `AGENTS.md` for this repo: the ground rules above, the machine's specifics, the never-touch list
- [x] Confirm the tool runs against `C:\Python311\python.exe` with stdlib only
- [ ] Decide whether this repo is private on GitHub or local-only (it will contain a full map of your filesystem)

## Phase 1 - Inventory scanner

One script, one pass, one database. Everything later reads from it instead of
re-walking the disk. Delivered as `scan.py`; snapshot 1 in
`data/inventory.sqlite3`.

- [x] Walk all of `C:\` with `os.scandir`, recording per entry: full path, parent, name, extension, depth, logical size, size on disk, created / modified / last-accessed times, and Windows attributes
- [x] Classify each entry as local, OneDrive-placeholder (cloud-only), or OneDrive-hydrated, using `FILE_ATTRIBUTE_RECALL_ON_*` / `OFFLINE`
- [x] Skip reparse points and junctions rather than following them, so `AppData\Local\Application Data`-style loops cannot cause infinite recursion. Cloud reparse tags are descended into; mount points and symlinks are recorded but not followed
- [x] Handle paths over 260 characters (`\\?\` prefix) and record permission denials instead of crashing on them
- [x] Write results to SQLite with the totals rolled up per directory, so the viewer never has to sum a million rows live
- [x] Store the run as a timestamped snapshot, so later scans can be diffed against this one
- [x] Sanity check: 773.9 GB on disk against the 794.3 GB Windows reports, 97.4% accounted for
- [x] Verify the rollup arithmetic, not just its plausibility: root subtree totals equal the sums over the `files` table. `--verify` asserts this and reports OK
- [x] Confirm scanning does not hydrate OneDrive placeholders - free space unchanged across a scan of `Documentos` apart from the growth of the scan database itself
- [ ] Re-run elevated to close the remaining gap. 603 of 607 errors are permission denials, 511 of them in `ProgramData\Microsoft\Windows`. Only 3 touch user data, so this is a completeness matter, not a blocker
- [ ] Measure `System Volume Information` (restore points and shadow copies), which is on the skip list and is likely most of the 20.4 GB gap. Needs `vssadmin list shadowstorage` elevated. Genuinely reclaimable, so worth knowing

### What Phase 1 found

`scan.py --verify` reprints all of this from the snapshot.

| | on disk | logical |
|---|---|---|
| All of `C:\` | **773.9 GB** | 1478.4 GB |
| Cloud-only, occupying nothing | - | 188.9 GB across 17,014 files |
| 318,781 dirs, 956,012 files | | |

**Video is 459.6 GB on disk - 59% of everything used.** No other category is
close: the next largest is 19.4 GB of disk images. This reframes the job. The
space problem is one decision about video, not a thousand small cleanups.

Biggest concentrations of local video:

| On disk | Where |
|---|---|
| 66.9 GB | `Users\andry\OneDrive\Escritorio\Hikaru no Go BDRIP 1080P [01-75Fin+SP]` |
| 58.9 GB | `Users\andry\OneDrive\Imágenes\Álbum de cámara` |
| 54.7 GB | `Users\andry\Videos\history\_has_content` |
| 48.9 GB | `C:\Videos\TorrentMovies` |
| ~130 GB | `C:\Videos\Torrent\*` - Modern Family, The Good Doctor, Rick and Morty |

Other findings worth acting on:

- **`Documentos` is 83.0 GB logical but 10.1 GB on disk**; 72.9 GB of it is
  cloud-only. Confirms trap 1 was the real risk here - a logical-size tool
  would have sent us hunting for 73 GB that was never on the disk.
- **Archives are 18.3 GB on disk but 535.4 GB logical**, so roughly 517 GB of
  archives live in OneDrive as placeholders. Deleting them frees cloud quota,
  not local space.
- **`$Recycle.Bin` holds 3.7 GB** in 44 files. Free, zero-risk.
- **~143 GB in files over 500 MB not modified in 2+ years.** The first version of
  this line read "15.7 GB in 8 files", measured on access time, and was wrong by
  roughly tenfold - see the Phase 2 correction below. Among them the Android
  emulator images: `.android\avd` (7.8 GB subtree), the `android-34` system
  image, and a stale Google Play Games AVD.
- `AvidDownloads`, `SoftwareTorrent`, `Documents`, `inetpub` and
  `Documents and Settings` are all empty or junctions - 0 files between them.
- `Documentos\StarCraft II` is confirmed genuinely empty: 0 files, 0 subdirs,
  nothing hidden. Safe to delete.
- The singing project now exists in **three** places: `OneDrive\Documentos\
  _Personal\Clases canto\Tools`, `E:\Projects` on the SD card, and
  `C:\Projects`. Its `AGENTS.md` still names the OneDrive path as canonical.

### Caveats on these numbers

- **`C:\Windows` at 45.6 GB is overstated.** `WinSxS` is largely hard links into
  `System32`, counted once per name. Not reclaimable by deleting files.
- **Last-access times are not usable on this machine**, despite being recorded.
  Corrected during Phase 2; see below. Staleness is judged on modification time.

## Phase 2 - The viewer

Delivered as `app.py` plus `web/`. `python app.py` serves
`http://127.0.0.1:8770`.

- [x] Localhost server on a fixed port, serving the snapshot from SQLite as JSON
- [x] **By folder**: sortable table with drill-down and breadcrumbs, biggest child first, showing size on disk, logical size and file count
- [x] **By file type**: groups and top-60 extensions, with each group's share of the disk
- [x] **By age**: buckets on modified and accessed, side by side
- [x] **Biggest single files**, filterable by group, minimum size, and how long since it was touched
- [x] Cloud-only vs on-disk shown distinctly everywhere, so you never plan a cleanup around bytes that were never there
- [x] Open-in-Explorer link per row, so a decision is one click from the actual folder
- [x] A visible note of which snapshot is loaded and when it was taken, plus a drive-usage bar showing measured / unaccounted / free
- [x] Serve pages as UTF-8, so `Imágenes\Álbum de cámara` renders properly in the browser even though the console mangles it
- [x] **A video view of its own**, since video is 59% of the used space: folders holding local video, and every local video file over 700 MB
- [x] Name search across folders and files
- [x] Empty-folder list, carried forward from the Phase 1 findings
- [x] Annotate `node_modules`, `__pycache__`, caches and similar as regenerable, and mark junctions so their zero size is not mistaken for a bug
- [x] Verify the views agree with the snapshot: age buckets and type groups each sum to exactly 773.9 GB and 956,012 files, so no rows are lost in grouping
- [ ] Treemap or similar graphical view. Deferred - the bar-in-cell tables answer "what is big here" well enough that a treemap is decoration until proven otherwise

### The correction Phase 2 forced

**Phase 1 claimed last-access times were trustworthy on this machine. That was
wrong, and the Age tab now says so on screen.**

`DisableLastAccess = 2` means Windows records access times, which is what that
claim rested on. But it records reads by *any* process, and antivirus, the search
indexer and backup all sweep the whole volume. The evidence, which
`Store._atime_health` recomputes rather than leaving as a footnote:

- 253,215 files (182.7 GB) were "read" within six months despite not being
  modified for over two years.
- Access stamps cluster on a few calendar days instead of spreading out. One day
  accounts for **24% of all files**; six unrelated films all read "7 days ago"
  while their contents were last modified 193 to 603 days ago.

So the tool judges staleness by modification time, with access time shown dimmed
for comparison only. The difference is not cosmetic: files over 500 MB untouched
for two years are **143.3 GB by modification time against 15.4 GB by access
time**, a tenfold undercount. The Phase 1 finding of "15.7 GB stale" was a
symptom of the same error and has been corrected above.

### Performance notes

Whole-table aggregates are computed once at startup (~20 s) and cached, since a
snapshot is immutable once complete. Before that, the Age tab took 25 s per click
because it ran one full scan of 956k rows per bucket; it is now a single scan per
timestamp column. Every view responds in under 30 ms apart from name search at
about 1.1 s, which is a substring `LIKE` and cannot use an index.

## Phase 3 - Analysis passes

Read-only. Produces ranked candidate lists, deletes nothing.

- [ ] **Stale and large**: not *modified* in N years, over a size threshold, ranked by GB. Not accessed - see the Phase 2 correction
- [ ] **Regenerable junk**: `node_modules`, `.venv`, `__pycache__`, build outputs, browser and app caches, `Temp`, Windows Update leftovers, old restore points - grouped by how safely they come back
- [ ] **Finished downloads and installers**: `.iso`, `.msi`, `.exe` installers, archives in `Downloads` / `SoftwareTorrent` / `AvidDownloads`
- [ ] **Duplicates**: group by size, then partial hash, then full hash. Report only proven byte-identical sets, with all copies' paths so you pick which to keep
- [ ] **Duplicate trees**: whole folders that are copies of each other - notably `E:\Projects\singing-practice-tools` vs `C:\Users\andry\OneDrive\Documentos\_Personal\Clases canto\Tools`
- [ ] **Empty folders**, reported with whether they hold hidden files (e.g. `Documentos\StarCraft II`, already confirmed empty)
- [ ] **Emulator and VM images**: `.android\avd`, Android SDK system images, Play Games AVDs, `.vhdx`/`.qcow2`. 19.4 GB of disk images total, much of it stale, and all of it regenerable by recreating the emulator
- [ ] **macOS turds**: `._*` and `.DS_Store` files, notably throughout `E:\Projects`. Tiny, but they are noise in every listing
- [ ] **Installed software inventory**: every program with its install size and last-used date, so the decision is per-application, not per-folder
- [ ] Every candidate carries a confidence and a one-line reason in the viewer

## Phase 4 - Reclaim space

First phase that changes anything. Smallest-risk, highest-GB first.

- [ ] Review the Phase 3 lists together and mark keep / delete / archive
- [ ] Reclaim the zero-risk tier first: empty the Recycle Bin (3.7 GB), caches, temp, regenerable build output, old Windows Update files
- [ ] Stale emulator and VM images (~15 GB, untouched 2.5+ years, recreatable)
- [ ] Then installers and finished downloads
- [ ] Then duplicates, keeping one canonical copy each
- [ ] Deletions in batches, to Recycle Bin, each logged to a reversible manifest
- [ ] Re-measure free space after each batch and record the GB actually recovered
- [ ] **The video decision, which is the whole ballgame.** 459.6 GB on disk, so
      everything else combined is worth less than a third of it. Ripped
      series and movies under `C:\Videos\Torrent*` are ~180 GB and are
      re-obtainable; `Hikaru no Go` is another 66.9 GB. Personal footage in
      `Imágenes\Álbum de cámara` is not replaceable and should be treated
      separately. Keep / move to external / delete, per group, your call

## Phase 5 - Reorganize

Structure, not space.

- [ ] Agree the taxonomy for `OneDrive\Documentos`: what the `_*` folders mean and what belongs in each
- [ ] Decide what to do about apps writing into `Documentos` uninvited (MuseScore4, Scanned Documents, Sound Recordings, StarCraft II) - redirect them or accept and quarantine them under one folder
- [ ] Settle the canonical home for code: pick **one** of the three copies of the singing project (`OneDrive\Documentos\_Personal\Clases canto\Tools`, `E:\Projects`, `C:\Projects`) and retire the others. Confirm with git which has the newest commits before choosing
- [ ] Resolve `E:\Projects` - it is on the Switch SD card. Move `HomeNetworkMonitor` somewhere real, retire the duplicate copy, strip the macOS `._*` files
- [ ] Update the singing project's `AGENTS.md` when its path changes, since the old path is documented in it
- [ ] Get large media off `OneDrive\Escritorio` and out of the Desktop tree - 66.9 GB of video on the Desktop is both a sync cost and a clutter problem
- [ ] Work out what `Users\andry\Videos\history\_has_content` is (54.7 GB in 72 files). It is also one of the odd entries in the Explorer sidebar, so the two questions are probably the same question
- [ ] Write `AGENTS.md` in `OneDrive\Documentos` describing the folder contract, so the structure survives
- [ ] Clean up the Explorer sidebar: Quick access pins and recent-folder behaviour, pin what you actually use

## Phase 6 - Keep it that way

- [ ] Re-run the scanner and diff against the Phase 1 baseline: what grew, what appeared
- [ ] A short recurring routine - what to check, how often
- [ ] Record the final numbers: GB recovered, where from

---

## Explicitly not doing

- Automatic or scheduled deletion of anything
- Registry cleaning, "optimizers", or third-party cleanup utilities
- Touching the Switch SD card's `atmosphere`, `switch`, `Nintendo`, `emuMMC`, `bootloader` or `games` folders
- Reinstalling Windows or moving the user profile to another drive
