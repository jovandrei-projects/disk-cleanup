# Task queue

The master ordered list. One line per task. This answers "what next"; the
task's own `STATE.md` answers "where in it".

Status is one of `next`, `in progress`, `blocked`, `paused`, `done`. Keep the
order meaningful, but see rule 3 in `README.md`: finishing something early is
fine, it just has to be ticked where it lives.

Conventions for `STATE.md` are in `README.md`; the template is in `_template/`.

| # | Task | Status | Folder | Waits on |
|---|---|---|---|---|
| 0 | Agent handoff and context workspace | done | `agent-workspace-setup/` | — |
| 1 | Analysis passes: duplicates, duplicate trees, software inventory | done | `analysis-passes/` | — |
| 2 | Reclaim space: marked decisions to the Recycle Bin, logged | next | `reclaim-space/` | 1, user review |

The order is intended, not binding. 1 finishes what `analyze.py` started -
the Phase 3 checklist in `ROADMAP.md` has three candidate kinds no code
produces yet. 2 is the first task allowed to change the disk, so it wants the
full candidate list in front of it and the user's marks behind it.

## Not yet filed as tasks

Open work that exists but has no folder, so nobody has to go looking for it:

- ~~**Elevated rescan**~~ - done 2026-09-28, snapshot 3 (elevated). Numbers
  and the `vssadmin` result are in `ROADMAP.md` Phase 1.
- ~~**`E:\Projects` tree-dup check**~~ - resolved 2026-09-27: the user
  deleted the folder off the SD card; nothing left to compare.
- **`System Volume Information`** - restore points and shadow copies, likely
  most of the gap between the scan total and what Windows reports. Measured
  with `vssadmin list shadowstorage`, elevated. Genuinely reclaimable.
- **Treemap view** - deferred in `ROADMAP.md` Phase 2; the bar-in-cell tables
  answer "what is big here" well enough that this is decoration until proven
  otherwise.
- **GitHub private vs local-only** - user decision; this repository maps the
  whole filesystem.
- **Phase 5 (reorganize) and Phase 6 (keep it that way)** - their checklists
  live in `ROADMAP.md`. Phase 5 is mostly user decisions (folder taxonomy,
  which copy of the singing project survives) and Phase 6 waits on Phase 4.
  File folders when they become work, not before.

A task gets a folder here when it is going to be worked on across more than
one session. Until then the roadmap is enough, and duplicating it would only
create two places to update.
