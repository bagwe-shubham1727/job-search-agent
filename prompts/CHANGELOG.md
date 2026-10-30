# Prompt contract change log

Each version of the judge prompt is a separate file, `prompts/judge.<version>.md`.
A version is never edited after its first model call. The SHA-256 of each file is
recorded in every raw-reply log entry, and `jsa exp prompt freeze` records the v1 and
v2 digests in `data/experiments/prompt/FREEZE.json`.

## judge.v1 (2026-10-29)

- Drafted by Claude (WS4 coding agent) on 2026-10-29 from PLAN.md §5.3 and
  CONTRACT.md §8. Not yet reviewed by the student.
- Sections: `role`, `task`, `label_definition`, `output_schema`, `path_rules`,
  `uncertainty_rules`, `untrusted_input`, `inputs`.
- `label_definition` is deliberately general: "RELEVANT if, based only on the supplied
  text, the posting is worth Kiran considering given the résumé's target roles, levels,
  locations, exclusions and skills; otherwise NOT_RELEVANT." It does not restate the
  §6 rule. This is the baseline the prompt experiment measures.
- Used by the JS1 pipeline runs, the sampling report (Chapter 1) and the v1 arms of the
  prompt experiment (Chapter 2).

## Pre-registered candidates for the single v2 change

Written down before the v1 dev run, so the choice cannot be fitted to the results
after the fact. v2 changes exactly one marked section of v1. `freeze` checks this
mechanically and refuses a diff that touches more than one section.

1. **Recommended by the plan: replace only `label_definition`** with the contract's
   §6.5 four-gate definition in plain language: the title family plus the seniority
   marker list; at least two distinct skills from the listed skill arrays, excluding
   `familiar_with_not_shipped`; none of the three exclusion phrase families; and
   location established as US-based from `location.name`, with mixed or unknown not
   counting. The variable that changes is "what RELEVANT means". §16 says the
   experiment measures agreement with the written rule, and v1's general definition is
   the most likely source of disagreement.
2. **Add one sentence to `label_definition`** saying only that the location must be
   established as US-based. This is the purest single-criterion change; use it if
   candidate 1 is judged to be several changes at once.
3. **Add one worked example of a valid reply to `output_schema`.** This targets format
   acceptance, not agreement.

Rejected before the run: `--json-schema` (an interface change, not a prompt change)
and model or temperature changes (there is no such flag, and neither is a prompt
change).

## Choice of the v2 change

**The student chooses** which candidate becomes v2, after seeing the v1 dev results
and before any v2 call. The choice, the rationale and the date are recorded here by
the student. `judge.v2.md` does not exist until then.

### Which candidate and why

<!-- STUDENT WRITES THIS -->
