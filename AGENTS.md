# Working notes for agents

Read this first, then `.agent_tasks/QUEUE.md` for what to pick up next, then
`ROADMAP.md` for where the work stands.

## What this is

A read-only inventory of this machine's `C:` drive, plus a local viewer, used to
decide what to delete and how to reorganize. The point is to rank and explain,
never to clean automatically.

`ROADMAP.md` owns the phase list and its status. This file owns the machine's
specifics and the traps. `.agent_tasks/QUEUE.md` owns which task is next, and
each `.agent_tasks/<task>/STATE.md` owns the steps of work in flight. Do not
restate a phase's status here.

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

## The task workspace - read before starting work

`.agent_tasks/` holds the state of work in progress, so the plan does not die
with the session. The full contract is `.agent_tasks/README.md`, the template
`.agent_tasks/_template/STATE.md`. The short version:

1. **Read `.agent_tasks/QUEUE.md` first**, then the `STATE.md` of any task
   that is not `done`. If the queue is empty, fall back to `ROADMAP.md`. Do
   not open a second task while one is `in progress` unless the user asks.
2. **Progress is the checklist.** Tick a step only when it is finished *and
   verified*. Never delete a step: tick it, or move it to *Deferred or
   blocked* with the reason.
3. **Long output goes to `.agent_tasks/<task>/scratch/`**, which is
   gitignored, so any conclusion drawn from it must end up in `STATE.md`, or
   in `ROADMAP.md` if it is a measurement.
4. **Update `STATE.md` as state changes**, especially its *Where it stopped*
   line, which is what the next session acts on. Append a row to
   `.agent_tasks/efficiency_stats.md` before stopping.

A `STATE.md` step is a step of the work; a roadmap item is product state.
When a step lands and moves a roadmap item, tick both in the same commit.

## Assume this is the last prompt of the session

Sessions end without warning - credits run out, context fills up, something
crashes. Work accordingly:

- **Update `ROADMAP.md` when a phase item changes state**, in the same commit
  as the change.
- **When a measurement is taken, write the number down** where the roadmap
  keeps its findings. A superseded number is useful; a missing one is not.
- **Commit in coherent local groups** and never push without the user's
  explicit request.
- **If about to run low, stop and write rather than start something new.**
  Half-finished unverified code is worse than a documented gap. Say
  explicitly what was deferred.

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
10. **A `LIKE` pattern is not a place for Python escaping habits.** `'C:\\\\Users'`
    in source produces the pattern `C:\\Users`, which matches nothing and fails
    *silently* - zero rows is not an error. Single backslash is a literal in SQL
    `LIKE`: write `'C:\\Users\\%'` in source. Candidate generation once shipped
    with 24 over-escaped patterns and quietly returned empty lists for six
    candidate kinds. When a filter returns nothing on a machine where you know
    matches exist, suspect the pattern first.
11. **Empty folders need their *branch*, not their leaves.** A folder that holds
    only empty folders is one decision; reporting each leaf produced 95k rows,
    70k of them inside `WinSxS\Temp`. The right query is "subtree with zero
    files whose parent is not itself empty", grouped by parent.
12. **The Recycle Bin's `$I`/`$R` pair lags the delete call.** `SHFileOperationW`
    returns before the bin entry is visible to `os.scandir`, so a lookup right
    after a delete misses intermittently. `reclaim.find_in_bin` retries for
    3 s - do not shorten that. The pair is also how restore works: `$I` holds
    the original path UTF-16LE, `$R` holds the data; moving `$R` back and
    dropping `$I` restores without the shell's localized verbs.
13. **A candidate row's `path` is the unit a 'delete' mark recycles.** Kinds
    that group findings under a folder once stored the *parent* in `path`:
    ticking "7 macOS junk files" marked the folder holding them, which is how
    `C:\Users\andry` itself ended up marked - a 335 GB recycle of the whole
    profile. `analyze.candidates` now names the actual file or empty dir, and
    `guard_reason` refuses the profile root outright (`NEVER_EXACT`). Any new
    candidate kind that groups findings still has to put a deletable path on
    the row. Two adjacent bugs found with it: in `LIKE`, `_` is a single-char
    wildcard - `'._%'` matched *every dotfile* (`.condarc`, `.babelrc`), and
    the fix is `'.\_%' ESCAPE '\'`; and `reclaim._path_size` resolves file
    marks via parent-dir + name because the `lower(path||name)` fallbacks
    force a full table scan per mark.
14. **Recycling moves bytes; it does not free them.** A batch's `freed` is the
    volume's free-space delta and comes out ≈0 (or slightly negative from
    background writes) because the files still occupy `$Recycle.Bin`. The GB
    only materialize on `--empty-bin`, which is permanent. Report both numbers
    so a "6 GB batch" is not mistaken for 6 GB already recovered.
15. **`grp='installer'` means every `.exe`, not just setup files.** The kind
    once listed `Code.exe`, `Typora.exe`, `Devin.exe` as "installers already
    run" - ticking one would gut a working app. The query now also requires a
    setup-ish name (`setup`/`install`/`driver`/`unins`) or a download-ish
    location for `.exe` files, and excludes `$Recycle.Bin` outright. Any new
    "this file is disposable" kind needs the same paranoia: the difference
    between an installer and an installed program is context, not extension.
16. **`--refresh` cannot take the scan root.** Refreshing `C:\` hit the
    copy-nothing degenerate case and aborted mid-write; it now refuses early
    with a clear message. To refresh everything, run a full `python scan.py` -
    that is what a root refresh would be anyway.
17. **A synchronous disk operation on the request thread looks like a
    crash.** The viewer is a single-threaded `HTTPServer`; a minute spent
    inside `SHEmptyRecycleBinW` (or a multi-GB `SHFileOperationW` batch)
    fills the listen backlog, Windows refuses the overflow, and the page
    floods with `ERR_CONNECTION_REFUSED` while the process keeps running.
    `/api/reclaim` and `/api/emptybin` therefore run on daemon threads -
    `BATCH`/`EMPTYBIN` status dicts polled via `/api/reclaim_status` and
    `/api/emptybin_status`, same shape as `REFRESH`. Any new long operation
    belongs on a thread, and a worker that writes `decisions` must open its
    own connection (concurrent calls on one conn are not safe). Related:
    `SHEmptyRecycleBinW` answers `E_UNEXPECTED` (0x8000FFFF), not
    `ERROR_FILE_NOT_FOUND`, when the bin is already empty; both are accepted.
18. **Windows `SO_REUSEADDR` lets a second app.py silently share the port.**
    Two processes bound :8770 and answers alternated between the live and a
    stale instance, so a verified change looked unverified (hit 2026-10-01 -
    an old `pythonw.exe` hid the new status fields). Before trusting any
    check against the viewer, `netstat -ano | findstr :8770` must show ONE
    LISTENING line.
19. **A long write transaction anywhere locks out the viewer's marks.**
    `analyze.py --dupes` once opened its write transaction with the DELETE
    and held it through the whole hashing phase, so for minutes every
    `POST /api/decide` failed `database is locked` - found when the reclaim
    self-test crashed on it. Expensive phases must stay outside write
    transactions: cache inserts commit in chunks, and the result swap
    (delete + insert) is one short transaction at the end. The same rule
    holds for any future long analysis pass that shares the database.
20. **`reclaim.run_batch` is every 'delete' mark, not a fixture.** The
    self-test once ran it unscoped and swept a real 95-mark batch into the
    bin (fully restored - see `.agent_tasks/reclaim-space/STATE.md`,
    2026-10-07 incident). `propose`/`run_batch` now take `only={paths}`;
    tests must pass it. Second bug the incident exposed:
    `restore_manifest` processed manifest order, so an individually-binned
    child could restore before its marked parent and recreate that path -
    the parent's restore then died on "target already exists" with its
    `$R` stranded in the bin. Restores now sort parents-first (fewest
    `\`), covered entries last. If a merge-restore is ever needed by hand
    again: move the partial dir aside, `restore_pair` the `$R`, merge the
    aside in (file sets are disjoint), then remove the shell - OneDrive-
    scope dirs may refuse `rmdir` (errors 5/123) until moved out of the
    synced tree and the READONLY bit is cleared.

## Running things

```
python scan.py                      scan C:\ into data/inventory.sqlite3
python scan.py --root C:\Users      scan one subtree
python scan.py --list-snapshots     what has been scanned already
python scan.py --finish 1           index and roll up a walk that was interrupted
                                    afterwards; recomputes totals from the rows,
                                    so it is safe to re-run
python scan.py --refresh "C:\path"  rescan ONE subtree into a new snapshot (~1 min).
                                    The rest of the tree is copied from the latest
                                    complete snapshot. If the path is gone, its
                                    parent is refreshed instead - which is also
                                    how a deletion gets verified.

python analyze.py --dupes           hash same-size files and prove duplicate
                                    folders; persists dup_sets/dup_members/
                                    tree_proofs for the viewer (minutes the
                                    first time; hashes are cached by path).
                                    Re-run after a refresh.
python analyze.py --trees           print duplicate-folder groups (fast, no
                                    new hashing - reads stored verdicts)
python analyze.py --software        print the installed-software inventory
```

A snapshot is immutable once complete; refreshes append a new one that chains
via `snapshots.refresh_of`/`refresh_path`, so any two snapshots can be diffed.

The reclaim machinery (the only code allowed to change the disk):

```
python reclaim.py --self-test     round-trip scratch files through the bin
python reclaim.py --propose       show the batch the current delete marks imply
python reclaim.py --run --yes     execute it (manifest first, then Recycle Bin)
python reclaim.py --restore FILE  put back what a manifest recycled
python reclaim.py --empty-bin --yes   empty the Recycle Bin itself (permanent)
```

The viewer's pipeline slice (Recommended → "Send to the Recycle Bin") does
the same through `POST /api/reclaim`; the covering parents are then
rescanned automatically (`scan.py --refresh` on the refresh thread) and the
store reloads the new snapshot itself when the queue drains - no manual
refresh or reload step. The never-touch list is enforced in
`reclaim.guard_reason`; a batch containing a refused path aborts before
touching anything. Related machinery: `POST /api/rescan` runs a full `C:`
walk off-thread; `/api/oplog` serves the timestamped worker log the UI
shows as a terminal; `scan.py --progress-file` gives spawned walks a live
one-line status file; and `reclaim.propose` consumes 'delete' marks whose
path is gone (a stale mark's intent is met) instead of refusing forever.

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

## First run on a new machine

Clone and `python scan.py` - that is the whole setup. `data/inventory.sqlite3`
is a map of whatever machine it runs on, so an old machine's snapshots are
worthless on a new one: do not copy `data/` across machines. The full `C:`
walk takes about 10 minutes; `python app.py` serves the viewer once a
snapshot exists.

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
