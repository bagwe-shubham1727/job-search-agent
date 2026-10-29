# CONTRACT.md — Job Search Agent

**Written:** October 29, 2026  
**Persona:** Kiran Joshi (fictional)  
**Board:** Stripe on Greenhouse

## What this agent does

This agent checks one public job board, remembers which posting IDs it has already seen, and evaluates newly discovered jobs against Kiran Joshi's fictional résumé. It produces a rule-based result and a separate Claude judgment. The two results must stay separate: the rule is reproducible, while Claude's answer is an opinion based on the available text.

The agent is for job discovery only. It will not apply for jobs, contact employers, log in to job sites, or claim that a job is a guaranteed fit.

## 1. Persona and résumé

Kiran Joshi is a fictional early-career software engineer. The supplied résumé says `"fictional": true`; the names, employers, schools, dates, projects, and contact details are invented. The agent uses the exact fixture at:

`persona/kiran-joshi.resume.example.json`

Kiran's target roles are Software Engineer, Full-Stack Software Engineer, Backend Engineer, and Frontend Engineer. The target levels are New Grad, Entry Level, SWE I, and SWE II. The résumé includes professional and project experience with TypeScript, JavaScript, Java, Python, SQL, C#, React, Next.js, Node.js, Express, Spring Boot, PostgreSQL, MongoDB, Redis, Elasticsearch, RabbitMQ, Kafka, AWS, GCP, Docker, Kubernetes, GitHub Actions, Sentry, Prometheus, and Grafana. Go and Terraform are explicitly listed as familiar with but not shipped, so they do not count toward the primary skill threshold.

## 2. Board

I am using Stripe's public Greenhouse board.

- Board identifier: `stripe`
- Public board: `https://boards.greenhouse.io/stripe`
- API endpoint: `https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true`
- Automated job-board host: `boards-api.greenhouse.io`

I chose Stripe because the title and skill rule has a mix of matches and non-matches on this board, making it possible to test both outcomes. The board changes over time, so the agent must use the response it actually fetches and must not hard-code a posting count.

Stripe does not always include the word “Senior” in titles. Therefore, the title filter will not catch every senior-level job. This is a known limitation; the agent must not claim that every returned match is definitely entry-level.

## 3. Inputs and requirements

The agent needs:

1. Board identifier `stripe`.
2. The approved résumé fixture at `persona/kiran-joshi.resume.example.json`.
3. A local state file holding previously seen posting IDs and any pending model judgments.
4. HTTPS network access to the Greenhouse API.
5. A Claude subscription and an officially supported way to use it from the environment, such as Claude Code if available.

A Claude subscription is not the same as Anthropic API access and does not automatically provide an API key. The contract does not require an Anthropic API key. If the subscription cannot be used through an officially supported interface in this environment, the rule step still runs and the model judgment is marked unavailable; the agent must not pretend a model call happened.

The résumé path and state path should be configurable. The state file must be stored inside the configured project data directory. The agent must validate the résumé before sending any résumé content to a model.

## 4. Résumé fields used by the rule

The rule reads these résumé JSON paths:

- `$.target.roles[*]`
- `$.target.levels[*]`
- `$.target.excluded[*]`
- `$.skills.languages[*]`
- `$.skills.frontend[*]`
- `$.skills.backend[*]`
- `$.skills.data[*]`
- `$.skills.messaging[*]`
- `$.skills.cloud_devops[*]`
- `$.skills.observability[*]`

The rule does not read `$.target.locations[*]`; location is reported to Claude as context, not used to decide the deterministic label. It also does not count `$.skills.familiar_with_not_shipped[*]`.

The rule does not use the persona's name, contact details, school names, employer names, or dates as matching signals. Claude may use Kiran's experience and project bullets for its qualitative judgment, but those fields do not alter the rule verdict.

The target role phrases are taken from `$.target.roles[*]`, not from a separate hard-coded role list. The implementation may use documented aliases for common title variants, as defined below.

## 5. Posting fields used by the agent

The agent reads these fields from the Greenhouse response:

- `id` — stable posting identifier used for deduplication
- `title` — role-title check
- `location.name` — location reported in the output and given to Claude as context
- `updated_at` — metadata only; it does not decide whether a posting is new
- `content` — job description and requirements
- `departments[*].name` — additional text, if present

The request uses `?content=true`. Before implementation, I will inspect one raw response and confirm the exact response shape. A missing optional field contributes an empty value. A missing or invalid posting ID is a data-quality error and must be reported rather than replaced with an invented ID.

Greenhouse's `content` field may contain HTML that has been escaped into text. Before matching, the agent must decode HTML entities, strip HTML tags, and normalize whitespace. Matching still cites the original source path, such as `$.content`; it must not invent a JSON path for the cleaned text. The cleaned text is only an in-memory representation used for matching.

## 6. Deterministic rule

I want a classmate to be able to apply this rule by hand and reach the same result.

### 6.1 Title check

The title is lowercased and trimmed. The following title aliases count as the same role family:

- `software engineer` matches the role `Software Engineer`
- `full-stack`, `full stack`, and `fullstack` match `Full-Stack Software Engineer`
- `backend`, `back-end`, and `back end` match `Backend Engineer`
- `frontend`, `front-end`, and `front end` match `Frontend Engineer`

The title must contain both the role family and the word `engineer` (or a documented equivalent title phrase): `software engineer`, `full-stack engineer`, `backend engineer`, or `frontend engineer`. The aliases only normalize the family word, not the job itself: `backend`, `back-end`, or `back end` count only in a title phrase such as `Backend Engineer`, `Back-End Software Engineer`, or `Back End Engineer`; `frontend`, `front-end`, and `front end` count only in phrases such as `Frontend Engineer`, `Front-End Software Engineer`, or `Front End Engineer`. `Backend Data Analyst` and `Frontend Designer` do not pass. “Software Engineering” by itself does not count as “Software Engineer.” “Software Engineering Internship” is excluded. The word `intern` and the word `internship` both cause rejection.

The title exclusions implement the intent of `$.target.levels[*]` and `$.target.excluded[*]`: they are a fixed, documented interpretation of those fields for this version, not a runtime parser that dynamically converts every phrase in those arrays into a new rule. The title is rejected if it contains any of these markers as a whole word or defined abbreviation: `senior`, `sr`, `sr.`, `staff`, `principal`, `lead`, `manager`, `director`, `intern`, `internship`, `III`, `IV`, `L3`, or `L4`. `SWE I` and `SWE II` are allowed. Because Kiran's listed target levels stop at SWE II, titles marked III, IV, L3, or L4 are excluded. This is a simple title heuristic and will miss senior jobs whose titles omit a seniority marker.

### 6.2 Skill check and special cases

The eligible skill set comes from the résumé paths in section 4. Each distinct skill counts at most once, no matter how many times it appears in the posting. Matching is case-insensitive.

The agent must decode escaped HTML and strip tags before searching. It must not treat punctuation removal as the only normalization rule, because that would make `C#` become a stray `c` and create false matches.

Use these matching rules:

- `C#` matches the exact token `C#`; it must not match the letter `c` by itself.
- `Node.js` matches `Node.js` or `NodeJS`, case-insensitively.
- `Next.js` matches `Next.js` or `NextJS`.
- `React` counts only when written as `React`, `React.js`, or `ReactJS` with the technology name's capitalization preserved in the source. A lowercase plain-English “react” does not count. A sentence-initial “React” can still be a false positive (for example, “React quickly to incidents”) because the rule cannot reliably infer grammar from capitalization alone; this is a known limitation.
- `Express` counts only as `Express.js`, `ExpressJS`, or in the phrase `Express framework`; a plain-English “express interest” does not count.
- `REST` counts only in phrases such as `REST API`, `RESTful API`, or `REST services`; a plain-English “the rest of the team” does not count.
- `Front End`, `Front-End`, and `Frontend` are equivalent for the title check, but are not automatically treated as a résumé skill.
- Other skills use case-insensitive whole-word matching after HTML cleanup. Multiword skills must appear as consecutive words.

For the `React`, `Express`, and `REST` special cases, capitalization and context are part of the rule. This avoids counting common English words as technologies. If the source does not contain the required technology form, that skill does not count.

### 6.3 Explicit exclusions

The rule also checks the posting text for these explicit exclusion phrases:

- U.S. citizenship: `must be a U.S. citizen`, `U.S. citizens only`, `United States citizens only`, or `citizenship required`
- Security clearance: `security clearance required`, `active clearance required`, or `must hold a clearance`
- Unpaid work: `unpaid position`, `unpaid role`, `unpaid internship`, or `this is an unpaid opportunity`

These checks implement the intent of `$.target.excluded[*]` using the exact phrase list below; the agent does not dynamically interpret arbitrary new prose in that résumé field. They are case-insensitive after HTML cleanup. The agent does not infer an exclusion from silence or from ambiguous wording. This is a literal phrase list, not a general legal interpretation.

### 6.4 Final verdict

A posting is `MATCH` if and only if all three conditions are true:

1. Its title matches one of the role families derived from `$.target.roles[*]` and passes the title exclusions.
2. At least two distinct eligible résumé skills match the cleaned posting title, content, or department text.
3. None of the explicit exclusion phrases in section 6.3 appears in the cleaned posting text.

Otherwise the verdict is `NO_MATCH`.

Missing optional fields contribute no text. Missing location alone does not cause rejection. The rule does not guess whether an employer sponsors a work visa. Sponsorship and location suitability are left to Claude's separate judgment and must be described as uncertain if the posting does not say.

## 7. Output format and evidence

For each new posting, the agent writes one JSON record with this shape:

```json
{
  "posting_id": "123456",
  "title": "Software Engineer",
  "location": "Boston, MA",
  "updated_at": null,
  "rule_verdict": {
    "label": "MATCH",
    "evidence": [
      {
        "term": "TypeScript",
        "resume_path": "$.skills.languages[0]",
        "posting_path": "$.content"
      },
      {
        "term": "Node.js",
        "resume_path": "$.skills.backend[0]",
        "posting_path": "$.content"
      }
    ],
    "reason": "The title passes the role check and two distinct résumé skills appear in the posting."
  },
  "model_judgment": {
    "status": "VALID",
    "label": "RELEVANT",
    "summary": "The role appears worth reviewing based on the supplied evidence.",
    "evidence": [
      {
        "resume_path": "$.experience[0].bullets[0]",
        "posting_path": "$.content",
        "reason": "The résumé describes relevant shipped experience that relates to the posting description."
      }
    ],
    "uncertainties": ["The posting does not state whether sponsorship is available."]
  }
}
```

The example is only a schema illustration; the posting ID and values are not a claim about a verified live vacancy.

For each rule verdict, `evidence` is an array with one entry per distinct matched skill. Every entry must pair exactly one `term`, one `resume_path`, and one `posting_path`; this makes it unambiguous which résumé skill was found in which posting field. The résumé path must point to the skill value that matches `term`, and the posting path must point to the original raw field containing that match. Valid posting paths include `$.title`, `$.content`, and `$.departments[0].name`. The validator checks that both paths exist and that the cited term is actually supported by their values after the specified cleanup and normalization.

For a `NO_MATCH`, the record still lists any skill evidence that did match and explains which gate failed. It must not claim a skill matched without a complete evidence entry.

The `model_judgment` fields must also cite evidence. `resume_fields` and `posting_fields` are arrays of JSON paths supporting the model's judgment. Every path must exist in the actual input objects. If any cited path is missing or invalid, the judgment is rejected by the validator.

## 8. Claude judgment format and validation

Claude's judgment uses a fixed JSON format with exactly these keys and no others:

```json
{
  "label": "RELEVANT",
  "summary": "A short explanation of the assessment.",
  "evidence": [
    {
      "resume_path": "$.skills.backend[0]",
      "posting_path": "$.content",
      "reason": "The posting mentions a technology listed in Kiran's résumé."
    }
  ],
  "uncertainties": ["Sponsorship policy is not stated."]
}
```

`label` must be exactly `RELEVANT` or `NOT_RELEVANT`. This makes the model result comparable with the hand labels in the prompt experiment. It is still a model judgment, not a verified fact. `RELEVANT` means Claude thinks the posting is worth considering; it does not mean Kiran is qualified for certain or will get an interview.

The validator rejects a reply if it is not valid JSON, has any text before or after the JSON object, is wrapped in Markdown code fences (including ```json fences), has missing keys, has extra keys, uses a label other than the two allowed values, gives a field the wrong type, or cites a résumé/posting path that does not exist. Arrays must have the exact types defined by the schema. `summary` must be a string. `uncertainties` may be an empty array but must always be present. Every evidence entry must pair a real résumé path with a real posting path and a short reason.

The agent may retry one time after a validation failure, using the same schema instructions. It must not silently repair or reinterpret an invalid reply. The sampling report records and scores the first reply before any retry, so retry behavior does not hide the model's initial formatting or judgment variation. If the second reply is invalid, it records `model_judgment.status` as `INVALID_OUTPUT`, keeps the raw reply in a separate diagnostic field or local diagnostic log, and does not treat it as a valid label. The raw reply must not be allowed to overwrite the structured output. If no model call can be made, the status is `UNAVAILABLE`; if a call fails after being attempted, the status is `ERROR`.

Claude's evidence paths must be real paths in the supplied résumé and posting. A path that looks plausible but does not exist is a validation failure.

## 9. Baseline and run statuses

The first successful, valid fetch is a baseline, not a run that reports every posting as new. Its status is `BASELINE`. It reports the number of postings fetched, the number of valid unique IDs seen, `new_count: 0`, and whether the state was saved. The All IDs from the baseline are stored as seen, but the baseline still reports `new_count: 0`. IDs are retained cumulatively so a posting that disappears and later reappears is not treated as new again. No postings receive new-posting judgments on the baseline run.

On later runs, a posting is new only if its ID is not in the state from the last successful fetch. The run report must distinguish:

- `SUCCESS_WITH_NEW` — fetch and validation succeeded and new IDs were found
- `SUCCESS_NO_NEW` — fetch and validation succeeded and no new IDs were found
- `FETCH_FAILED` — the request failed or returned an unsuccessful HTTP status
- `EMPTY_RESPONSE` — the request succeeded but the postings array was empty
- `INVALID_RESPONSE` — the response could not be parsed or had the wrong shape
- `PARTIAL_FAILURE` — the fetch worked, but one or more record judgments or another later step failed

An empty response is not the same as a successful run with no new IDs. The report must not describe a fetch failure, invalid response, or empty response as `SUCCESS_NO_NEW`.

The baseline report includes fetched count, unique valid IDs seen, zero new postings, and state-save result. It does not claim that all existing jobs were judged.

## 10. State, pending judgments, and retries

The state file stores the board identifier, the set of all valid posting IDs ever seen on a successful fetch, the last successful fetch timestamp, and any posting IDs whose Claude judgment is still pending or invalid. The seen-ID set is cumulative, not a snapshot: once an ID has been seen, its disappearance from the board does not remove it from the set. If the same ID later reappears, it is not treated as new again.

The agent must not lose a posting just because Claude is unavailable. If the rule step succeeds but the Claude call fails or returns invalid output, the posting's rule result is saved and the posting ID is added to a pending-judgment list. On later runs, pending judgments are retried even though the posting ID is no longer new. A pending ID is removed only after a valid Claude result is stored or after an explicit, documented decision to stop retrying it.

If a fetch fails or the response is invalid, the last successful seen-ID state is preserved. State is updated only after a successful, validated fetch. State writes must be done safely so an interrupted write does not silently destroy the previous valid state.

A model error makes the run `PARTIAL_FAILURE`, not `SUCCESS_NO_NEW`. If there are no new postings but a pending judgment is retried and fails, the run is also `PARTIAL_FAILURE`.

## 11. Host allow-list and subscription boundary

The agent's own network requests may contact:

- `boards-api.greenhouse.io` — fetch public Greenhouse data.
- Any additional host explicitly documented as required by the approved Claude-subscription interface used by the project.

The implementation must document the actual Claude Code/subscription hosts it relies on before the build is considered complete. The agent's code can enforce the allow-list for requests it makes itself. It cannot guarantee or enforce the network destinations used internally by a separate `claude` executable that it launches; that limitation must be recorded rather than hidden.

The agent must not follow arbitrary links embedded in job descriptions. Requests it makes must use HTTPS. Redirects to undocumented hosts must be rejected. Subscription credentials and session tokens must never be written to the résumé, state file, output records, or logs.

If subscription-authenticated use is unavailable, the agent must leave model judgments unavailable or deferred. It must not quietly switch to an Anthropic API key or claim that a subscription-authenticated judgment was completed when it was not.

## 12. Refusals and résumé privacy

The agent accepts only the approved fictional résumé fixture. It checks all of the following:

1. `$.fictional` is exactly `true`.
2. The email ends in `@example.com`.
3. The phone number uses the reserved fictional `555-01xx` pattern.
4. The required Kiran persona and résumé fields are present.
5. The SHA-256 digest of the fixture matches a pinned expected digest in the test/configuration.

The expected digest must be calculated from the exact committed bytes of `persona/kiran-joshi.resume.example.json` and pinned before the first implementation run. The implementation must not calculate an expected hash from the file at runtime and then compare the file to that same newly calculated value, because that would prove nothing. If the pinned digest is not set, does not match, or any other check fails, the agent refuses to process the résumé and must not send its contents to Claude.

The agent must never print a real résumé, show its contents in a report, or commit a real résumé to GitHub. The only résumé details allowed in output are the specific matched skill terms and their JSON paths, plus the fictional persona label needed to identify the fixture. It must not dump résumé bullets, personal contact details, or unrelated fields to the terminal or logs. A real résumé must stay outside the repository; the existing ignore rules for `private/` and `*.resume.json` should be checked as part of implementation.

The agent also refuses to apply for jobs, email recruiters, log in, bypass access controls, ignore rate limits, follow arbitrary links, contact undocumented hosts, expose credentials, or write outside configured project data/output directories. It must never present Claude's judgment as a fact or as an employer's decision.

## 13. Three real-posting hand checks

Before implementation code is added, I will fetch current raw postings from the Stripe Greenhouse API and manually evaluate three postings using this exact contract. The record for each one must include the check date, posting ID, title, a short excerpt, title-check result, explicit-exclusion result, matched résumé skills, the résumé paths and posting paths for those matches, and the final verdict.

The three cases must include:

1. One posting that passes the title check, has at least two distinct skill matches, and has no explicit exclusion (`MATCH`).
2. One posting with an eligible title but fewer than two distinct skill matches (`NO_MATCH`).
3. One posting that fails the title check or contains an explicit exclusion (`NO_MATCH`).

I will not invent IDs or excerpts. The three entries must be filled from a real API response before this contract is considered ready for submission. If the board changes and the intended case is no longer available, I will choose another real posting that tests the same condition.

## 14. Two wrong implementations the tests must catch

**Wrong implementation A: title-only matching.** It returns `MATCH` for every title that looks like a software engineering role. This is wrong because the skill threshold and explicit exclusion check also apply. A test with an eligible title and zero or one distinct matching skill must return `NO_MATCH`.

**Wrong implementation B: raw substring counting.** It searches for skill strings after stripping punctuation and counts repeated appearances as separate skills. This is wrong because special skills such as `C#` need their own matching rule, common English words like “rest” must not count as `REST`, and repeated mentions of one skill count only once. Tests must cover `C#` versus plain `c`, plain-English “the rest of the team,” repeated mentions of a single skill, and a missing evidence path.

## 15. Failure statement

**October 29, 2026:** If a fetch fails or returns an invalid or empty response and the agent reports `SUCCESS_NO_NEW`, it has hidden a failed or unusable run by describing it as a successful run.

## 16. Hand-labeling for the prompt experiment

My hand labels will use the same deterministic rule as the agent, not my personal opinion about whether I would spend a day applying. I will apply the title check, skill threshold, and explicit exclusion phrases exactly as written, then record the evidence paths. Claude uses `RELEVANT` and `NOT_RELEVANT`, so its label can be compared directly with the human `MATCH`/`NO_MATCH` label using this mapping:

- `RELEVANT` corresponds to `MATCH`
- `NOT_RELEVANT` corresponds to `NO_MATCH`

This comparison measures agreement with the written rule, not whether a recruiter would interview Kiran or whether a job is objectively desirable.

## 17. Acceptance checks

The implementation is consistent with this contract only if:

- It reads the Kiran fixture from `persona/kiran-joshi.resume.example.json`.
- It validates the fixture flag, reserved contact patterns, required structure, and pinned SHA-256 digest.
- It fetches Stripe Greenhouse postings and validates the response shape.
- It decodes escaped HTML and strips tags before matching.
- The title, skill, and explicit exclusion checks follow this contract exactly.
- Each rule result cites the résumé and posting paths that support it.
- Claude's output is validated against the exact JSON schema and allowed labels.
- Invalid Claude replies are rejected rather than silently repaired.
- The model judgment includes evidence paths that are checked against the actual input objects.
- Baseline, no-new, empty, invalid, fetch-failure, and partial-failure outcomes remain distinct.
- Failed model judgments stay pending and can be retried.
- A failed fetch never overwrites the last successful state.
- The agent's own requests stay within the documented allow-list, and the separate Claude executable limitation is documented.
- A real or unverified résumé is refused and never printed or committed.
- The two wrong implementations above are caught by tests.
- Three real Stripe postings are recorded as hand checks before implementation code is committed.
- `CONTRACT.md` is committed before implementation code.

## 18. First commit

I will put this file at the repository root as `CONTRACT.md` and commit it before implementation code. I will check the history with `git log --oneline --reverse` so the order is visible. If a contract change is needed after the hand checks, I will commit that change before any code as well.

The exact SHA-256 digest of the approved résumé fixture must be pinned before the agent runs. The three live posting checks must also be filled in before this contract is treated as complete. Those are explicit pre-build tasks, not values to invent.
