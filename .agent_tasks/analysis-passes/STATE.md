# Task: Analysis passes - finish the candidate kinds

**Status:** done, apart from one blocked comparison (E: unmounted)
**Started:** 2026-09-27   **Last touched:** 2026-09-27

## Objective

Every candidate kind in `ROADMAP.md` Phase 3 is produced from the snapshot
and shown in the viewer with a one-line reason. All ten kinds now exist.

## What landed (2026-09-27)

- `analyze.py --dupes`: same-size grouping (>=1 MB, `cloud_only=0`) ->
  head+tail 64 KB partial hash -> SHA-256 -> `dup_sets`/`dup_members` tables.
  Members carry `nlink`/`ino` so the viewer counts **physical copies** -
  1,766 of 2,687 sets are fewer files than names (hard links, trap 3).
  Result on snapshot 2: 2,687 proven sets, 6,984 copies; honest reclaimable
  is far under the naive 18.3 GB. `hashes(path,size,mtime,sha256)` persists
  across runs and snapshots.
- `analyze.py --trees` / `Store._treedups`: per-dir subtree signature
  (name+size of every descendant) -> topmost-match collapse -> groups
  reported only if not wholly under protected roots. Proof verdicts persist
  in `tree_proofs(snapshot_id,sig)`; `--dupes` proves (143 identical,
  17 differing, 168 reported of 275 signature groups), the viewer pass only
  reads. Signature computation is ~4 s inside `warm`.
- `analyze.py --software` / `Store._software`: HKLM64/HKLM32/HKCU uninstall
  keys, minus SystemComponent/ParentKeyName, `InstallLocation` (or
  uninstaller-dir guess) joined to scanned dirs -> 96 apps, real on-disk
  size where locatable. New "Software" tab.
- Viewer: "Duplicate files" + "Duplicate folders" sections in Recommended
  (tick the copies to remove; marks go to `decisions` by path).

## Deferred or blocked

- Nothing open. Snapshot 3 (elevated, 2026-09-28) is current; dup sets and
  tree proofs were recomputed against it (2,993 sets, 147 proven groups).

- ~~**`E:\Projects` vs `Clases canto\Tools` comparison**~~ - resolved
  2026-09-27: the user deleted `E:\Projects` off the SD card, so the
  duplicate no longer exists. `HomeNetworkMonitor` (the other project that
  lived there) already had a copy at `C:\Projects\HomeNetworkMonitor`.
- **`analyze.py --dupes` must be re-run after a refresh** - the viewer
  warns when `computed_for` differs from the loaded snapshot.

## Verification

`node --check`, `py_compile`, `test_render.js` (all views incl. new
`software` case) and `scan.py --verify` pass. Tested on port 8771 - 8770
was already held by an older app.py instance.
