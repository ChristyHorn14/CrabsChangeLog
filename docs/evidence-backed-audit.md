# Evidence-backed audit contract

## Traced limitation and null-proposal cause

This repository implements snapshotting, validated finding import, append-only human review, patch preview, an explicit copy-on-write patch step, and two ways to complete evidence-backed research. The default is the [Work-driven audit workflow](work-driven-audit.md): ChatGPT Work researches and synthesizes schema-3 bundles, which are validated and imported locally without separate API credentials. The optional local runner uses the OpenAI Responses API with web search and strict structured output. The existing `private-audit/triage/triage-prompt-v4.txt` remains a low-cost first stage: it forbids external research, citations, and proposed corrections. Its `review` result is an escalation signal, not a finished finding.

The earlier schema-2 validator closed only one gap: a null `needs_research` finding had to say that research was attempted and record limitations. It did not require a researched conclusion, an explicit retain/revise/split/delete/replace disposition, or exact cross-field proposals when evidence was adequate. The data model also exposed only one nullable `replacement` on the finding field. Consequently, a high-confidence finding could carry a directly relevant guideline and rationale yet still validate with a null replacement. The importer faithfully persisted that payload, and the UI correctly—but unhelpfully—reported that no final value was supplied. The missing step was therefore between retrieval and import: enforced synthesis into an actionable proposal, plus a safe way to supersede existing null findings.

## Required second-stage flow

Feed triage `review` items, plus editorial items that may conceal a substantive issue, to a research-capable audit stage. For each note:

1. Inspect Text, Extra, tags, and relevant note context together.
2. Identify the exact questionable claim and why it matters.
3. Retrieve authoritative, directly relevant evidence. Prefer current specialty-society guidelines, government or standards bodies, systematic reviews, and primary literature as appropriate. Record usable HTTPS links and locators.
4. Reconcile scope, population, date, and conflicting evidence. Never turn an inference into a cited fact.
5. Produce a concise researched conclusion.
6. When support is sufficient, propose exact complete Text and/or Extra field values that preserve existing HTML, media references, and cloze structure and follow the deck's concise retrieval-target conventions.
7. Set confidence from the evidence actually found.
8. Use `needs_research` only after an attempted search still cannot support a sufficiently confident recommendation. Document the limitation; do not fabricate a citation or replacement.

New output uses schema 3 and `audit_stage: "evidence_backed"`. Every finding includes `researched_conclusion`, `disposition` (`retain`, `revise`, `split`, `delete`, or `replace`), `remaining_uncertainty`, and `proposed_changes`. Each proposed change contains an exact `field`, `original`, and complete `final` value. `revise` requires at least one change and supports Text-only, Extra-only, or cross-field changes. Non-patch dispositions contain no field changes; the maintainer displays and can approve the recommendation without inventing patch semantics.

Only a genuinely unresolved item may use `evidence_status: "needs_research"` with no proposed changes. Its disposition may be null, it must set `research_attempted: true`, provide nonempty `research_limitations`, and may not claim high confidence. Finding a relevant source while leaving synthesis unfinished does not meet this condition.

## Existing-queue backfill

`maintainer.py export-backfill OUTPUT.json` exports current, substantive null-proposal findings whose latest state is awaiting review, needs research, or deferred. Approved findings, editorial findings, already superseded findings, and findings that already have proposals are excluded. The export itself is read-only; the built-in evidence runner consumes it.

Import the runner's schema-3 response with the existing `import-findings` command using `reprocess: true` and `supersedes_finding_id` on each result. Import appends a new finding; it never edits the original finding or its review history. The maintainer queue shows the newer result and retains the prior finding and decision in SQLite. Reimporting an identical response is idempotent because the stable finding identity is unchanged. An approved finding cannot be superseded through this path.

The importer enforces the actionable schema. Legacy schemas 1 and 2 remain readable for historical data. Human review, exact field edits, rationale comments, source binding, and patch provenance remain distinct and unchanged.

## Default: run the research stage in Work

Use the repository-level [Work-driven audit runbook](work-driven-audit.md). After a deck upload, `grab/audit the next batch of new cards` means selection through schema-3 validation/import, including Work research for substantive findings. For the existing queue, `process the next backfill batch` uses `prepare-work-backfill`, researches the selected manifest in Work, and imports the completed results. Neither path requires API credentials.

## Optional: local API research runner

The following runner is retained for future/local automation. It is not required for normal Work-driven auditing.

Provide credentials without placing secrets in the repository:

```sh
export OPENAI_API_KEY='...'
export CRABS_RESEARCH_MODEL='your Responses API model with web search support'
```

Run and import the existing backfill:

```sh
.venv/bin/python maintainer.py research \
  private-audit/backfill-candidates-v1.json \
  private-audit/backfill-researched-v1.json \
  --checkpoint private-audit/backfill-researched-v1.jsonl
```

Each successful candidate is flushed and synced to JSONL before the next begins. The same command resumes safely and does not call the model again for completed, unchanged inputs. Use `--limit N` for a bounded backfill batch, then rerun without it to continue. A partial future-audit batch must use `--no-import` until complete so unprocessed notes cannot be recorded as audited. The command otherwise imports completed findings by default. Import remains append-only and idempotent. It does not approve findings or read or write an Anki package.

For future audits, pass the ordinary audit bundle to the same `research` command instead of directly importing substantive findings. The command attaches full note context from the current immutable snapshot, researches every non-editorial finding, produces schema 3, and imports it for normal human review. Editorial-only findings may continue through the existing importer.

`docs/crabs-card-style.md` is loaded verbatim into every request. Startup fails if its existing-note-only or no-clozes-in-Extra constraints are missing. Local validation rejects unknown fields, altered source identities, duplicate field changes, clozes in Extra, unsupported null proposals, non-HTTPS evidence, malformed cloze/HTML/media structure, and changes to the existing cloze ordinal multiset.
