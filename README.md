# disk-cleanup

Read-only inventory of `C:` plus a local viewer, used to decide what to
delete and how to reorganize. Never cleans automatically - scanning is
separate from deleting, deletions go to the Recycle Bin, and the user
decides what goes.

## Run

```
python scan.py     # inventory C:\ into data/inventory.sqlite3
python app.py      # viewer at http://127.0.0.1:8770
```

## Test

```
python run_tests.py          # full suite
python run_tests.py --quick  # skips slow/browser tests
```

See `AGENTS.md` for project rules (long - the traps matter) and
`../TESTING.md` for the shared test policy.
