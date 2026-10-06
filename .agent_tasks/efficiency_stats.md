# Session cost

Appended at the end of every session, by the agent, before it stops. One row
per session. The purpose is to notice if the task workspace is costing more
context than it saves - if new input tokens climb while the work per session
does not, say so rather than just recording it.

Cached input is not free but is roughly an order of magnitude cheaper than
new input, so the column to watch is **new input**.

| Project / Task | Agent Messages | New Input Tokens | Cached Input Tokens | Output Tokens |
|---|---|---|---|---|
| `agent-workspace-setup` (workspace created, 2 tasks filed, no code) | n/a | n/a | n/a | n/a |
| `analysis-passes` (dup hashes, tree sigs, software tab; task done minus blocked E: check) | n/a | n/a | n/a | n/a |
| queue review + elevated rescan (snapshot 3), dup recompute, E:/GitHub items resolved | n/a | n/a | n/a | n/a |
| `reclaim-space` phases 1-2: reclaim.py primitive+guard+manifest, Reclaim tab, refresh/reload endpoints; all verified incl. live restore | n/a | n/a | n/a | n/a |
| `reclaim-space` phase 3 ordering set with user; app suggestion list + dup territory split produced from snapshot 4/3 | n/a | n/a | n/a | n/a |

If the figures are not available at the end of a session, write the row with
the counts left as `n/a` rather than skipping it, so the session is still
accounted for.
| `reclaim-space` first real batch: bin emptied 3.8 GB, 40 cache/build marks recycled 6.2 GB, snapshot 5 verified; 3 latent bugs fixed (parent-path candidates, `._%` wildcard, spent marks blocking batches); History tab + `uninstalls` tracking shipped, self-test + render green | ~35 | ~30 | 3 | 1 |
| `reclaim-space` 18 approved apps uninstalled via real uninstallers (silent flags + UAC one at a time); Edge/Plex rescinded; Discord crumbs recycled; root-refresh guard added; full rescan launched; ~29 GB install footprint removed | ~25 | ~20 | 4 | 1 |
| `reclaim-space` post-round rescan (snapshot 6, verified) + --dupes re-run; Recommended view regrouped by kind + dup territory split; installer false-positive fix; video/installer/dup breakdowns for user | ~20 | ~15 | 2 | 1 |
| `reclaim-space` Recommended view rebuilt: left sidebar with next-actions, progress-stage table, kind/state/territory filters; stage tags on rows; render test green | ~15 | ~12 | 1 | 1 |
| `reclaim-space` Recommended rework per user: board overview + focused slices, staged selection + bottom apply bar, per-candidate guard (guarded rows no longer tickable/batch-wedging), batch `/api/decide`, listen backlog fix (ECONNREFUSED under parallel bursts); render test green | ~20 | ~15 | 2 | 1 |
| `reclaim-space` "crash" was a server held hostage by a synchronous op: reclaim-batch and empty-bin now run on threads with status polls (refresh pattern); SHEmptyRecycleBinW E_UNEXPECTED-on-empty accepted + argtypes declared; render + self-test green, live POST round trips verified | ~30 | ~25 | 3 | 2 |
| `reclaim-space` UX cohesion pass: Reclaim tab folded into a "Send to the Recycle Bin" pipeline slice in Recommended; auto-refresh + auto-reload after batch/empty-bin (queue merge, reload recheck); group checkboxes everywhere; guarded rows split into "Handled elsewhere" with per-row advice; bare C: tree root unwrapped; SO_REUSEADDR stale-listener trap found + documented; all gates + live end-to-end green | ~40 | ~30 | 4 | 2 |
| `reclaim-space` progress/visibility pass: run_batch progress callback + covered-by-parent + propose prunes stale marks (queues parent refresh); scan --progress-file; OPLOG + /api/rescan worker; pipeline step cards + terminal + per-row status paint; span grpbox (a11y fix) + keeper exclusion + mirrored parent state; busySteps loading; live end-to-end verified incl. stale rxjs subtree rescan | ~45 | ~35 | 4 | 2 |
| `reclaim-space` viewer redesign per user round 3: sidebar->areas nav, pipeline split into bin/kept/rescan slices, Stats subnav, kind panels, "none" unmark + clear-marks, working /api/dupscan, analyze.py write-lock fix (trap 19); live-verified incl. dup run (2350 sets, snap 27) + none-mark round trips; all gates green | ~30 | ~25 | 3 | 2 |
| `reclaim-space` UX polish per user round 4: uniform [arrow][box] row grid + greyed dead boxes for untickable rows/groups, Recycle Bin naming everywhere, idle-vs-ready step-card states, persistent fold state, in-place mark refresh + working badge, clearer selbar labels, elsewhere guidance; frontend only, all gates green | ~15 | ~12 | 1 | 1 |
