# What moves the score (JS3, Chapter 9)

## 1. Where every number came from

"Hand-set" means someone chose it by reasoning, with no labels involved. "Fitted" means it was
chosen because it scored better on labelled data. "Inherited" means it was carried over from an
earlier layer unchanged.

| Number or object | Value | Where it lives | Origin |
|---|---|---|---|
| R1 role phrase | +4 | FILTER.md §1 | Hand-set (Claude, v0.1). The phrases themselves are inherited from CONTRACT §6.1 (Shubham, JS1) |
| R2 generic word | +2, words "engineer", "developer" | FILTER.md §1 | Hand-set (Claude, v0.1) |
| R2 blockers | 14 specialty words | FILTER.md §1 | Hand-set (Claude, v0.3) after counting which kept postings R2 produced, on **unlabelled** corpus data. Not fitted: no label was consulted |
| R3 seniority | −10, 13 markers | FILTER.md §1 | Weight hand-set; marker list inherited from CONTRACT §6.1 |
| R4 skills | +1 each, cap 3 | FILTER.md §1 | Hand-set. The skill list is inherited (persona résumé, CONTRACT §4); the matching rules inherited (CONTRACT §6.2) |
| R5 topic | +1, 10 words (12 in v0.1) | FILTER.md §1 | Hand-set; "api"/"apis" cut in v0.2 after counting matches on unlabelled corpus data |
| R6 location | +1 / 0 / −10 | FILTER.md §1 | Weights hand-set; the US and non-US signal lists inherited from CONTRACT §6.4 |
| R7 exclusion | −10, 11 phrases | FILTER.md §1 | Weight hand-set; phrases inherited from CONTRACT §6.3 |
| Threshold | 7 | FILTER.md §1 | Hand-set to reproduce the CONTRACT §6.5 bar (role + 2 skills + US); the "2 skills" is inherited from CONTRACT §6.5 |
| Kiran's years (C4) | 4 | `claims.py` `KIRAN_YEARS` | Computed by hand from the persona's experience dates (52 months) |
| Short-text cut-off | 200 characters | `claims.py` `MIN_CONTENT_CHARS` | Hand-set |
| Judge prompt | `prompts/judge.v2.md` | JS1 | **Fitted**: chosen over v1 on the 10 JS1 dev labels (dev 7/10 → 10/10), then confirmed on held-out (6/10 → 10/10). The only number-like object in the system chosen on labels |
| Model | `claude-sonnet-5-5` | `config/agent.toml` | Inherited from JS1 |
| Judge timeout | 180 s | `config/agent.toml` | Inherited from JS1 |
| Audit seed and sizes | 20261125; 40 / 8 / 8 / 12 | FILTER.md §5, `audit.py` | Hand-set, pre-registered |
| Interval level | 95% exact (Clopper–Pearson) | `audit.py` | Convention |
| E3 truncation | 1,500 characters | `experiments.py` | Hand-set for this experiment |

## 2. The changes, one object at a time (predictions written before any run)

Held-out labels: the 10 JS1 held-out labels (Shubham, 2026-10-30), on the postings exactly as
labelled (the 2026-10-29 hand-check raw). The 15 JS1 tuning labels (dev 10 + sampling 5) are
reported beside them but are not the test. A label `MATCH` counts as relevant; the filter's
"kept" is compared with it.

| ID | Object | One change | Prediction (before running) |
|---|---|---|---|
| E1a | the filter file | v0.1 → v0.2: cut "api", "apis" from R5 | No held-out decision changes: the held-out postings are mostly role-phrase titles that get R5 from other words, and the cut flipped only generic-title specialty jobs on the corpus |
| E1b | the filter file | v0.2 → v0.3: add the R2 blockers | At most one held-out decision changes (the held-out set has a stratum of title-fail postings, which is where blockers act) |
| E2 | a setting | threshold 7 → 6 on v0.3 | Agreement stays the same or falls by 1–2: a lower bar can only add kept postings, and every extra one is a NO_MATCH under the CONTRACT rule unless it has a role phrase, two skills and a US location |
| E3 | the context given to Claude | judge v2 with the posting content whole vs cut to its first 1,500 characters | Agreement falls from about 10/10 to 7–9/10, and the misses are MATCH postings judged NOT_RELEVANT, because the skills a posting lists sit in its later "what you'll need" section |

Each E3 condition runs once (one `claude` call per held-out posting, no retry), from an empty
directory with no tools, through the JS1 judge path.

## 3. Results

Pending: filled in from `data/js3/experiments/` after the runs.

## 4. What persistence is not proof of

Pending.
