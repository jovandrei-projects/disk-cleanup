# Task: Reclaim space - marked decisions become deletions, reversibly

**Status:** in progress
**Started:** 2026-09-28   **Last touched:** 2026-09-28

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

Phases 1-2 built and verified 2026-09-28: `reclaim.py` (primitive, guard,
manifest, CLI), a Reclaim tab in the viewer, and endpoints
`/api/reclaim|restore|emptybin|refresh|refresh_status|reload`. End-to-end
proven over HTTP: mark a scratch file, POST recycle it, manifest written,
restore brings it back. `reclaim.py --self-test` is green; `test_render.js`
has a `reclaim` case and is green. Nothing real has been deleted.

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

## Deferred or blocked

App uninstalls are the user's to run (Settings > Apps / each app's
uninstaller) - the tool records decisions, it does not invoke uninstallers.
Video tier (~243 GB in `C:\Videos` plus personal media) awaits the user's
separate review.

## Verification

`python reclaim.py --self-test` (scratch round trip), the three-command
gate in `AGENTS.md`, plus a live POST/restore round trip against a running
`app.py`.
