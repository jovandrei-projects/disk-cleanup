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

If the figures are not available at the end of a session, write the row with
the counts left as `n/a` rather than skipping it, so the session is still
accounted for.
