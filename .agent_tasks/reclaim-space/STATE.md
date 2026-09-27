# Task: Reclaim space - marked decisions become deletions, reversibly

**Status:** next
**Started:** —   **Last touched:** 2026-09-26 (filed, not started)

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

- [ ] Recycle-Bin send for a single path, round-tripped on a scratch file:
      deleted, present in the bin, restorable
- [ ] Refusal check against the never-touch list, exercised on purpose
- [ ] Manifest writer; a batch with no manifest does not execute

### Phase 2 - Drive it from decisions

- [ ] The `decisions` table's `delete` marks become a proposed batch the
      user confirms in the viewer - nothing is deleted from a list alone
- [ ] After each batch: `scan.py --refresh` on the parents, GB recovered
      recorded in `ROADMAP.md` Phase 4
- [ ] `test_render.js` case for whatever the batch UI is

### Phase 3 - The batches themselves, with the user

- [ ] Zero-risk tier
- [ ] Emulator and VM images
- [ ] Installers and finished downloads
- [ ] Duplicates, keeping one canonical copy per set
- [ ] Video - the user's call

## Where it stopped

Not started. The real batches wait on `analysis-passes/` and the user's
review; the Phase 1 primitive does not - it can be built and proven on
scratch files in a test folder without touching a real target.

## Deferred or blocked

Phase 3 is blocked on the user's review of the candidate lists. Phases 1
and 2 are not.

## Verification

A created test file goes to the bin and back via the manifest; `python
scan.py --verify` still OK; the three-command gate in `AGENTS.md`.
