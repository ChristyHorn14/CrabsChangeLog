# Work-driven Crabs audit workflow

This is the default audit workflow. It uses ChatGPT Work as the research and synthesis layer and does not require `OPENAI_API_KEY`, `CRABS_RESEARCH_MODEL`, or separately billed API use. The local `maintainer.py research` command remains an optional automation path; local Python cannot invoke a user's ChatGPT Work subscription.

## Simple user triggers

- After uploading the latest Crabs `.apkg` to the Crabs Project: **`grab/audit the next batch of new cards`**
- **`add in N new cards`** has the same full-workflow meaning: select N eligible unaudited notes, audit every note, research substantive findings, synthesize edits/dispositions, and import the completed results. Merely creating a manifest is not completion.
- For the existing queue: **`process the next backfill batch`**

Those phrases mean the complete workflow below, not a triage-only pass. A substantive item is not complete merely because it was labeled `needs_research`.

## Future uploaded-deck audits

1. Treat the uploaded `.apkg` as read-only. Ingest it into the local append-only history with an explicit version if it is not already the selected export.
2. Use `coverage` and the durable GUID/fingerprint history to select a manageable batch of `new_unaudited`, `never_audited`, or `modified_needs_reaudit` eligible notes. Do not select `audited_unchanged` notes.
3. Audit complete note context: Text, Extra, tags, note type, media references, and relevant model context.
4. Resolve editorial issues directly. For substantive clinical findings, use Work's web/research capabilities during the same task. Prefer authoritative guidelines, standards bodies, systematic reviews, and primary literature as appropriate.
5. Follow `docs/crabs-card-style.md` and produce schema-3 evidence-backed results: researched conclusion, disposition for the existing note, exact complete Text and/or Extra when `revise` is defensible, evidence, confidence, remaining uncertainty, and diffs/proposed changes.
6. Validate and import the completed bundle with `maintainer.py import-findings`. Import is append-only and idempotent. It creates an awaiting-review item; it never approves or patches a deck.
7. Report selected notes, researched findings, imported finding IDs/count, no-issue outcomes, and anything genuinely unresolved.

One audited note remains one note. Never create a new card automatically. Aggressive rewriting of the existing note is allowed when it produces a better card. Use advisory `split` when a second card is warranted, without creating it. Extra should add concise understanding, not become a citation dump.

Do not mark a partial future batch as audited. The imported bundle's `sample_guids` must represent every selected note, including notes with no findings, only after all of them have completed the audit/research/synthesis pass.

## Existing backfill: durable batch and resume procedure

The current baseline is `private-audit/backfill-candidates-v1.json`. Eligibility is recalculated from SQLite rather than tracked in a hand-edited counter: approved, rejected, already superseded, editorial, and proposal-bearing findings are excluded according to the repository rules. As schema-3 results are imported, their `supersedes_finding_id` links preserve the original finding and review history and remove that candidate from the next eligible batch.

At the start of a Work session:

```sh
.venv/bin/python maintainer.py work-backfill-status
.venv/bin/python maintainer.py prepare-work-backfill private-audit/work-backfill-YYYY-MM-DD-NN.json --limit 10
```

`prepare-work-backfill` refuses to overwrite a batch file. Keep that manifest until its results have been validated and imported; reopening the same file resumes the same selected candidates without reselection. Use a small limit when evidence is complex.

For every candidate in the manifest, Work must:

1. Read the prior finding and complete note.
2. Perform actual evidence research when the issue is substantive.
3. Produce one schema-3 result following the style guide and `docs/evidence-backed-audit-prompt.txt`.
4. Copy `supersedes_finding_id` exactly.
5. Use `needs_research` without a proposal only after a genuine unsuccessful research attempt, with limitations documented and non-high confidence.

Write a result bundle beside the manifest, validate/import it with:

```sh
.venv/bin/python maintainer.py import-findings private-audit/work-backfill-YYYY-MM-DD-NN-results.json
.venv/bin/python maintainer.py work-backfill-status
```

The importer validates source identity, eligibility, schema 3, evidence URLs, existing fields, exact originals, HTML/media/cloze structure, dispositions, and supersession. A failed import commits nothing. Reimporting identical results is idempotent. After a successful import, the status count drops and the next prepared batch selects the next eligible candidates. If a session stops before import, resume from its existing manifest and result draft; do not prepare another batch first.

No step approves findings or mutates an Anki package. The user reviews in the maintainer, and only the separate explicit approved-patch workflow can create a new package.

## Schema-3 bundle shape

Top-level fields are `schema: 3`, `audit_stage: "evidence_backed"`, matching `source_sha256`, the appropriate `scope`, all selected `sample_guids`, a versioned `audit_version`, `author`, `reprocess`, and `findings`. Backfill sets `reprocess: true`; future audits set it to false.

Each finding includes the fields required by `docs/evidence-backed-audit-prompt.txt`. For `revise`, `proposed_changes` contains exact complete existing-field values. For `retain`, `split`, `delete`, or `replace`, it is empty and the disposition remains an advisory review item. Do not encode approval or deck-application intent in the bundle.

## Optional API automation

`maintainer.py research` implements the same contract with checkpointed Responses API calls and web search. It is optional and requires separate API credentials. It is not the default workflow and is not needed when Work performs the research and creates the schema-3 bundle.
