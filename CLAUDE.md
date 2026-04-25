# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick command reference

```bash
.venv/bin/pytest                                # all 122 tests, ~20s
.venv/bin/pytest tests/test_parser.py::test_X -v  # single test
.venv/bin/ruff check src tests                  # lint
.venv/bin/pip install -e .                      # after dependency change

# CLI subcommands (cli.py is the single entry point)
.venv/bin/python -m kleinanzeigen_watcher test --query "monitor" --plz 01067 --radius 10
.venv/bin/python -m kleinanzeigen_watcher run --config config.yaml --once
.venv/bin/python -m kleinanzeigen_watcher run --config config.yaml --evaluate-existing
.venv/bin/python -m kleinanzeigen_watcher top5 --config config.yaml [--telegram]

# Cloud (GitHub Actions, the actual production runtime)
gh workflow run poll.yml             # manual trigger
gh run list --workflow=poll.yml --limit 5
gh run watch                         # last run, live
```

## Venv bootstrap (one-time, this machine has no `python3-venv`)

```bash
python3 -m venv --without-pip .venv
curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
.venv/bin/pip install -e '.[dev]'
```

## Architecture

**Production runtime is GitHub Actions, not local systemd.** `.github/workflows/poll.yml` runs `run --once` every 10 minutes and commits `kleinanzeigen.db` back to `main` as state. `digest.yml` runs `top5 --telegram` daily at 07:00 UTC. Local systemd unit-files exist under `systemd/` but are intentionally `disable`d — they are kept as a fallback / for offline dev. The repo at `https://github.com/hallohand/kleinanzeigen-watcher` is the source of truth.

**Data flow per poll** (single-process, sync):

```
config.yaml ─► load_config ─► Profile
   │
   ▼
url_builder.build_search_url(profile)        # builds /s-PLZ/slug/k0l1rN URL
   │
   ▼
fetcher.Fetcher.fetch(url)                   # httpx + UA rotation + robots.txt + retry
   │
   ▼
parser.parse_listings(html)                  # selectolax → list[Listing]
   │
   ▼
storage.filter_new(profile, listings)        # SQLite, returns only unseen IDs
   │
   ▼ (per new listing, if profile.ai_filter)
evaluator.Evaluator.evaluate(listing, system_prompt=profile.evaluator_prompt)
   │                                         # Claude Haiku 4.5 + messages.parse(Verdict)
   ▼ (only when verdict.recommended is True)
notifier.Notifier.send_listing(listing, verdict_reason=...)
   │                                         # Telegram sendPhoto with sendMessage fallback
   ▼
storage.mark_seen(profile, NEW_ONLY, verdicts=...)   # see "DB invariant" below
```

`scheduler.Scheduler` is the glue. It has three entry-points: `poll_once` (one cycle), `run_until` (n cycles, used by `--bootstrap`/`--evaluate-existing`), `run_forever` (long-running loop with SIGTERM via `threading.Event`).

## Non-obvious invariants

- **`Scheduler.poll_once` calls `storage.mark_seen(profile, NEW, ...)` — NEVER `mark_seen(profile, ALL_PARSED, ...)`.** The cloud workflow commits the DB on every change. Re-touching unchanged rows produces 144 git commits/day. Tests check the count delta.
- **First-run-per-profile auto-bootstraps.** If `storage.has_any_for_profile(name)` is False, the scheduler treats the run as a bootstrap (mark all as seen, no notifications). Use a fresh profile name to force re-bootstrap.
- **`Profile.evaluator_prompt` is per-call, not per-Evaluator-instance.** `Scheduler` passes it as `system_prompt=` on every `evaluate()`. The single shared `Evaluator` only holds the *default* prompt; per-profile overrides go through the per-call kwarg.
- **Detail pages (`/ad/`, `/VIP*`) are robots.txt-disallowed.** Only the search-results page (SRP) snippets are parsed. Don't add code that fetches detail URLs.
- **HTML-Parser anchors on `data-adid`.** CSS classes like `aditem-main--middle--price-shipping--price` look stable but are functionally-named — defensive parsing traverses from the `article.aditem` root.
- **Robots.txt-disallowed filters** (`anbieter:privat`, `anzeige:angebote`, `anzeige:gesuche`) must NOT go into the URL via `url_builder` — apply client-side after parsing.
- **`evaluator.Verdict` is Pydantic.** Use `client.messages.parse(output_format=Verdict, ...)`, not `messages.create()`. The `Verdict` schema is the single source of truth for what the LLM is allowed to return.
- **Migration on `Storage.__init__` is in-place.** Old DBs without `recommended`/`verdict_reason` columns get `ALTER TABLE`d. Schema changes must include a corresponding clause in `_migrate()` and a test in `test_storage.py::test_legacy_db_without_new_columns_is_migrated`.

## Test conventions

- **No live network.** All HTTP-using tests inject `httpx.MockTransport` (`fetcher.py`, `notifier.py`) or `unittest.mock.MagicMock(spec=Evaluator)` (anthropic SDK). Fixtures under `tests/fixtures/` are real captured HTML — used both for parser tests and for end-to-end pipeline tests via the mock transport.
- **`time.sleep` is monkeypatched** in `test_fetcher.py`, `test_notifier.py`, `test_scheduler.py` (autouse fixtures). Real sleeps would make the suite seconds slower.
- **TDD is the workflow.** Every commit on `main` shows the test added before the implementation. Apply the same pattern to new features. `superpowers:test-driven-development` skill is the rule.
- **No `storage._conn` access from outside Storage.** Tests use the public seams `storage.forget(profile, ids)` and `storage.count_seen(profile)`.

## RESEARCH.md and SETUP.md exist

- `RESEARCH.md` — empirical findings about kleinanzeigen.de URL/HTML structure, Cloudflare status, robots.txt rules, library choices. Read before changing the parser or URL-builder.
- `SETUP.md` — local-dev setup including the get-pip workaround. Cloud setup is in README.
