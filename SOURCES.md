# Sources

What this submission used, what I wrote, and what Claude contributed. The day-by-day record, with commit hashes, is [`docs/BUILD_LOG.md`](docs/BUILD_LOG.md), written by Claude during the build.

## External sources

| Source | Used for |
|---|---|
| [JS1 assignment](https://github.com/nikbearbrown/info-7375-prompt-engineering-for-generative-ai/blob/main/assignments/assignment-js1-the-contract-and-the-watch.md), course AI policy, Frictional and GitHub-submission guides | Requirements |
| Stripe's public Greenhouse board, `https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true` | The job data. Saved responses are in `evidence/` and `data/` |
| Claude Code docs (`https://code.claude.com/docs/en/`: network-config, cli-reference, permissions, headless, data-usage, env-vars, legal-and-compliance), read 2026-10-29 | Judge flags, permissions, hosts: [`docs/claude-code-network-facts.md`](docs/claude-code-network-facts.md) |
| A local `career-ops` board list (`portals.yml`) | Candidate boards when choosing one |
| Python libraries: `httpx`, `pydantic` (runtime); `pytest`, `ruff`, `mypy`, `hatchling`; `uv` | Toolchain (see README) |
| Model: `claude-sonnet-5-5` via the `claude` CLI (Claude Code 2.1.314), on my subscription | Every recorded judgment and experiment call |

No code was copied from other projects.

## What I wrote

- **`CONTRACT.md` (commits `053fda0`, `c1bd530`, `7aa5d0f`):** I chose the target role families, level targets, skill categories, the switch to Stripe on Greenhouse, and the hard US-only location rule after inspecting the initial hand-check candidates (including evaluating `8249901`, `7543868`, `8175099`, and `8234357`), and edited the contract text across drafts with Claude's review feedback.
- **Chapter 1 (`experiments/sampling/hand_labels.json`, `data/experiments/sampling/SAMPLING.tables.md`, `docs/experiments/SAMPLING.md`):** I confirmed the 5 `CONTRACT.md §13` hand labels (`f5fb431`), provided the pre-run prediction before `jsa exp sampling run` executed, and provided the `## Conclusion` section (updated after Claude Code verified the 20-call reasons on `8234357` and `8127182`).
- **Chapter 2 (`experiments/prompt/labels/{dev,heldout}.labels.json`, `prompts/CHANGELOG.md`, `prompts/judge.v2.md`, `data/experiments/prompt/PROMPT_EXPERIMENT.tables.md`, `docs/experiments/PROMPT_EXPERIMENT.md`):** I sealed the 20 `dev` and `heldout` hand labels (`14e51f9`), chose Candidate 1 (`label_definition` replacement) after seeing the `7/10` `v1` `dev` run (`c2e5599`), directed Claude Code to use the `CONTRACT.md §6` lists in `judge.v2.md` to avoid held-out leakage, and provided the `## Rule-vs-hand decisions` and `## Conclusion` sections (`6f5dc0a`).
- **Chapter 3 (`data/experiments/surfaces/ACTION_SURFACES.tables.md`, `docs/experiments/ACTION_SURFACES.md`):** I provided the three `What could go wrong` risk cells and the `## Least autonomy that suffices` defense selecting Surface `(a)` (`--tools ""`).
- **FRICTIONAL.md, README.md sign-off and driver's-seat table, and SOURCES.md student sections:** Written and reviewed for final sign-off using docs/BUILD_LOG.md and docs/FACTS_FOR_SIGNOFF.md to trace the exact timestamps, commit hashes, and run counts.

## What Claude contributed

Claude (Claude Code, Opus 5.5 orchestrating; coding agents in separate worktrees) contributed:

- **Contract support, not the contract.** Claude declined to ghostwrite `CONTRACT.md` and gave a question sheet instead. It reviewed my drafts, verified every §13 hand-check claim against the raw file (finding one wrong path), and built the §6.4 US and non-US location signal lists from all 294 distinct `location.name` values at my request. It also computed the skill lists for the hand-check postings and found case 4 (8127182).
- **Board choice.** Claude first recommended Datadog, which was wrong (0 of 397 postings passed my title rule). It then probed boards and suggested Stripe, which I chose.
- **Persona.** Claude drafted the fictional `persona/kiran-joshi.resume.example.json` (`@example.com`, 555 phone), modeled only on my target roles and skill areas.
- **Evidence capture.** Claude saved the hand-check raw response (`evidence/handcheck/`), byte for byte with its SHA-256.
- **Plan.** A Claude planning agent wrote [`docs/PLAN.md`](docs/PLAN.md); Claude reviewed it and added amendments R1–R10.
- **All code and tests** in `src/` and `tests/`, written test-first by Claude coding agents. Claude also wrote the two wrong implementations (`tests/wrong_versions/`) and the meta-test that proves the suite catches them.
- **Reviews.** A Google-style code review and a ponytail audit, both by fresh Claude agents, and the fixes that followed (BUILD_LOG, 2026-10-30).
- **Prompt v1.** `prompts/judge.v1.md` was drafted by Claude. The pre-registered v2 candidates in `prompts/CHANGELOG.md` were written by Claude before the v1 dev run.
- **Prompt v2 lists.** In `prompts/judge.v2.md`, the lists inside `label_definition` were copied from CONTRACT §6 by Claude at my direction, replacing examples in my draft that came from held-out postings.
- **Running things.** Claude ran every recorded run and experiment call, and the privacy and evidence checks.
- **Generated docs.** The tables in the three experiment docs are generated by code. Claude wrote this file's factual parts, `README.md` (except the sign-off and driver's seat), and `docs/NETWORK.md`, `TRACEABILITY.md`, `ARCHITECTURE.md`, `RUNS.md`, `FACTS_FOR_SIGNOFF.md` and `BUILD_LOG.md`.

## AI assistance in my own parts

- **Contract review and §6.4 / §13 data extraction (`CONTRACT.md`, Oct 29):** As recorded in `docs/BUILD_LOG.md` (`18:10–19:15 ET`), Claude reviewed my contract drafts, turned my US-only location rule into finite US and non-US signal lists across the 294 distinct `location.name` strings in the October 29 Stripe response (`§6.4`), computed the complete skill path lists for the §13 hand-check postings, and found `8127182` as the `<2`-skills hand-check case.
- **Chapter 2 hand-label JSON formatting and pre-freeze check (`dev.labels.json`, `heldout.labels.json`, `judge.v2.md`):** I used AI assistance to format the 20 `dev` and `heldout` hand-label JSON entries and notes (`14e51f9`) from the `CONTRACT.md §6` rule criteria (which is why the `20/20` rule-vs-hand audit reflects consistency with the rule). Before freezing `judge.v2.md` (`c2e5599`), Claude checked the `v2` text against `CONTRACT.md §6`, flagged that several examples came from held-out postings, and replaced those examples with the full contract lists at my direction so the held-out set stayed clean.
- **Reference logs and fact-checking against repo artifacts (`BUILD_LOG.md`, `FACTS_FOR_SIGNOFF.md`, Chapters 1–3, `README.md`, `FRICTIONAL.md`):** Claude maintained the dated factual timeline in `docs/BUILD_LOG.md` and candidate sign-off items in `docs/FACTS_FOR_SIGNOFF.md`, and verified the cited counts, costs, commit hashes, and run reasons in my sections against the committed repository files before each commit (for example, checking the `3/1` split reason on `8234357` in Chapter 1 and the test/run counts in `README.md` and `FRICTIONAL.md`).
