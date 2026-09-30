# Private maintainer pilot

This local tool is separate from the public release/site workflow. It never generates public artifacts or accesses a live Anki profile. The default audit path is the [Work-driven workflow](work-driven-audit.md), which needs no separate API credentials. The optional `research` command sends candidate note content to the configured OpenAI Responses API and web-search service; all other commands remain local. Source APKG files remain unchanged. Use the existing virtual environment; no dependencies were added.

## Routine use

From `CrabsChangeLog`:

```sh
.venv/bin/python maintainer.py ingest ../9-21-26Crabs.apkg --version 2026-09-21
.venv/bin/python maintainer.py import-findings private-audit/pilot-proposals.json
.venv/bin/python maintainer.py serve
```

To process the current non-approved null-proposal queue in Work:

```sh
.venv/bin/python maintainer.py work-backfill-status
.venv/bin/python maintainer.py prepare-work-backfill private-audit/work-backfill-YYYY-MM-DD-NN.json --limit 10
```

The batch file is a read-only manifest selected from current durable history. Work researches it, creates a schema-3 result bundle, and imports that bundle with `import-findings`. Importing appends superseding proposals; it does not overwrite prior findings or review decisions, approve anything, or modify an Anki package. Re-run `work-backfill-status` after import; the remaining count is the durable progress marker. See the full [Work-driven runbook](work-driven-audit.md).

The optional `maintainer.py research` API runner remains available; see [Evidence-backed audit contract](evidence-backed-audit.md). It requires `OPENAI_API_KEY` plus `--model` or `CRABS_RESEARCH_MODEL`, checkpoints every candidate, validates exact existing-field-only output, and imports into the human queue by default. Local Python does not and cannot invoke the user's Work subscription.

Open http://127.0.0.1:8765. Confirm the batch and note/finding counts, enter your reviewer name, then choose **Start Review**. The last name and queue filter are remembered locally when browser storage is available; every new page session still requires Start Review. Text, Extra, and any other fields are shown together for each note. Fields with findings are emphasized; fields without findings remain visible as context and require no separate disposition. Each finding supports **Approve (A)**, **Reject (R)**, **Defer (D)**, **Needs research (N)**, or **Edit + Approve (E)**. Decisions remain finding-level even when several findings share one note. Original and proposed text use red strikethrough deletions and green underlined additions; exact HTML is displayed as text.

Each action waits for the database commit and displays the saved decision and reviewer. Navigation prioritizes the next note with an unresolved finding; fields without findings never block progress. A failed save leaves the note and draft in place. Previous/Next only navigate. Revisited findings show the saved decision, reviewer, timestamp, and append-only history. Unsaved changes require confirmation before leaving. Existing HTML/media/cloze protections remain enforced. Refresh/restart reloads saved decisions from SQLite; unsaved drafts are not persisted.

**Edit final values + Approve (E)** makes all fields on the note editable in place. Every field starts at its exact current or previously approved value; use **Use automated proposal** on a finding field when that proposal is desired. The approval control is adjacent to the final-value workspace. Saving records only fields whose values actually changed. Editing another field does not create a finding, resolve a sibling finding, or alter the immutable field/category/provenance of the finding that prompted the work.

The **Needs research** filter is the persistent retrieval queue for decisions saved with that status. It shows the complete note, automated finding/proposal, audit version/date, citations, saved decision, and history. Reopen an item there to enter a supported human correction or change its decision; it leaves the queue as soon as its latest saved status changes.

Cross-field editing exists because the safest correction is sometimes to preserve a concise atomic retrieval target in Text while adding nuance, limitations, or clinical context to Extra. A resolution may therefore leave the finding field unchanged and edit another field, or edit several fields together. All edits in that resolution share one review decision and are applied atomically to the note.

The interface retains source fields, tags, GUID and evidence details. Use **Preview approved patch** or the `preview` command below to inspect approvals.

Approval only saves a decision. Closing/restarting the application retains all decisions. A research-required automated proposal cannot be blindly approved. After doing the research, however, a reviewer may enter a human correction and must record a **Reviewer evidence / rationale note** with that approval. This text is the review row's `comment`: it remains in append-only review history, is not inserted into an Anki field, and is not consumed by patch generation. Editing and approving is a human assertion, and substantively changed clinical text requires the reviewer to check its evidence. The prototype records that provenance but does not judge evidence quality or whether edited text is medically supported.

After review:

```sh
.venv/bin/python maintainer.py preview --output private-audit/approved-01.json
```

This saves machine-readable approvals and `approved-01.preview.txt`, showing exact original/replacement fields, GUIDs, numeric IDs, total notes affected, and that tags are unchanged. It does not touch any deck. Inspect the complete preview. To explicitly apply, copy the full patch ID printed in the preview:

```sh
.venv/bin/python maintainer.py apply private-audit/approved-01.json \
  --output ../peds-pilot-reviewed.apkg --confirm PASTE_FULL_PATCH_ID_HERE
```

The output must be a new filename. Only approved changes from that exact package and the current decision history are accepted. Changing a decision invalidates the old patch. A changed source package, conflicting approvals, altered patch, empty patch, existing output, or unsupported edit fails closed. If output/report already exists, inspect it and use another output name; do not blindly delete and retry.

The resulting package is re-read by the existing release reader and compared with the exact expected snapshot before publication to the output path. A sibling `.validation.json` contains exact applied changes, source/output hashes, raw database checks, and the existing release comparison. This is a local candidate, not a distributed deck. Before distribution, test importing it into a disposable Anki profile. Static checks cannot guarantee behavior in individual collections or prove medical correctness.

Read current coverage or export portable history:

```sh
.venv/bin/python maintainer.py coverage
.venv/bin/python maintainer.py export-history private-audit/history-export-01.json
.venv/bin/python -m unittest discover -s tests -v
```

`--db PATH` before the subcommand selects a separate history database. JSON exports include the complete source snapshots and exact SQLite history values (payload/snapshot columns are JSON strings). Back up `private-audit/history.sqlite` while the UI is stopped. It is intentionally ignored by Git, as are proposals, sample notes, patches, and local outputs. Keep source code and this guide in version control. No deck content enters the website directory.

## Architecture and data model

`crabs.reader.read_package()` is the authoritative Anki abstraction: normalized notes keyed by numeric ID, each containing stable GUID, ordered named fields with exact values, model ID, tags, and media references. All maintainer matching uses unique GUIDs plus verified numeric ID and original fields, never text similarity or line numbers. Duplicate/empty GUIDs and duplicate field names are rejected. `crabs.compare.compare()` supplies the familiar release validation alongside stricter exact patch checks. Existing parser and release behavior are unchanged.

`crabs/maintainer.py` implements coverage, proposals, reviews, and patches. `crabs/maintainer_patch.py` copies and patches APKG packages. `crabs/maintainer_ui.py` is a replaceable local browser interface. The root `maintainer.py` provides commands.

The SQLite history has seven append-only tables:

| Table | Durable information |
| --- | --- |
| exports | Source SHA-256, explicit version label, absolute input path, ingestion date, complete normalized snapshot |
| audits | Export hash, GUID, relevant-content fingerprint, audit logic version, date, outcome |
| findings | Deterministic finding ID, source hash, complete immutable finding JSON |
| reviews | Finding ID, status, reviewer, final edited text, optional comment, timestamp; every subsequent decision adds a row |
| field_reviews | Source hash, GUID, field, unchanged disposition, reviewer, comment, timestamp; every disposition or reset adds a row |
| review_edits | Review and prompting-finding IDs, GUID, changed field, exact before/after values, and timestamp for every human-directed resolution edit |
| applications | Validation reports and approved changes for applied output packages |

Database triggers reject updates/deletes to historical records. Application code uses transactions. The latest review event determines current status; older decisions remain available. Legacy finding decisions remain valid for the field named by the immutable finding. A one-time migration reset is a later `reset_due_to_field_granularity_migration` event, so the item becomes pending without deleting its prior decisions. Audit outcomes are `proposals` or `no_issue_identified`. **No issue identified does not mean verified medically correct.** AI proposals enter as `awaiting_review`; they never enter as approved. Rejection is durable, not deletion.

## Finding import schema

Create a JSON bundle with `source_sha256`, `audit_version`, `author`, `sample_guids` (10–20 unique eligible GUIDs), and `findings`. `private-audit/pilot-proposals.json` is the concrete example for this pilot. The import command validates the entire bundle before committing it.

Every input finding needs:

- `guid`, `field`, `original` (exact complete field), `replacement` (exact complete replacement, or null for research-only findings).
- `category`: clinical_accuracy, outdated_recommendation, outdated_guideline, threshold, dose, classification, staging, diagnostic_criteria, oversimplification, ambiguous_wording, contradiction, redundancy, card_construction, cloze_construction, answer_leakage, excessive_information, low_value, extra_field, organization.
- `severity`: low, moderate, high, critical; `confidence`: low, medium, high.
- `rationale`, `evidence_status`: supported, editorial, needs_research; `evidence`: an array, required nonempty for supported proposals.
- Each source: title, organization_authors, publication, year, HTTPS url; include DOI/PMID, locator, accessed date and support explanation when available.

Import adds numeric note ID, related card IDs, specialty/subspecialty, exact source/version, content fingerprint, audit date and audit version. It derives stable finding IDs from proposal/content/evidence/audit-version identity, excluding export metadata. Reimporting an identical rejected finding does not create a new review item, even in a later export. Changed relevant content, evidence, proposal, disposition, or audit version permits a new proposal. The importer does not perform medical research or generate blanket findings across the specialty. Legacy schemas 1 and 2 remain readable. New evidence-backed audits use schema 3 with `audit_stage: "evidence_backed"`, an explicit disposition, researched conclusion, uncertainty, and exact zero-or-more field changes. See [Evidence-backed audit contract](evidence-backed-audit.md).

Approvals are strictly tied to their original package hash. An identical suppressed finding from a different export remains in history and is not silently carried into a new patch. When a previously approved proposal needs application to a different package, generate a new audit version and review it again. This intentional conservative rule separates transferable audit coverage from exact-byte patch authorization.

## Eligibility, selection, and living-deck coverage

Pediatric scope is the exact `Crabs::Specialty::Peds` tag or a descendant of `Crabs::Pasha::Chapter9PediatricOtolaryngology::`. This is tag-based and may miss untagged/mistagged Pediatric notes. It does not infer clinical specialty from prose. The fixed pilot manifest contains 15 notes selected for a mixture of basic, multiple-cloze, factual, procedural, management, guideline-sensitive, media-containing, and substantial Extra content. It is not a random sample or an estimate of problem prevalence. Do not expand it during this run.

Image occlusion is excluded when the model has a normalized Image Occlusion name, stock kind 6, Question Mask + Answer Mask fields, Occlusion + Image fields, or image-occlusion template marker. This covers the native and enhanced models found in the source. Unknown heavily customized types can evade heuristics; add an explicit tested detector before auditing them. Excluded notes remain in snapshots and raw validation, are absent from audited eligible counts, and cannot be patched.

Coverage always uses the selected/current export, not a historical denominator. It counts total notes in scope, eligible notes, audited unchanged eligible notes, unaudited eligible notes, and excluded image-occlusion notes. Each scoped note is:

- `never_audited`: eligible, no audit, already present/first baseline.
- `new_unaudited`: no audit and absent from all earlier imported exports.
- `audited_unchanged`: latest historical audit fingerprint equals current fingerprint.
- `modified_needs_reaudit`: historical audit exists but relevant content changed.
- `excluded_image_occlusion`: outside the content pipeline.

A first-ever export cannot distinguish newly created from previously existing unaudited notes. Import later exports to establish that history. Removed notes stay in history but leave current counts. GUID-preserving numeric-ID remapping does not invalidate coverage. Specialty tag changes update scope; tags alone do not invalidate clinical coverage.

## Field-aware audit validity

Fingerprint rule version 1 includes **every named field**, the complete normalized model/template definition, and checksums for referenced packaged media. Only exact attribute-free `<span>` and `</span>` wrappers are removed for fingerprinting. No normalization is performed when patching. All other field bytes, including whitespace, emphasis, links, units, cloze syntax, substantive Extra content and attribute-bearing markup trigger re-audit. This narrow exception is deliberately conservative; it is not a general semantic HTML diff.

Tags and nonclinical note metadata do not affect this clinical fingerprint. A tag/organization audit may require separate rules later. Media images are not clinically interpreted, but changed packaged media bytes trigger re-audit. Remote resources can change without a local checksum; the tool cannot detect that. Model changes conservatively invalidate coverage. Historical fingerprints/decisions are never rewritten.

## Patching and validation limits

Only complete approved field replacements are supported. One approved resolution may contain several replacements on the same note; they retain their relationship to the prompting finding and are applied in one package transaction. **Tag changes, new/deleted notes/cards, changed cloze ordinals/delimiters, and changed HTML/media/link tokens are intentionally blocked in this pilot.** The schema displays empty tag changes; it does not claim tag-edit support. Plain text inside existing markup/clozes can change. Guardrails are structural, not a complete Anki renderer or clinical validator.

The writer extracts only a temporary authoritative database and changes approved note fields using GUID + ID + exact old value. It preserves note IDs/GUIDs, cards/scheduling, tags (including raw study-state tags), models/decks, media, and the compatibility database. Required changed-note metadata is explicit: `mod` advances, `usn` becomes -1 when present, and first/sort-field cache columns are updated when applicable. First/sort-field updates involving media/script/style/comments are rejected by the pilot cache adapter. No cards are regenerated; edits requiring card-generation changes are unsupported.

Validation compares all raw SQLite tables/schema against a precomputed expected result, allowing only approved `flds` and the declared metadata/cache changes. It also compares every normalized note/field/card/model/deck/media value, checks source SHA-256 immutability, and hashes every non-authoritative-database ZIP member. All source ZIP entries remain present; ZIP compression bytes may differ, while their uncompressed payloads are identical except the patched authoritative database. The output is published only after these checks pass. A crash after output publication but before recording history/report can leave a valid output without its report; inspect/recover deliberately.

A failed check stops application; no source deck is ever replaced. For a later ordinary release comparison, the patched APKG remains compatible with `release.py ... --check-only`. Public generation/distribution is outside this pilot.

## Another specialty later

Reuse the note/GUID abstraction, history, review UI, and patch engine. Add an explicit tested specialty predicate and scope label, then a separate bounded sample/audit version. The current CLI deliberately hard-codes the Pediatric scope and 10–20-note import limit. Do not audit another specialty or the whole Pediatric deck as part of this infrastructure run.

## Evidence and safety

The pilot includes an AAP-guideline-based AOM dosing proposal, editorial corrections, and unresolved questions. The source citation is retrievable and scoped to the relevant statements; it is not proof of current universal applicability. All remain proposals until reviewed. Clinical findings without verified support have no proposed replacement and must be deferred. Editorial corrections do not validate the surrounding medical claims. Do not treat an audited specialty, a passing validation report, or no findings as medical certification.

This loopback-only UI uses same-origin mutation checks and displays untrusted content as text. It has no authentication and is intended for a trusted local machine only. Do not expose its port publicly. It does not fetch media, third-party scripts, or evidence pages automatically.

### Review UI regression checks

Run `.venv/bin/python -m unittest discover -s tests -v` (Node.js is needed for the browser-controller regression test). The tests use synthetic packages and a temporary loopback server; they do not read or modify the live audit database.
