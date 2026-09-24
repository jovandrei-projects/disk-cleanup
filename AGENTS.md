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
  *recorded* - but see trap 9: it is recorded for every process, not just the
  user, and is useless for staleness here. **Use `mtime`.**
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
9. **Last-access time is not evidence of use, even with recording enabled.**
   This was asserted in the first pass here and was wrong. Windows updates
   `atime` for reads by *any* process, and antivirus, the search indexer and
   backup all sweep the whole volume. On this machine 253,215 files (182.7 GB)
   were "read" within six months despite not being modified for over two years,
   and one single calendar day accounts for 24% of all access stamps. A person
   does not read a quarter of a disk in a day.

   Consequence: `mtime` is the staleness signal, and the difference is not
   marginal. Files over 500 MB untouched for two years are 143.3 GB by `mtime`
   and 15.4 GB by `atime` - a tenfold undercount. `Store._atime_health` computes
   this and the Age tab shows it, so the claim stays checkable instead of
   becoming folklore. Re-derive it before trusting `atime` on any other machine;
   the reverse error, assuming `atime` is always useless, is just as wrong.

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

The viewer:

```
python app.py                       http://127.0.0.1:8770
python app.py --port 9000 --no-browser
```

Loopback only, by design: the snapshot maps the whole filesystem. Whole-table
aggregates are precomputed at startup (about 20 s) and cached for the life of
the process, because a snapshot never changes once complete. Without that cache
the Age tab cost 25 s per click. If a new view needs a full-table aggregate,
add it to `Store.warm` rather than computing it per request.

## Verifying a change

Run all three. The first two are instant and catch most of it:

```
node --check web/app.js                 syntax
python -m py_compile app.py scan.py     syntax
node test_render.js                     every view, against a running app.py
```

`test_render.js` loads `web/app.js` in a VM with a stubbed DOM, points `fetch`
at the live server, renders each view and inspects the HTML. **It exists because
a mismatched quote once shipped a blank page while every JSON endpoint passed
its own tests.** Testing the API is not testing the app; if you add a view, add
it to the `cases` list there.
