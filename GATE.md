# GATE.md — Job-Search Agent 2: the loop, the tools, and the diff

**Version:** v0.1, 2026-11-09, written before any JS2 code.
**Persona:** Kiran Joshi (fictional), the same as in `CONTRACT.md`.
**Authorship:** Claude Code drafted this file from `CONTRACT.md` and Shubham's request on
2026-11-09, before writing any JS2 code. Shubham reviews it, changes what he disagrees with,
and adopts it as v1.0. Until then it is a draft (see `SOURCES.md`).

`CONTRACT.md` still governs one board: the rule, the records, the run statuses and the state.
This file governs the loop that runs that one-board pass over several boards.

## 1. What the loop is

`jsa watch` reads a plan (`config/watch.toml`), then for each planned board, in order:
checks the budget, fetches the board once through the permission policy (with at most one
retry), and runs the JS1 pass on it (`pipeline.run_once`: rule, records, state). Each board has
its own state folder `data/watch/boards/<provider>-<token>/`. The loop records every
observation in `data/watch/loops/<loop_id>/trace.jsonl` and ends with exactly one exit
status, written to `report.json` and `report.md` beside the trace.

The loop does not call Claude. Its model backend is `none`, so every new posting's judgment is
`UNAVAILABLE` and stays pending (CONTRACT §10). `jsa run` stays the judging path for Stripe.

## 2. Exits

Every run of the loop ends in exactly one of these. A loop that stopped did not
necessarily succeed: only `FINISHED` means every planned board was checked.

| Exit | When | What it reports | Exit code |
|---|---|---|---|
| `FINISHED` | Every planned board was attempted and every one is OK (below) | Per-board status, fetched count, new count, pending count; total requests and seconds used | 0 |
| `INCOMPLETE` | Every planned board was attempted, at least one failed, at least one is OK | The same, plus each failed board with its status, HTTP status and error kind, marked for Shubham's attention | 8 |
| `BUDGET_EXHAUSTED` | A budget (§3) stopped the loop before every board was attempted | Which budget ran out, the boards done, and the boards **not attempted** (never reported as checked) | 9 |
| `ERROR` | The loop could not do its job: the policy refused the plan before any fetch, a board's state is corrupt or locked, or no attempted board was OK | The reason code; nothing is reported as checked | 10 |

**A board is OK** when its JS1 status is `BASELINE`, `SUCCESS_WITH_NEW` or `SUCCESS_NO_NEW`, or
when it is `PARTIAL_FAILURE` only because judgments were deferred: every judgment is
`UNAVAILABLE`, the backend is `none`, and the notes are only `judgments_not_valid`,
`pending_unresolved` and `judge_unavailable`. Any other `PARTIAL_FAILURE`, and every
`FETCH_FAILED`, `INVALID_RESPONSE` and `EMPTY_RESPONSE`, is a **failed board**.

An empty board is a failed board. "No jobs came back" is not "no new jobs" (CONTRACT §15).

**Precedence** when more than one applies: `ERROR`, then `BUDGET_EXHAUSTED`, then
`INCOMPLETE`, then `FINISHED`.

## 3. Budgets

Per loop run, from `config/watch.toml`:

| Budget | Value | Checked |
|---|---:|---|
| `max_boards` (boards attempted) | 6 | Before starting each board |
| `max_requests` (GET attempts sent; see amendment A1) | 10 | Before every attempt |
| `max_seconds` (wall time from loop start) | 180 | Before each board and each retry; each request's timeout is the smaller of 30 s and the time left |

A request already in flight is bounded by its own timeout, so the loop can overrun
`max_seconds` by at most that timeout plus the time to finish the board it is on.

**Who may change a budget:** only Shubham, and only by a new dated entry in §10 of this file
that gives the new value and the reason, committed before the run that uses it. The agent
cannot change one: `config/` is outside its write folder (§6).

## 4. Repeat rule

- **The same board** is the same provider plus the same token after trimming and lowercasing
  (`Stripe` and ` stripe` are `stripe`). The loop fetches a board at most once per run. A later
  plan entry for a board already in the plan is recorded as `SKIPPED_REPEAT`, is not
  fetched, and does not count against `max_boards`.
- **The same action** is a GET of the same URL in the same loop run. The only allowed second
  GET of a URL is the one retry in §5. Any further GET of that URL is refused by the fetcher
  and recorded as `repeat_refused`.
- **Across runs**, running the loop again is a new decision by Shubham, not a repeat. Postings
  are de-duplicated by the per-board seen-ID state (CONTRACT §10).

## 5. Error policy

| Failure on a board | Retry? | Why | Then |
|---|---|---|---|
| Timeout, connection/DNS/TLS error, HTTP 500–599 | **Once**, after a 2 s pause, only if a request and at least 5 s remain | The request is a read-only GET, so repeating it changes nothing on the server; these failures are often momentary; one retry costs one request and stays polite | If the retry also fails: the board is `FETCH_FAILED`, the loop moves on |
| HTTP 404 or any other 4xx (bad board name) | No | Asking again for a board that does not exist gives the same answer | `FETCH_FAILED` with the HTTP status; the loop moves on |
| HTTP 429 | No | The site asked us to slow down; respecting rate limits is a refusal in CONTRACT §12 | `FETCH_FAILED`; moves on |
| Host or redirect refused by the policy, size cap, too many redirects | No | A policy refusal is not a transient fault | `FETCH_FAILED`; moves on |
| Response not JSON or wrong shape | No | The bytes will not change by asking again within seconds | `INVALID_RESPONSE`; moves on |
| Empty `jobs` array | No | Same | `EMPTY_RESPONSE` (a failed board); moves on |
| A board's state file is corrupt, or its lock is held | No | Continuing would risk the saved state | The loop stops: `ERROR` |

The loop never invents a value for a failed board: no posting count, no "0 new". A failed
board's state is never written (CONTRACT §10), and its saved response (if any bytes came back)
is kept as evidence.

**Escalation to Shubham:** every failed board is listed under "Needs your attention" in
`report.md`, and the exit code is non-zero. The loop never repairs a plan or a state file on its
own.

## 6. Permission policy

Enforced in the program (`src/job_search_agent/policy.py` and the fetcher and writer that call
it), not in a prompt. The loop has no model in it, so no instruction can talk it out of these.

**Hosts.** The loop's requests may reach only `boards-api.greenhouse.io` and
`api.ashbyhq.com`: exact host match, HTTPS, port 443, no user name or password in the URL, GET
only. Every redirect hop is checked again. Links inside job descriptions are never followed.

**Reads.** Inside the project folder only. Never `private/`, `.env` files, or anything outside
the project (resolved through symlinks).

**Writes.** Inside `data/watch/` only, resolved through symlinks, so `..`, a sibling with the
same prefix (`data/watch-evil/`) and a symlink that points out are all refused. Everything else
is refused, including `config/` (budgets and the plan), `GATE.md`, the source code and JS1's
`data/live/` state.

**Needs Shubham's approval.** Deleting anything under `data/watch/`. The only delete is
`jsa watch reset <provider>/<token>`, which clears one board's saved state so its next run is a
fresh baseline. It asks on a terminal and proceeds only if Shubham types the board key; with
no terminal it is refused.

**Never**, with or without approval: apply for a job, email, message, log in, send any
request other than GET, follow a link from a posting, or change a budget or the plan.

## 7. Boundary cases and predictions (written before the tests run)

| # | Request | Predicted result |
|---|---|---|
| B01 | GET `https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true` | ALLOW |
| B02 | GET `https://api.ashbyhq.com/posting-api/job-board/ramp` | ALLOW |
| B03 | GET `https://jobs.lever.co/palantir` (host off the allow-list) | DENY `host` |
| B04 | GET `https://boards-api.greenhouse.io.evil.example/` (allowed name as a prefix) | DENY `host` |
| B05 | GET `http://boards-api.greenhouse.io/...` (plain HTTP) | DENY `scheme` |
| B06 | POST `https://boards-api.greenhouse.io/v1/boards/stripe/jobs/1` (the apply endpoint, allowed host) | DENY `method` |
| B07 | An allowed host answers with a redirect to `https://evil.example/` | Request refused at the hop, board `FETCH_FAILED` (`REDIRECT_REJECTED`) |
| B08 | Write `data/watch/loops/x/trace.jsonl` | ALLOW |
| B09 | Write `data/watch/../live/state.json` (`..`) | DENY `outside_write_root` |
| B10 | Write `data/watch-evil/x.json` (prefix trick) | DENY `outside_write_root` |
| B11 | Write `data/watch/link/x.json` where `link` is a symlink to a folder outside the project | DENY `outside_write_root` |
| B12 | Read `config/watch.toml` | ALLOW |
| B13 | Write `config/watch.toml` (same file as B12) | DENY `outside_write_root` |
| B14 | Read `private/real.resume.json` | DENY `private` |
| B15 | Read `/etc/hosts` (outside the project) | DENY `outside_project` |
| B16 | Delete `data/watch/boards/greenhouse-ramp/live/state.json` | NEEDS_APPROVAL |
| B17 | B16 with approval refused, or with no terminal | Nothing deleted; DENY `not_approved` |
| B18 | B16 with Shubham typing the board key | ALLOW; the file is deleted |
| B19 | Action `apply` (likewise `email`, `message`, `login`) | DENY `never`, even with approval |
| B20 | A third GET of the same URL in one loop run | DENY `repeat` |

## 8. Wrong versions the tests must catch

Each is plausible and wrong. `tests/meta/test_js2_wrong_versions_caught.py` swaps each one in
and requires the JS2 tests to fail.

| # | Wrong version | Why it is wrong |
|---|---|---|
| W1 | Reports `FINISHED` when a board failed | A loop that stopped is reported as a loop that succeeded |
| W2 | Treats an `EMPTY_RESPONSE` board as OK | An empty board becomes "no new jobs" |
| W3 | Retries every failure (a 404, a 429) | Retries a permanent answer and ignores the site's rate limit |
| W4 | Checks the request budget after sending | Sends one request more than `max_requests` |
| W5 | Write check by string prefix (`str(path).startswith(str(root))`) | `data/watch-evil/` passes |
| W6 | Write check without resolving symlinks | A symlink inside `data/watch/` that points out passes |
| W7 | Host check by suffix or substring | `boards-api.greenhouse.io.evil.example` or `evilgreenhouse.io` passes |
| W8 | Case-sensitive repeat key | `Stripe` and `stripe` are fetched twice |
| W9 | Delete without asking when there is no terminal | An unapproved delete happens in a script |

## 9. The second job-board system

Ashby's public posting API (`https://api.ashbyhq.com/posting-api/job-board/<name>`) returns
`{"jobs": [...], "apiVersion": ...}`. Its IDs are UUIDs, so `PostingId` accepts a lowercase UUID
as well as a positive decimal. Each Ashby job is mapped onto the field names the CONTRACT §6
rule reads, so the rule and its evidence validator do not change:

| Rule path | Ashby field |
|---|---|
| `$.title` | `title` |
| `$.content` | `descriptionHtml` (plain HTML, not entity-escaped; the same cleanup is safe on it) |
| `$.location.name` | `location` |
| `$.departments[0].name`, `$.departments[1].name` | `department`, `team` |
| `$.updated_at` | `publishedAt` |

A record's posting paths therefore name the mapped view, not Ashby's own field names. The saved
raw bytes keep Ashby's names; this table is the key between them.

## 10. Amendments

Each amendment is dated, says what changed and why, and is committed before the code or run
that depends on it.

**A1 (2026-11-09, written while designing the fetcher; committed with the loop code in 0afcf05).** A request is one GET attempt. Redirect hops inside
one attempt are recorded in the trace but are bounded by `http.max_redirects` (3), not by
`max_requests`. Reason: the JS1 fetcher follows redirects inside one call, so counting hops
against the budget would mean putting the budget inside the transport. None of the planned
boards redirects. Drafted by Claude while designing the fetcher; for Shubham to accept.
