# Working notes for agents

Read this first, then `ROADMAP.md` for where the work stands.

## What this is

A read-only inventory of this machine's `C:` drive, plus a local viewer, used to
decide what to delete and how to reorganize. The point is to rank and explain,
never to clean automatically.

`ROADMAP.md` owns the phase list and its status. This file owns the machine's
specifics and the traps. Do not restate a phase's status here.

## Ground rules

The failure mode here is permanent data loss, so:

1. **Scanning is separate from deleting.** Phases 1-3 only read.
2. **Deletions go to the Recycle Bin**, logged with original path and size.
3. **Never open or read the contents of a OneDrive placeholder file.** Attribute
   reads only. Opening one downloads it and *consumes* the free space we are
   trying to recover. `os.stat` is safe; anything that opens a handle to the
   data is not.
4. **Never touch** `C:\Windows`, `C:\Program Files*`, `C:\ProgramData`,
   `$Recycle.Bin`, `System Volume Information`, `Config.Msi`, `Recovery`,
   `$SysReset`, `hiberfil.sys`, `pagefile.sys`, or a running app's `AppData`.
   They are measured and reported, not edited. Software goes through
   Add/Remove Programs.
5. **Duplicate means byte-identical, proven by hash.** Not same name, not same
   size.
6. **The user decides what goes.**

## This machine

Windows 11. `C:` is 952.8 GB total, 158.6 GB free at the 2026-09-24 baseline.
Python 3.11 at `C:\Python311\python.exe`. PowerShell, so `&&` does not chain -
use `;`.

- **`E:` is a Nintendo Switch SD card**, not a data drive. `E:\Projects` is a
  macOS-made copy (hence the `._*` files) and
  `E:\Projects\singing-practice-tools` duplicates
  `C:\Users\andry\OneDrive\Documentos\_Personal\Clases canto\Tools`. Never
  touch `atmosphere`, `switch`, `Nintendo`, `emuMMC`, `bootloader`, `games`.
- **`DisableLastAccess = 2`** (System Managed, updates enabled), so `atime` is
  meaningful on this machine. Granularity is about an hour. Do not assume this
  holds on other machines - it is off by default in many configurations, and
  every "not accessed in N years" conclusion depends on it.
- **WSL Ubuntu 2 exists but is the wrong tool.** It reaches `C:` only through
  `/mnt/c`, which is roughly an order of magnitude slower and cannot read
  OneDrive placeholder state. Use native Windows Python.
- Stdlib only. No new dependencies.

## Traps

1. **OneDrive placeholders lie about size.** A cloud-only file reports its full
   logical size to `stat` while occupying zero bytes on disk. Planning a
   cleanup on logical size recovers nothing. `scan.py` records both, and the
   viewer must show them distinctly.
2. **Not every reparse point is a junction.** `OneDrive` and the `_*` folders
   under `Documentos` are reparse points with cloud tags and must be descended
   into. Junctions and symlinks (`AppData\Local\Application Data`) must not be,
   or the walk recurses forever. Discriminate on `st_reparse_tag`, never on
   the `ReparsePoint` attribute alone.
3. **`C:\Windows\WinSxS` is mostly hard links** into `System32`. Its bytes are
   counted twice in any naive walk, so it looks enormous and is not reclaimable
   by deleting files. It gets cleaned with `DISM /StartComponentCleanup`, if at
   all.
4. **Paths can exceed 260 characters.** The walk uses the `\\?\` prefix
   internally and strips it before storing, so stored paths stay readable.
5. **A scanner total far below what Windows reports means something was
   silently skipped**, usually permissions. Check the `errors` table before
   trusting any number.
6. **Not running elevated** hides `ProgramData`, other users' profiles and parts
   of `Windows`. The snapshot records whether it was elevated; compare totals
   between an elevated and non-elevated run rather than assuming.
7. **The rollup needs an index on `dirs(parent_id)` alone.** It joins children
   to parents without naming a snapshot, so an index leading with `snapshot_id`
   cannot serve the lookup and SQLite scans the whole table once per parent.
   With the index the rollup is 8 seconds; without it, it does not finish. The
   same applies to any later pass that walks the tree by `parent_id`.
8. **The Windows console is cp1252 and mangles accented paths.** `Imágenes` and
   `Álbum de cámara` print as `Im?genes`. The stored strings are correct -
   `os.path.isdir` on them succeeds. Do not "fix" an encoding bug that is only
   in the terminal; print `ascii(path)` to check.

## Running things

```
python scan.py                      scan C:\ into data/inventory.sqlite3
python scan.py --root C:\Users      scan one subtree
python scan.py --list-snapshots     what has been scanned already
python scan.py --finish 1           index and roll up a walk that was interrupted
                                    afterwards; recomputes totals from the rows,
                                    so it is safe to re-run
```

Verify a scan before building on it. `--verify` checks the rollup invariant -
the root's subtree totals against the sums over `files` - and prints where the
permission denials cluster:

```
python scan.py --verify
```

A full `C:` walk is about 10 minutes for ~956k files; the rollup is 8 seconds.
If the rollup is not nearly instant, an index is missing - see trap 7.
