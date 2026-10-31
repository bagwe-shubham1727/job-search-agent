# Prompt experiment: generated tables

Changed section (v1 to v2): `label_definition`. First reply only; no retries. Format acceptance is the validator pass rate, not accuracy. Brackets are Wilson 95% intervals.

| Cell | Format acceptance | Agreement (invalid = disagree) | Agreement among valid | Evidence entries valid | Replies with a bad path |
|---|---|---|---|---|---|
| v1-dev | 10/10 [0.72, 1.00] | 7/10 [0.40, 0.89] | 7/10 [0.40, 0.89] | 49/49 | 0 |
| v2-dev | 10/10 [0.72, 1.00] | 10/10 [0.72, 1.00] | 10/10 [0.72, 1.00] | 41/41 | 0 |
| v1-heldout | 10/10 [0.72, 1.00] | 6/10 [0.31, 0.83] | 6/10 [0.31, 0.83] | 45/45 | 0 |
| v2-heldout | 10/10 [0.72, 1.00] | 10/10 [0.72, 1.00] | 10/10 [0.72, 1.00] | 47/47 | 0 |

## Confusion matrices (rows: hand label; columns: Claude)

### v1-dev

| hand \ Claude | MATCH | NO_MATCH | INVALID |
|---|---|---|---|
| MATCH | 1 | 3 | 0 |
| NO_MATCH | 0 | 6 | 0 |

### v2-dev

| hand \ Claude | MATCH | NO_MATCH | INVALID |
|---|---|---|---|
| MATCH | 4 | 0 | 0 |
| NO_MATCH | 0 | 6 | 0 |

### v1-heldout

| hand \ Claude | MATCH | NO_MATCH | INVALID |
|---|---|---|---|
| MATCH | 0 | 4 | 0 |
| NO_MATCH | 0 | 6 | 0 |

### v2-heldout

| hand \ Claude | MATCH | NO_MATCH | INVALID |
|---|---|---|---|
| MATCH | 4 | 0 | 0 |
| NO_MATCH | 0 | 6 | 0 |

## v1 vs v2 discordant postings

- dev: 8197135 (M; v1 NO_MATCH, v2 MATCH), 8197891 (M; v1 NO_MATCH, v2 MATCH), 8198280 (M; v1 NO_MATCH, v2 MATCH)
- heldout: 8039548 (M; v1 NO_MATCH, v2 MATCH), 8206731 (M; v1 NO_MATCH, v2 MATCH), 8267736 (M; v1 NO_MATCH, v2 MATCH), 8332676 (M; v1 NO_MATCH, v2 MATCH)

## Rule vs hand audit

- dev: none
- heldout: none

## Limits

- n = 10 per cell: one posting moves a rate by 10 points.
- One call per cell ignores the sampling variance measured in the sampling report.
- Both sets come from one board on one day.
- The stratified mix is not the board's base rate.

## Rule-vs-hand decisions (labeling slip or rule bug)

<!-- STUDENT WRITES THIS -->

## Conclusion

<!-- STUDENT WRITES THIS -->
