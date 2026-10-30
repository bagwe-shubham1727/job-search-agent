# Build log (written by Claude, the orchestrating session)

> **What this is.** A dated, factual record kept by Claude during the build: what was tried, what happened,
> what the student accepted, changed, or rejected, with commit hashes and test names. It is raw material for
> the student's `FRICTIONAL.md`, **not** a substitute for it. It contains no judgments attributed to the student
> beyond what they said or committed. Times are America/New_York.

## 2026-10-29

**17:24 Start.** The folder was empty. Claude ran the Claude Code setup analysis and read the official JS1
assignment, the AI policy, and the Frictional guidance from the course repo.

**~17:40 Declined request.** The student asked for CONTRACT.md and FRICTIONAL.md to be written "as I am writing it
in max humanize form". Claude declined to ghostwrite either file in the student's voice and cited
`prerequisites/ai-policy.md` ("do not ask AI to invent your struggle or understanding") and `frictional/06`.
Claude offered instead a question sheet for the contract and this factual log for FRICTIONAL.

**~17:50 Judge backend probe.** Claude tested `claude -p` headless calls under the student's subscription
(no API key in the environment). The default call cost $0.17 because it loaded all plugins and hooks. `--bare`
failed ("Not logged in", because bare mode needs an API key). An isolated call from an empty folder worked at
about $0.008 and about 1.9k context tokens.

**~18:00 Persona.** The student first asked for themselves as the persona. Claude pointed out that the assignment
forbids that ("Use a fictional persona, not yourself"). The student chose "new persona modeled on you". Claude
drafted `persona/kiran-joshi.resume.example.json`: fictional, `@example.com`, 555 phone, no real names, employers,
schools, or contacts, modeled only on the role targets and skill areas in the student's local career-ops profile.

**~18:05 Board choice, and a Claude mistake.** Claude recommended Greenhouse `datadog` based on a loose title regex
that counted every "Engineer" title. When the student's draft title rule was applied, **0 of 397** Datadog postings
passed: most were Sales Engineers, and the Software Engineer titles were Senior, Staff, or Intern. Claude reported
its own error. Probing the career-ops boards under the student's title rule put Stripe first (55 title-passing:
35 with ≥2 skills, 20 with <2). The student switched to Stripe.

**18:10–19:00 Contract reviews (Claude reviewed, student wrote).**
- Draft 1: Claude flagged a baseline that conflicted with the spec ("first run reports none as new"), the missing
  validator for Claude's output, Claude's 3-label scale versus the 2-label hand labels, `C#` turning into `c` under
  punctuation stripping (`c` matched 6–9 times per board), REST/React/Express matching as plain English, and HTML
  in `content`.
- The student's next draft fixed those and moved to Stripe.
- After the hand-check candidates were fetched, the student added a hard **US-only location rule**. Bengaluru
  posting 7543868 had passed title and skills.
- Claude verified every hand-check claim against the raw file. It found one wrong path (GraphQL is
  `$.skills.backend[4]`, not `[3]`) and showed that "clearly names a US city" was not hand-predictable on Stripe's
  294 real location strings (`SF, NYC, CHI, ATL, SEA`, `Remote in Canada`, `New York or San Francisco`).
- A later draft the student pasted said the workspace lacked files that did exist. Claude flagged those
  statements as false for the repo; that draft was not committed.

**18:40 Commit `053fda0`.** First contract, the student's text, committed (on the student's request) with the
student as author. Pushed.

**22:41Z (18:41 ET) Raw evidence.** Claude saved the Stripe response byte-for-byte:
`evidence/handcheck/stripe-jobs-2026-10-29T22-41-31Z.json` (734 postings, HTTP 200; sha256 in `.meta.json`).
Claude picked hand-check candidates by title only. The student hand-evaluated four of them (8249901, 7543868,
8175099, 8234357).

**~19:10 Location lists and case 4.** At the student's request ("keep the us only rule and add hand checks"),
Claude:
- turned the US-only rule into finite signal lists built from all 294 distinct `location.name` values;
- computed complete skill lists for the hand-check postings;
- found 8127182 (only Java matches) as the fewer-than-two-skills case.

**19:15 / 19:19 Commits `c1bd530`, `7aa5d0f`.** The student committed the amended contract (the student removed
§18–§19 and then the dangling §19 reference). Claude committed the data files in `ba1d9f0` (persona, raw evidence,
.gitignore). The student asked to drop the Claude co-author trailer. Amending the pushed commit needs a force push,
which Claude Code's safety classifier blocked, so `ba1d9f0` keeps its trailer and later commits have none.

**19:30 Planning.**
- A fresh planning agent wrote `docs/PLAN.md`.
- A docs agent gathered Claude Code network and flag facts (`docs/claude-code-network-facts.md`).
- Claude reviewed the plan and added amendments R1–R8. R1 replaced the undocumented `--setting-sources ""` with
  the documented `--setting-sources project --safe-mode` plus three traffic-disabling env vars. It was verified
  19:33 ET: `is_error: false`, 1,642 context tokens. R2 corrected `Write(...)` permission rules, which never
  match per the docs, to `Edit(...)`.
- Commit `33ea56e`.

**21:01 Usage limit.** Work paused until the claude.ai usage limit reset, then resumed.

**21:05–21:20 WS0 foundation.** A fresh coding agent built the toolchain, shared models, ports, config, and test
harness (commit `1493176`). Claude re-ran the acceptance independently: ruff clean, `mypy --strict` clean on 16
files, pytest 96 passed / 1 skipped (live).

**21:25 WS1–WS4 launched** in parallel git worktrees with disjoint file ownership: rule core, policy edges,
orchestration, judge/experiments.

**21:30 WS4 network failure.** The first WS4 agent died on `ENOTFOUND` (API unreachable) before writing anything. It
was relaunched fresh at 21:33 ET.

**21:42 Merge WS2** (`e57a458`): résumé gate, fsio write policy, allow-list HTTP, privacy audit. Claude re-ran the gate
on main: 261 passed, 1 skipped.

**21:46 Merge WS3** (`138bcff`): state, status, sources, events, pipeline, report, CLI. Gate: 383 passed. `jsa doctor`
passed every check against the real résumé gate.

**21:50 Merge WS1** (`e867b51`): provider, four-gate rule, evidence validator. Gate: 758 passed; meta-test 3 passed.
- Wrong version A (title-only) was killed by 9 contract tests and B (substring counting) by 12.
- All five §13 hand checks reproduced exactly.
- `jsa rule --raw ... --id 8127182` gave NO_MATCH, failed gate SKILLS, evidence Java only.
- Location labels over the 734 hand-check postings were 335 US_BASED, 332 NON_US, 67 NOT_ESTABLISHED. Claude's earlier
  throwaway script gave 339/332/63; the difference is the `Tor`/`Toro` non-US entries added afterwards.

**21:52 Run 1, live baseline** (`30304b7`): `uv run jsa run --model-backend none` at clean commit `e867b51`.
- Status BASELINE: 736 fetched, 736 unique valid IDs, new 0, state saved.
- The board had 734 postings at 18:41 ET, so it had already changed.
- Raw sha256 `8f02cbe2…`. `verify-evidence` OK; `audit-privacy` 0 findings.
