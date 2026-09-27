# Task: Agent handoff and context workspace

**Status:** done
**Started:** 2026-09-26   **Last touched:** 2026-09-26

## Objective

A session can end at any point and the next one resumes from
`.agent_tasks/QUEUE.md` plus one `STATE.md`, without the user re-explaining
anything. Ported from `C:\Projects\singing-practice-tools`, where the same
structure is already in use; enforced by `AGENTS.md`, which is injected
automatically, so it works with no pre-prompt from the user.

## Not in scope

Product work. Nothing in `scan.py`, `app.py`, `analyze.py` or `web/` changes.

## Decisions already made

- `scratch/` is gitignored, matching how the repository already treats
  `data/` and `reports/`. Conclusions must be lifted out of it into
  `STATE.md` or `ROADMAP.md`.
- The queue does not duplicate `ROADMAP.md`. Phases stay in the roadmap; the
  queue only orders tasks and points at folders. Phases 5 and 6 have no
  folders until they become work.
- No development-log equivalent was invented; this repository keeps its
  measurements in the per-phase findings sections of `ROADMAP.md` and that
  convention stays.

## Phases

### Phase 1 - Structure

- [x] `.agent_tasks/README.md` - the contract, layout, rules, cost discipline
- [x] `.agent_tasks/QUEUE.md` - master ordered task list
- [x] `.agent_tasks/efficiency_stats.md` - session cost table
- [x] `.agent_tasks/_template/STATE.md` - the template
- [x] Gitignore `.agent_tasks/*/scratch/`
- [x] This file, as the first real instance of the format

### Phase 2 - Enforcement

- [x] Task-workspace section in `AGENTS.md`, read before the roadmap at
      session start
- [x] File-ownership note in `AGENTS.md` extended with the new files
- [x] "Assume this is the last prompt of the session" section added, since
      it is the behavioural half of why the workspace exists

### Phase 3 - File the real work

- [x] `analysis-passes/`: the three Phase 3 candidate kinds `analyze.py`
      does not produce yet - hash-proven duplicates, duplicate trees, the
      installed-software inventory
- [x] `reclaim-space/`: Phase 4's decisions-to-Recycle-Bin pipeline with a
      reversible manifest
- [x] Phase 1 leftovers (elevated rescan, `System Volume Information`), the
      treemap, the GitHub-privacy decision and Phases 5/6 listed under
      *Not yet filed* rather than given empty folders

## Where it stopped

Complete. Next session starts from `QUEUE.md` task 1.

## Verification

None applicable; no code changed. Sanity check is that a fresh session,
given "Continue from .agent_tasks/QUEUE.md", reads `QUEUE.md`, opens
`analysis-passes/STATE.md` and starts its first unticked step.
