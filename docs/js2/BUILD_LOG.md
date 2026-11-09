# JS2 build log (factual, written by Claude)

What happened while Claude built JS2 on 2026-11-09 (ET, overnight; Shubham was away). Times are commit times from `git log`; work before a
commit happened in the minutes before it. Facts
and commits only. This is raw material for Shubham's `FRICTIONAL.md`, not a substitute for it:
the course AI policy says Claude must not invent his struggle or understanding.

| Time (ET) | What | Evidence |
|---|---|---|
| 02:51–03:00 | Read `CONTRACT.md`, the JS1 code and the JS2 assignment. Chose to build on JS1 (not the Reallocation Engine or Lectern). | — |
| before 03:03 | Probed the public APIs. Every nonexistent board answers 404 on all three systems tried (Greenhouse, Ashby, Lever). Found two wrong boards that answer **200**: `ashby/vercel` returns `{"jobs":[]}` (28 bytes), and `greenhouse/ramp` returns one stale posting ("Copy of Chief Legal Officer", "dublin"). | probe output in this session's transcript |
| before 03:03 | Picked boards by size so committed evidence stays small: Stripe (6.0 MB) and Figma (1.7 MB) on Greenhouse, Ramp (2.8 MB) and Linear (0.45 MB) on Ashby. Left out OpenAI on Ashby (13.6 MB) and Anthropic on Greenhouse (10.3 MB). Left out Lever (a third system) to keep the change small. | `config/watch.toml` |
| 03:03 | Wrote `GATE.md` v0.1 and the plan, committed before any JS2 code. | `f524c91` |
| 03:03–03:14 | Ashby IDs are UUIDs, but JS1's `PostingId` allowed only positive decimals. Widened it to decimal-or-lowercase-UUID; Greenhouse still requires integers. | `642f550` |
| 03:03–03:14 | Ashby fields mapped onto the rule's Greenhouse names, so the rule and the evidence validator did not change. Known cost: record paths cite the mapped view, not Ashby's field names (GATE §9). | `642f550` |
| 03:03–03:14 | Designing the fetcher showed GATE §3 counted redirect hops as requests, which the JS1 fetcher cannot do from outside. Wrote amendment A1 instead of quietly counting differently. | `0afcf05`, `e955298` |
| 03:14 | Claude mistake: grouped files wrongly into the first build commits (the Ashby commit lacked `models.py`). Reset the three unpushed commits and recommitted them (so their commit times are 03:14); checked that each commit imports. | `642f550`..`0afcf05` |
| 03:14 | **Live run 1.** Exit `INCOMPLETE`; the deliberate `ashby/linearapp` got a 404 and was not retried. | `43143ad`; `docs/js2/TRACE.md` |
| 03:14 | Claude mistake: a `cmd && pytest \| tail -1 && git commit` chain committed a red test, because the pipe's exit status was `tail`'s. Fixed in the next commit; used `set -o pipefail` afterwards. | `437946b` (red), `6fe3ec1` (fix) |
| 03:15–03:16 | Checked each careers page outside the agent (ramp.com/careers: `ashbyhq` 338 times, `greenhouse` 0). Wrote `checks/check_watch.py` and `checks/expectations.toml`. | `e54a26d` |
| 03:16 | **Wrong-board runs.** `greenhouse/ramp` ended `FINISHED` twice (`BASELINE`, then `SUCCESS_NO_NEW`). The independent check failed it on 3 checks. | `e8816e4`; `docs/js2/FINISHED_WRONG.md` |
| 03:17–03:18 | Wrote GATE A2 (a board below its floor is a failed board), then the test, committed red before any patch. | `b4582e7`, `affcbdd`, `docs/js2/review/red-before-patch.txt` |
| 03:18 | Sent the patch request to a fresh Claude Code subagent in an isolated worktree. A local plugin hook appended its own tool-usage block to that prompt; the request text itself is in `docs/js2/review/PROMPT.md`. | `4f22eec` |

## Things that are still open

- `test_floor_must_be_positive` passed before the patch for the wrong reason (the plan refused
  every extra key). It discriminates only after the patch.
- The 94dd41a commit (policy and boundary tests) imports `reset_board` from `watch.py`, which
  arrives one commit later, so the tests do not run on that single commit. Every later commit
  runs.
- No live retry happened in any run; retries are shown only by constructed tests.
