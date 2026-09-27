# Task: Analysis passes - finish the candidate kinds

**Status:** next
**Started:** —   **Last touched:** 2026-09-26 (filed, not started)

## Objective

Every candidate kind in `ROADMAP.md` Phase 3 is produced from the snapshot
and shown in the viewer with a one-line reason. `analyze.py` already covers
stale-large, regenerable, installers/downloads, empty folders, macOS litter,
VM images and the Recycle Bin. What no code produces yet: hash-proven
duplicates, duplicate trees, and the installed-software inventory.

## Not in scope

Deleting anything - that is `reclaim-space/`. The video decision is the
user's. A treemap view.

## Decisions already made

- **Duplicate means byte-identical, proven by hash.** The roadmap's pipeline:
  group by size, then partial hash, then full hash. `hashlib` is stdlib.
- **Never read the contents of a OneDrive placeholder** (`cloud_only=1`).
  Hashing opens the file and hydrates it, so placeholders are excluded from
  every pass, not just the final one.
- New kinds join the Recommended list rather than getting their own tab,
  except where the shape differs: a duplicate set is a *group* of paths, not
  one row.

## Phases

### Phase 1 - Duplicates by hash

- [ ] Size grouping over `files`: `cloud_only=0`, above a floor worth
      hashing for, more than one file per size
- [ ] Partial hash (head + tail chunk) to cull, then full hash on survivors
- [ ] Report sets, not files: every copy's path, reclaimable = (n-1) x size
- [ ] Viewer rows for duplicate sets, with keep/delete marks that survive
      rescans the way `decisions` already does

### Phase 2 - Duplicate trees

- [ ] `E:\Projects\singing-practice-tools` vs `C:\Users\andry\OneDrive\
      Documentos\_Personal\Clases canto\Tools`. `E:` is not in the snapshot -
      a `scan.py --root E:\Projects` subtree scan gets it without walking the
      Switch folders, which are siblings of `E:\Projects`, not children
- [ ] Generic whole-tree duplicate detection inside `C:` if it is cheap -
      sibling dirs with identical file sets

### Phase 3 - Installed software inventory

- [ ] Uninstall registry keys (HKLM + HKCU, 64- and 32-bit views) via
      `winreg`: display name, install location, estimated size
- [ ] Join each InstallLocation to the scanned dirs so the per-app number is
      the real on-disk size, not the registered estimate
- [ ] Viewer table: one row per application

### Phase 4 - Confidence

- [ ] `ROADMAP.md` asks each candidate to carry a confidence and a one-line
      reason; tier A/B plus the reason string is the current answer. Decide
      whether that is enough or add a confidence field per kind

## Where it stopped

Not started. Begin with Phase 1's size grouping - and read the `dirs`/`files`
schema in `scan.py` before writing queries. Trap 10 applies to every `LIKE`
pattern written for this task: single backslash is literal, `'C:\\Users\\%'`
in source.

## Deferred or blocked

—

## Verification

The three-command gate under *Verifying a change* in `AGENTS.md`, plus
`python scan.py --verify`. `test_render.js` needs a case for any new view.
