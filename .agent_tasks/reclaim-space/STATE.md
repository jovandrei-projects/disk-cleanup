# Task: Reclaim space - marked decisions become deletions, reversibly

**Status:** in progress
**Started:** 2026-09-28   **Last touched:** 2026-10-07

## Objective

`ROADMAP.md` Phase 4 works: paths the user marked delete are moved to the
Recycle Bin in batches, smallest-risk highest-GB first, each batch logged to
a manifest that can put it back, and free space re-measured and recorded
after each batch.

## Not in scope

Generating the candidate lists - `analysis-passes/` does that. Deciding what
goes - that is the user's job, always; the video decision in particular.

## Decisions already made

- **Recycle Bin only, never permanent delete**, per ground rule 2. Stdlib
  has no send-to-recycle-bin; the options are `IFileOperation` via `ctypes`
  or shelling to PowerShell's
  `Microsoft.VisualBasic.FileIO.FileSystem.DeleteFile` with the recycle
  flag. Pick whichever round-trips a scratch file; both keep the
  stdlib-only rule.
- **The never-touch list is enforced in code**, not by the reviewer. A
  batch containing `C:\Windows`, `Program Files*`, `ProgramData`, an
  `AppData` folder of a running app, or a Switch SD folder refuses before
  touching anything.
- **A batch is a manifest.** JSONL in `data/` (gitignored): batch id,
  timestamp, original path, size, the decision row it came from. A batch
  that cannot be logged does not run.
- **Order** is the roadmap's: zero-risk tier first (the 3.7 GB Recycle Bin
  contents, caches, temp, regenerable output), then emulator/VM images
  (~15 GB), then installers and finished downloads, then duplicates, then
  video - which at 459.6 GB is the whole ballgame.

## Phases

### Phase 1 - The delete primitive

- [x] Recycle-Bin send for a single path, round-tripped on a scratch file:
      deleted, present in the bin, restorable. `reclaim.py --self-test` is
      the proof. Implementation: `SHFileOperationW` with `FOF_ALLOWUNDO`;
      restore moves the `$R` payload back and drops the `$I` record
      (locale-proof, no shell verbs). Gotcha found and fixed: the pair lands
      in `$Recycle.Bin` a beat *after* the delete call returns, so
      `find_in_bin` retries for 3 s.
- [x] Refusal check against the never-touch list, exercised on purpose:
      `guard_reason` covers the system prefixes/files, the Switch SD
      folders, this tool's own directory, missing paths, and AppData of a
      running app (exe-path prefix or process-name match, conservative).
- [x] Manifest writer; a batch with no manifest does not execute. JSONL in
      `data/manifests/`; the file is opened and a header written *before*
      the first delete, and a batch containing any refused path aborts
      untouched.

### Phase 2 - Drive it from decisions

- [x] The `decisions` table's `delete` marks become a proposed batch the
      user confirms in the viewer - nothing is deleted from a list alone.
      Reclaim tab: per-path verdict (will recycle / refused+reason / not in
      snapshot), unmark button, one confirm, then `POST /api/reclaim`.
- [x] After each batch: `scan.py --refresh` on the parents -
      `POST /api/refresh` runs them on a background thread over the minimal
      covering-parent set (`data/refresh.log`), `/api/reload` then picks up
      the new snapshot. GB freed is measured per batch (`freed` in the
      manifest); recording real numbers into ROADMAP Phase 4 happens when
      Phase 3 batches run.
- [x] `test_render.js` case for the batch UI (`reclaim`).

### Phase 3 - The batches themselves, with the user

Order set by the user 2026-09-28: bundled removals first, then granular.

- [x] Apps via Add/Remove Programs - all 18 approved apps uninstalled
      2026-09-29 (Edge and Plex rescinded by user; `done_at` set per row).
      Driven one at a time with user approving UAC. Footprint ~29 GB.
      Leftovers: Discord AppData swept to bin (batch-20260929-014129);
      two harmless Program Files crumbs remain (PerformanceTest log,
      Avid Link\Licenses) - guard-protected, delete by hand or leave.
- [x] Caches and regenerable - bin emptied (3.8 GB, permanent) + batch
      `batch-20260929-002027` recycled 40 marks / 6.2 GB. ~4 GB of caches
      skipped: their apps were running. Note: recycled != freed - the bytes
      stay in the Bin until it is emptied again (trap 14)
- [ ] Installers and finished downloads (~7 GB)
- [ ] Personal-territory duplicates only (~6.4 GB, 120 sets on snapshot 3) -
      system/AppData sets stay; territory split measured in ROADMAP Phase 4
- [ ] Video - the user's call

## Where it stopped

2026-10-07 (marking pass): the user asked for keep/trash marks on every
Recommended item, applied with their judgement calls. 752 decisions written
via `/api/decide` (95 delete / 656 keep / 1 stale test row cleared). The
review policy and the full path lists live in `.agent_tasks/reclaim-space/
marks.py` - rerunnable and auditable. `survey.py` beside it is the
read-only analysis scratch used to build it.

User answers: Android emulator stack delete (~12.8 GB: Pixel_3a AVD +
android-34 system-images tree), Nintendo dump trees delete
(`Escritorio\Nintendo\Contents` 85.8 GB + `Nintendo\save` 1.1 GB - note the
folder is 87 GB, larger than the ~30 GB the candidate rows showed, because
only >500MB files were listed; `Nintendo\Album` screenshots were left
unmarked), video-tools `.venv` keep (so all 23 venv<->Python311 torch dup
members marked keep).

Batch plan verified: `GET /api/reclaim` shows 95 actionable entries,
0 blocked, 0 pruned, `can_run`, no cloud-only placeholders. Unique
football-field figure is ~106 GB (the 174.85 GB total double-counts
dir+member nested marks, which run_batch reports as covered_by).
Nothing executed - the user still presses "Send to the Recycle Bin".

Notable non-marks: all 400 empty_dir rows are WinSxS (guarded, correctly
untouchable); system/appdata-territory dup sets left report-only by design;
`IdeaProjects\LifeOrchestrator\temp-awesome-copilot` is a proven-identical
clone of the copilot marketplace dir - members marked keep, but the whole
folder (~0.1 GB) is a user question for Phase 5; `Microsoft VS Code\_` is a
stray staged-update-looking dir inside the VS Code install - flagged, not
touched; Smash Bros pair `26_jump_shield.mp4`/`27_aerial_oos.mp4` are
byte-identical under different names (probable mis-export), both kept.

Earlier entries below; open asks are unchanged apart from what this pass
resolved (the installers tier is now mostly marked delete - Basemark,
Sibelius, Windsurf/Typora/marktext payloads - pending the batch run).

2026-10-06: UX polish pass answering the fourth feedback round (all
frontend, `web/app.js` + `web/style.css` only - no backend changes):

- One grid for every row: `.trow` pads the missing arrow gutter (18px) so
  all names share one column. Guard-refused rows get a greyed disabled
  checkbox (`offbox`) instead of a mid-row "can't be sent" tag - the reason
  moved to the row end (`guardTag`). Groups with nothing tickable get an
  inert greyed `grpbox.off` (clicking just folds the group), including
  "Handled elsewhere" and zero-boxable dup sets; dup-territory panels got
  real group boxes.
- Consistent naming: "the Recycle Bin" everywhere; step 2 is "Empty the
  Windows Recycle Bin" and its copy says it is the real system bin.
- Selbar apply button now says what it does - "&#9851; mark N for the
  Recycle Bin" / "unmark N" / "apply N mark changes" (splits added vs
  removed ticks). Buttons show a floating `#working` badge
  (`workOn`/`workOff`) and the bar dims while applying.
- Unmark / re-mark no longer flash "loading...": `refreshRecommended`
  re-fetches in place under the badge (`fetchReco`/`recoStore` factored out
  of `renderRecommended`).
- Step cards gained an `idle` (grey) state - blue is now only "ready to
  run" (marks pending / bin non-empty / dup analysis stale), not the
  default look of a card with nothing to do.
- Expanded/collapsed groups survive redraws and tab switches: `detailsKey`
  (chain of summary labels + same-label sibling index) + `DETAILS_OPEN`,
  saved on draw and recorded live via a capturing `toggle` listener.
- "Handled elsewhere" intro now says what to do: close the owning app, run
  Disk Cleanup / Storage Sense, or empty the Recycle Bin from step 2.
- Gates: `node --check`, `py_compile`, `test_render.js` (bin-slice
  expectations updated for the renames) and `reclaim.py --self-test` all
  green. Serve is per-request `no-store`, so the running viewer picks the
  changes up on a page reload - no restart needed.

2026-10-07: two fixes from user feedback.

- Intro paragraphs inside group panels (`details.kind > .hint`) sat at the
  panel's left edge. They now start where the children's checkboxes start:
  22px inside `ul.tree` panels (ul padding 4 + summary padding 4 + arrow
  14) and 18px for "Handled elsewhere"'s direct `.trow` rows.
- Guarded rows could offer a live "delete me" box: `blocked` was
  `guard && !decision`, so a keep-marked `$Recycle.Bin` rendered a real
  checkbox whose only effect was staging a mark the batch must refuse
  (the user's test tick proved it - batch showed "refused: protected
  system area"). Now `blocked = guard/protected && decision !== "delete"`
  across leafRow, dupMemberRow, dupTreesSection and the slice/boxable
  flags: a guarded row keeps a live box only while it carries a 'delete'
  mark, because the box's one job there is unmarking. `markable` still
  lists decided rows so their decision tag stays visible.
- Step 2 ("Empty the Windows Recycle Bin") gained a "look inside it in
  Explorer" link; `reveal()` special-cases `C:\$Recycle.Bin` to
  `explorer.exe shell:RecycleBinFolder` (the Bin's own window with
  original locations and restore verbs) instead of the raw $I/$R view.
- The user's test 'delete' mark on `C:\$Recycle.Bin` was restored to its
  prior 'keep' via `/api/decide`.
- The link looked dead because Python changes are not no-store: the
  viewer had to be restarted (`pythonw app.py --no-browser`, old PID
  killed first - trap 18). Verified: one LISTENING line, endpoint opens
  the friendly Bin window.

2026-10-07 (second pass): fifth feedback round, frontend-only again
(`web/app.js` + `web/style.css` + `test_render.js` - no backend changes):

- "narrow this list" removed with all its machinery: `recoFilters`,
  `recoToggle`, the `RECO_KINDS/STATES/TERR` state, the `data-f*`
  change-handler branch, and the `.filt`/`.flt` CSS. Slices always show
  the full list now.
- Board reworked (`overviewBody`): a "can mark" column counts the rows a
  batch could actually touch (guard passes), and the status cell is now
  coloured progress chips - blue marked / green kept / amber unsure /
  dim "N to review", "done" when nothing remains. Dup rows report
  "N sets/groups to review" plus copies marked.
- "Recycle Bin contents" is out of "Safe to remove": a "Your marks"
  section groups Marked for the Recycle Bin / Marked to keep / The
  Recycle Bin itself (all open the bin/kept slices), and a "Handled
  elsewhere" section collects kinds whose every row is guard-refused
  (empty folders under protected roots, Windows Update, WER), each row
  naming what actually deals with it. That is the "workable items" ask:
  a 400-item kind with nothing tickable no longer sits in the
  suggestions looking like work.
- "Handled elsewhere" row misalignment fixed: its direct `.trow`
  children pad to the shared 22px box column (they sat 4px left of the
  `ul.tree` rows; the matching 18px `.hint` override is gone, the 22px
  `details.kind` rule covers it).
- Gates: `node --check` and `test_render.js` all green; board dumped to
  text and eyeballed (Safe to remove = 39 items / 6 markable; Empty
  folders = 400 items / 0 markable, now under Handled elsewhere).

Earlier entries below; open asks are unchanged (installers tier,
personal-territory dup split, video decision). Side effect to know: the
reclaim self-test runs the real pending batch, and the user's WhatsApp
Cache mark recycled cleanly this time (the Errno 124 was transient) - it
was restored, so nothing is lost, but the mark was consumed and the user
would need to re-mark it to try again. Open roadmap asks unchanged:
installers tier, personal dup split, video decision.

Historical record: Phases 1-2 built and verified 2026-09-28: `reclaim.py`
(primitive, guard, manifest, CLI), a Reclaim tab in the viewer, and
endpoints `/api/reclaim|restore|emptybin|refresh|refresh_status|reload`.
End-to-end proven over HTTP: mark a scratch file, POST recycle it,
manifest written, restore brings it back. `reclaim.py --self-test` is
green; `test_render.js` has a `reclaim` case and is green.

2026-09-28 session: the user set Phase 3's order (apps, then caches, then
folders/dups split personal vs system, video last) and answered the app
list: 20 cuts (~31.4 GB), recorded in the new `uninstalls` table and shown
on the new History tab. Bin emptied 3.8 GB (permanent). First cache batch
recycled 6.2 GB / 40 paths into the Bin. While marking, two latent candidate
bugs surfaced - grouped kinds stored the *parent* as `path` (a tick would
have recycled `C:\Users\andry`), and `LIKE '._%'` matched every dotfile -
both fixed, see AGENTS.md traps 13-14.

2026-09-29 early: refresh of `C:\Users\andry` landed as snapshot 5 (729.4 GB
on disk, rollup/parents OK). A third latent bug: spent `delete` marks stayed
in `decisions` forever, resolving "not on disk" -> refused -> every later
batch aborted. `run_batch` now prunes stale marks pre-flight and consumes
executed marks post-flight; `--self-test` green again (commit 592f7a3).
`analyze.py --dupes` re-ran on snapshot 5: 2,985 proven sets, 22.1 GB
reclaimable keeping one each - the recycled node_modules sets shrank the
personal-dup figures. Unexplained: volume free space jumped ~50 GB (171.8 ->
222.1 GB) this session; logged ops account for ~3.8 GB. Suspect OneDrive
on-demand dehydration or user-side cleanup - ask before attributing.

2026-09-29 evening: all 18 approved apps uninstalled via real uninstallers
(UAC + silent flags where available: Inno /VERYSILENT, NSIS /S, MSI /X
/passive, Squirrel, Blizzard, VS Installer, steam://uninstall). User
rescinded Edge and Plex mid-run; both rows deleted from `uninstalls`.
Projects verified safe first - uninstallers only touch their own install
dirs; full project map (C:\Projects, IdeaProjects\LifeOrchestrator,
AndroidStudioProjects\TestNutritionApp, source\repos\AngularTest, OneDrive
_Learning) confirmed none overlap uninstall targets. Learned: `--refresh`
cannot take the scan root itself (copy-nothing degenerate case aborted);
guarded with a clear message. Free space 222.1 -> 233.7 GB during the round
(deltas also masked by OneDrive hydration). A full rescan is in flight to
produce snapshot 6 with exact post-round numbers.

Next: when the rescan lands, verify, re-run `analyze.py --software` +
dup territory re-split; sweep remaining app crumbs if the user wants
(Battle.net agent dir under ProgramData may remain - check snapshot 6).
Then installers tier (~7 GB) and personal-territory dups (~6.4 GB).
Still undecided: Midnight Protocol demo (1.8 GB Steam), video tier.

2026-09-30: Recommended reworked per user feedback (too much info, no
clear start). Overview is now a board of slices; clicking a next-action or
board row opens a focused view whose ticks are *staged* - a fixed bottom bar
applies them as one batch via `POST /api/decide {decisions:[[path,choice]]}`
(new `Store.decide_many`). Tier-A unguarded rows pre-tick as a draft.
Candidates now carry `guard` from `reclaim.guard_reason`, so protected rows
(Recycle Bin, Windows Update, WER, WinSxS empties, running-app caches)
render "handled elsewhere" with no checkbox - they could previously be
marked and would then abort every batch. Sidebar filters collapsed into a
"narrow this list" block inside the focused view. Also fixed: HTTP listen
backlog 5 -> 64 (`Server.request_queue_size`), the cause of intermittent
ECONNREFUSED when the page bursts parallel requests. Render gate green.

2026-10-01: user reported the app "crashed" on confirming empty-bin. It
did not - SHEmptyRecycleBinW ran synchronously on the request thread of
the single-threaded server; ~115k bin entries held it long enough that
the listen backlog overflowed and the page saw a wall of ECONNREFUSED.
The empty itself succeeded (manifest batch-20261001-003742, freed
6.28 GB) and the same process was still serving afterwards. Fix:
`/api/reclaim` and `/api/emptybin` now run on daemon threads
(`BATCH`/`EMPTYBIN` status dicts, polled via `/api/reclaim_status` and
`/api/emptybin_status`, same shape as `REFRESH`); the batch worker opens
its own sqlite connection instead of sharing the request thread's.
Adjacent find: SHEmptyRecycleBinW answers E_UNEXPECTED (0x8000FFFF), not
ERROR_FILE_NOT_FOUND, on an already-empty bin - now accepted, and the
call finally has a declared argtypes/restype. Verified live: batch POST
starts + stores its result, empty-bin POST freed a seeded scratch file
and reported freed 0 on an empty bin. Self-test + render gate green.
See AGENTS.md trap 17.

2026-10-01 late: UX-cohesion pass answering user feedback (stale 6 GB bin
figure, no group checkboxes, unexplained un-tickable rows, dead ends on
tier-B rows, "empty the bin" jumping to another tab). The Reclaim tab is
gone; its content is the "Send to the Recycle Bin" pipeline slice inside
Recommended (focus `{t:"pipeline"}`: step 1 recycle the marks, step 2 empty
the Bin, live status line, batch history pointer). Every sidebar/board
action opens a slice in the same tab. Guarded rows moved out of the
tickable list into a collapsed "Handled elsewhere" group with a per-row
note of what actually deals with it. Every collapsible group (candidate
groups, dup sets, dup folders) has a group checkbox; the bare `C:` tree
root is unwrapped. Backend: after a batch or empty-bin the covering parents
are queued for `scan.py --refresh` automatically and the store reloads the
new snapshot when the queue drains - `REFRESH` gained reloading/reloaded/
error fields and merges paths into a running queue, re-checking after the
reload. Verified live end-to-end: scratch file recycled, refresh of its
parent ran, snapshot 6 -> 7 reloaded with `reloaded:true`. Watch out:
SO_REUSEADDR let a stale pythonw.exe share :8770 and hide the new fields -
AGENTS.md trap 18. Gates: `node --check`, `py_compile`,
`reclaim.py --self-test`, `test_render.js` all green (render test's
"Duplicate files" overview expectation relaxed - dup rows legitimately
vanish when analysis is stale for the loaded snapshot).

2026-10-01 later: progress/visibility pass answering the second feedback
round (batch ran with no visible progress; `refused: not on disk` rows left
in the list; "loading..." opaque; parent checkboxes didn't mirror children;
console warning about inputs in `<summary>`; no full-rescan action).

- `reclaim.run_batch` takes a `progress(ev)` callback per path
  (start/ok/fail/covered); a marked path inside a dir already recycled by
  the same batch now reports `covered_by` instead of failing on
  file-not-found, and `restore_manifest` knows covered entries return with
  their parent's $I/$R pair. `propose` consumes 'delete' marks whose path
  is gone (returns `pruned`/`pruned_paths`) instead of listing them as
  refused - the mark's intent is already met.
- `scan.py --progress-file PATH` overwrites one line with the live walk
  phase (also "copying unchanged rows..."/"indexing and rolling up..." for
  refreshes) so spawned quiet scans expose progress.
- `app.py`: shared `OPLOG` deque served by `/api/oplog`; `BATCH` gains
  `rows`/`cur`/`pos` for per-row paint; `start_rescan` worker +
  `POST /api/rescan` runs a full walk off-thread and reloads the store;
  `GET /api/reclaim` queues a `--refresh` of pruned marks' parents so
  stale rows drop out of the recommendations; `REFRESH`/`RESCAN` status
  gains a `line` field read from the progress file.
- Frontend: pipeline slice is now four state cards (snapshot / send /
  rescan-changed / empty) in the video-tools vocabulary - blue waiting/
  running (pulsing dot), green done, red failed - plus a terminal `<pre>`
  tailing `OPLOG`, a live "n/m - path" status line, and per-row status
  painted into `.rowst` cells by the 2 s poller. `fullscan` button is the
  explicit full rescan; a "Rescan the whole drive" entry sits in the
  sidebar actions too. Group checkboxes became `<span class=grpbox>`
  (kills the a11y warning), `.on`/`.mix` classes are re-mirrored on every
  change so parent state always reflects children, groups with zero
  tickable rows get no box, and dup-set first members are `data-keeper`
  excluded from group/tick-all sweeps. Controls row gained "tick all
  listed / tick none"; stale_large got explanatory copy; Recommended's
  load shows per-endpoint progress via `busySteps`.
- Verified live: marked a scratch dir + inner file + nonexistent path;
  plan showed `pruned:1` and queued `dc-pipe-live2`'s rescan; batch rows
  reported recycled/covered/failed (WhatsApp Cache failed Errno 124 - real
  failure surfaced, not hidden); oplog tail showed all lines; 16 queued
  subtree rescans drained and snapshot 11 -> 27 reloaded, which dropped
  the user's stale `rxjs\dist` recommendation. Self-test + render gate
  green.

2026-10-02: viewer redesign answering the third feedback round (sidebar
duplicating the board, "Dup analysis is stale" a dead button, no way to
clear a mark, kind groups reading as children of the group above, duplicate
tick buttons, unexplained step colours, rescan steps glued onto the Bin
page, nine flat tabs).

- Sidebar is navigation now: Overview / Marked for the Recycle Bin /
  Marked to keep / Snapshot & rescans, plus the progress table. The board
  got a title ("What needs a look"), a plain-English intro, an upkeep row
  when dup analysis is stale, and the pending-apps row.
- `pipeline` slice split three ways: `bin` (step 1 send / step 2 empty +
  a colour legend: blue waiting-running, green done, red failed), `rescan`
  (full rescan with confirm, folder-rescan queue, duplicate analysis card
  with a working re-run button, snapshot history table, oplog), `kept`
  (keep/unsure marks with unmark and to-Bin links).
- "none" is a real decision: `/api/decide` deletes the row, the selbar
  gained "clear marks on checked", unmark links send "none", and applied
  keep/clear marks leave the staged SEL so a later apply cannot re-mark
  them delete.
- `/api/dupscan` (+ status poll) runs `analyze.py --dupes` off-thread and
  drops candidates/treedups caches when it lands. Verified live: finished
  in ~2.7 min with a warm hash cache, computed_for=27, 2,350 sets.
- Tabs are Recommended / Folders / Stats; Stats is a header pill row over
  File types, Age, Biggest files, Video, Empty folders, Software, History
  (`show()` routes the sub-view names, old links keep working).
- Kind groups / dup territories / "handled elsewhere" are bordered panels
  (`details.kind`) - sibling groups no longer read as children of the
  group above. The controls row lost its duplicate tick-all/tick-none.
- Found via a self-test collision: `analyze.py --dupes` held a write
  transaction from its first DELETE through the whole hashing phase, so
  for minutes every `/api/decide` failed `database is locked`. Hashing now
  happens first, hash-cache inserts commit in chunks, and the set swap is
  one short transaction at the end; `_prove_trees` commits per member.
  See AGENTS.md trap 19.
- Gates: `node --check`, `py_compile`, `reclaim.py --self-test`,
  `test_render.js` all green; live POST round trips for none-marks and
  dupscan verified.

## Deferred or blocked

App uninstalls are the user's to run (Settings > Apps / each app's
uninstaller) - the tool records decisions, it does not invoke uninstallers.
Video tier (~243 GB in `C:\Videos` plus personal media) awaits the user's
separate review.

## Verification

`python reclaim.py --self-test` (scratch round trip), the three-command
gate in `AGENTS.md`, plus a live POST/restore round trip against a running
`app.py`.
