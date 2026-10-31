# Sampling report: generated tables

**Repeatable is not correct.** A label Claude gives every time can still disagree with the hand label; such rows are marked *unanimous and wrong*.

Prompt `judge.v1` (sha256 `2da84890daded0ba…`), model requested `claude-sonnet-5-5`, served `claude-sonnet-5-5`. 20 calls, 4 per posting, first reply only, every session ID distinct (0 call(s) had no session ID).

Hand labels are the CONTRACT.md §13 verdicts; confirmed by the student: Shubham Bagwe (2026-10-30).

| Posting | Hand | n | RELEVANT | NOT_RELEVANT | INVALID | Modal | Unanimous | Agreement k/n | Distinct evidence-path sets | First-reply format acceptance |
|---|---|---|---|---|---|---|---|---|---|---|
| 8249901 | MATCH | 4 | 0 | 4 | 0 | NO_MATCH | yes (unanimous and wrong) | 0/4 | 4 | 4/4 |
| 7543868 | NO_MATCH | 4 | 0 | 4 | 0 | NO_MATCH | yes | 4/4 | 4 | 4/4 |
| 8175099 | NO_MATCH | 4 | 0 | 4 | 0 | NO_MATCH | yes | 4/4 | 4 | 4/4 |
| 8127182 | NO_MATCH | 4 | 0 | 4 | 0 | NO_MATCH | yes | 4/4 | 3 | 4/4 |
| 8234357 | NO_MATCH | 4 | 1 | 3 | 0 | NO_MATCH | no | 3/4 | 4 | 4/4 |

Unanimous and wrong: 8249901.

All replies INVALID (a format or outage case, not a wrong label): none.

## Conclusion

<!-- STUDENT WRITES THIS -->
