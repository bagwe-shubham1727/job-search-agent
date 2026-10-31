# Job-Search Agent 1 — The Contract and the Watch

**Student:** Shubham Bagwe · **Course:** INFO 7375 — Prompt Engineering for Generative AI (Northeastern University) · **Instructor:** Nik Bear Brown · **Assignment:** JS1, due 2026-10-31

A discovery-only agent. It watches one public job board (Stripe on Greenhouse), remembers the posting IDs it has seen, and reports only postings that are new since the last run. Each new posting gets two separate verdicts:
- **Record:** a deterministic rule anyone can recompute (CONTRACT.md §6).
- **Judgment:** Claude's opinion under a prompt contract, validated against a fixed schema and labelled as an opinion (§8).

The résumé is a **fictional persona**, Kiran Joshi ([`persona/kiran-joshi.resume.example.json`](persona/kiran-joshi.resume.example.json)). The agent never applies, contacts anyone or logs in.

**Start here:** [`CONTRACT.md`](CONTRACT.md) was written and committed first (`053fda0`, before any code).

## Language and toolchain

| | |
|---|---|
| Language | Python ≥ 3.12 (developed and run on 3.14.5) |
| Package manager | [`uv`](https://docs.astral.sh/uv/) (0.11.0); dependencies pinned in `uv.lock` |
| Runtime libraries | `httpx`, `pydantic` |
| Dev tools | `pytest`, `ruff`, `mypy --strict` |
| Model | `claude-sonnet-5-5` through the `claude` CLI (Claude Code 2.1.314 for every recorded call), signed in with a Claude subscription. No API key is used or needed |
| Platform | macOS (darwin); nothing is macOS-specific |

## Commands (from a fresh clone)

```bash
uv sync                          # create .venv and install pinned dependencies
uv run jsa doctor                # offline checks: config, résumé gate, claude on PATH, data dir
uv run pytest                    # full suite: 973 tests, offline (the network is blocked in tests)
uv run ruff check . && uv run mypy src
```

Reproduce the seeded pair offline, without touching the graded `data/` folder:

```bash
uv run jsa --data-dir data/scratch run --replay evidence/handcheck/stripe-jobs-2026-10-29T22-41-31Z.json --model-backend none
uv run jsa --data-dir data/scratch run --replay data/live/runs/2026-10-30T01-52-15Z/raw/greenhouse-stripe.json --model-backend none
```

The first prints `BASELINE` (734 IDs). The second finds 3 new postings. With `--model-backend none` their judgments are `UNAVAILABLE`, so it reports `PARTIAL_FAILURE`. With `--model-backend claude-cli` (the committed pair) it reports `SUCCESS_WITH_NEW`.

Other commands:

| Command | What it does |
|---|---|
| `uv run jsa run` | Live run: fetch the board once, rule and judge each new posting |
| `uv run jsa rule <posting-id>` | Print the rule record for one posting |
| `uv run jsa verify-evidence` | Recompute every saved raw file's SHA-256 against its `.meta.json` |
| `uv run jsa audit-privacy` | Scan outputs for résumé values, credentials and absolute paths |
| `uv run jsa pending` | Inspect or drop judgments left pending |

A live run needs network access and a signed-in `claude`. Without `claude`, judgments are `UNAVAILABLE` and stay pending; the agent never falls back to an API key.

## What ran

All runs below are real and committed. Full tables: [`docs/RUNS.md`](docs/RUNS.md).

| Run | When (ET) | Status | Fetched | New |
|---|---|---|---|---|
| Live 1, baseline | 2026-10-29 21:52 | `BASELINE` | 736 | 0 |
| Live 2, second calendar day | 2026-10-30 23:03 | `SUCCESS_WITH_NEW` | 746 | 21 |
| Live 3, third calendar day | 2026-10-31 15:22 | `SUCCESS_NO_NEW` | 745 | 0 |
| Seeded 1 (replay of the 18:41 hand-check response) | 2026-10-29 22:21 | `BASELINE` | 734 | 0 |
| Seeded 2 (replay of live 1) | 2026-10-29 22:21 | `SUCCESS_WITH_NEW` | 736 | 3 |

- **Live 2:** both judges ran on all 21 new postings. The rule gave `NO_MATCH` on all 21. Claude's 21 replies were all valid and all `NOT_RELEVANT`.
- **Live 3:** no posting was new. The board had shrunk to 745, and the 757 IDs seen so far are kept: a disappeared ID is never forgotten (CONTRACT §10).
- **Evidence:** raw responses are saved byte for byte with their SHA-256 (`data/live/runs/*/raw/`); state is in `data/live/state.json`. `verify-evidence` passes on every file.

## The three chapter artifacts

| Chapter | Report | Headline |
|---|---|---|
| 1. Sampling | [`docs/experiments/SAMPLING.md`](docs/experiments/SAMPLING.md) | 5 postings × 4 fresh calls: 20/20 valid; 15/20 agree with my labels; 8249901 is unanimous and wrong |
| 2. Prompt experiment | [`docs/experiments/PROMPT_EXPERIMENT.md`](docs/experiments/PROMPT_EXPERIMENT.md) | v1 → v2 (only `label_definition` changed): dev 7/10 → 10/10, held-out 6/10 → 10/10 |
| 3. Action surfaces | [`docs/experiments/ACTION_SURFACES.md`](docs/experiments/ACTION_SURFACES.md) | Chosen: surface (a), stdin with no tools |

## Repository map

| Path | Contents |
|---|---|
| `CONTRACT.md` | The contract (written first) |
| `src/job_search_agent/` | The agent ([`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)) |
| `tests/` | Unit, contract and meta tests. CONTRACT → code → test map: [`docs/TRACEABILITY.md`](docs/TRACEABILITY.md) |
| `prompts/` | `judge.v1.md`, `judge.v2.md`, `CHANGELOG.md` |
| `persona/` | The fictional résumé |
| `evidence/` | The hand-check raw response (2026-10-29 18:41 ET) |
| `data/live/`, `data/seeded/` | Run outputs and state files |
| `data/experiments/`, `experiments/` | Experiment calls and results; labels, prediction and procedure |
| `docs/` | Plan, network notes ([`NETWORK.md`](docs/NETWORK.md)), build log, sign-off facts |
| `SOURCES.md`, `FRICTIONAL.md` | Sources and AI use; my Frictional log |

Left out on purpose: caches, `.venv`, credentials, `data/tmp/`, `data/scratch/`, and my real résumé (it stays in the gitignored `private/`).

## Sign-off

Candidate facts for "Not checked" and "Not claiming": [`docs/FACTS_FOR_SIGNOFF.md`](docs/FACTS_FOR_SIGNOFF.md).

<!-- STUDENT WRITES THIS -->

```text
Sign-off — Job-Search Agent 1
Checked:      which properties, by which of my own tests (name them)
How:          by hand / by a test I wrote before reading Claude's code /
              by recomputation / with Claude's help (say which parts)
Not checked:  at least three real items
Not claiming: what this agent does not show
Signed or withheld: ____________ (name, date)
```

## Driver's seat

<!-- STUDENT WRITES THIS -->
<!-- Columns: Task | What Claude did | What I did | Why that part stays mine | Pointer (transcript line or edit).
     Candidate pointers that are already on record:
     - 053fda0: CONTRACT.md committed first, my text (BUILD_LOG 2026-10-29 17:40: Claude declined to ghostwrite it).
     - f5fb431: my sampling prediction, committed before any sampling call.
     - 14e51f9: my 20 hand labels sealed before any model call.
     - c2e5599: my v2 choice and rationale in prompts/CHANGELOG.md, before any v2 call.
     - BUILD_LOG 2026-10-30 02:35: Claude waited for my prediction rather than running first. -->

| Task | What Claude did | What I did | Why that part stays mine | Pointer |
|---|---|---|---|---|
| | | | | |
