# JS3: what is left for Shubham, in order

Claude built and ran everything that is not your judgment (2026-11-25, overnight, while you
slept, at your request). These are yours. `scripts/package_js3.sh` refuses to build the zip
while any `[Shubham` placeholder or the unsigned sign-off remains.

1. **Read and adopt `FILTER.md`.** It is Claude's draft (v0.1 → v0.3). Change any rule or number
   you disagree with (a change means a new row in §8 and re-running `filter` and `shortlist`), then
   change the status line to say you adopted it as v1.0, and commit.
2. **The reject audit (12 points; must be your own judgment).** Copy
   `experiments/js3/audit/hand_verdicts.template.json` to `hand_verdicts.json`. Open
   `docs/js3/audit/WORKSHEET.md` (78 postings, blind: no scores) and, for each, write `RELEVANT`,
   `NOT_RELEVANT` or `CANNOT_TELL` and a short reason. Fill `judged_by` and `judged_on`. Do not open
   `data/js3/audit/draw.json` or the filter run files before you finish. Commit the verdicts, then run
   `uv run python -m job_search_agent.js3 audit-report` and commit `docs/js3/audit/AUDIT_REPORT.md`.
   Then add two or three sentences to `docs/js3/AUDIT.md` §3 in your words: how many you judged the
   filter got wrong, and what you can honestly say from 40.
3. **Trust decisions.** In `docs/js3/TOOL_SERVER.md` §3 and §4, replace the two
   `[Shubham: confirm or change…]` lines with your decision and reason.
4. **Check two or three things yourself** and note what you ran: e.g. recompute one shortlisted
   posting's score by hand from FILTER.md §1; open the New Grad posting (8128744) and confirm the
   18-month sentence; read the Claude transcript `data/js3/mcp/claude-2026-11-25.jsonl`.
5. **README:** the sign-off (Checked / How / Not checked / Not claiming / Signed) and the driver's
   seat "why the judgment stays mine" column, in your words. Facts: `docs/js3/FACTS_FOR_SIGNOFF.md`.
6. **FRICTIONAL.md:** a JS3 section in your own voice, dated, with what you checked, accepted,
   changed or rejected from Claude, and commit links (the JS1 TA took points off for a log that
   read as compiled from the build log).
7. **SOURCES.md:** fill "What I wrote (JS3)".
8. Run `uv run pytest -q`, then `scripts/package_js3.sh`, then commit and push the course folder
   it prints, and submit the zip and the commit hash on Canvas. The due date was 2026-11-23.
