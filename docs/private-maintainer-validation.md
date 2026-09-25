# Pediatric ENT infrastructure pilot validation

Completed 2026-09-23. The user requested that all real proposals remain awaiting review.

## Real export

- Source: 9-21-26Crabs.apkg
- SHA-256: 989bd57641ddc3ee27aa9ec760c67152a2f11243d81f2172fb2d8b19b47a7dfc
- Pediatric scope: 512 notes, 477 eligible, 35 image-occlusion notes excluded.
- Exactly 15 eligible notes sampled; 462 eligible notes remain unaudited.
- 11 proposals: eight editorial corrections, one supported clinical proposal, two research-only findings.
- All 11 await human review. No real review decisions or deck patches were applied.
- No issue identified on a sampled note does not mean verified medically correct.

## Infrastructure verification

54 automated tests passed: 19 new maintainer tests and 35 existing release/tag tests. Legacy and modern APKG roundtrips passed. Tests cover approval, rejection, deferral, edited approval, durable history, duplicate GUID rejection, IO exclusion, new/unchanged/changed/cosmetic audit states, stale sources/decisions, patch tampering, conflicting field approvals, exact original matching, cloze/HTML/media preservation, output safety, and validation.

A separate synthetic 15-note sample plus an excluded IO note demonstrated proposal import, a browser approval, persisted rejected/deferred/edited/awaiting states, approved patch generation, exact preview, explicit application, and validation. Only two approved synthetic notes changed; all other notes, fields, tags, cards, media, and IO content were preserved. Synthetic output passed raw SQLite, normalized snapshot, source hash, archive-member, and existing release checks. This demonstration is not a substitute for human approval of the real proposals.

The real browser queue was opened and inspected successfully. Source/Extra/tag context, evidence, decision controls, status counts, and disabled research-only approvals were visible.

## Resume

The live review queue is http://127.0.0.1:8766. Restart from the project with `.venv/bin/python maintainer.py serve --port 8766` if necessary. Port 8765 was already occupied.

Read docs/private-maintainer.md for the complete commands and schema. Save your review decisions, generate an approved preview, then deliberately apply its exact patch ID to a new output package. The real-deck application and post-application validation remain pending by user choice.

The source package, public website files, release registry, snapshots, and existing reports were not modified. No commit or push was performed.

## Limits

Static validation does not replace a disposable-profile Anki import test or medical review. The pilot supports field text edits while retaining cloze ordinals and HTML/media tokens; tag edits and card structure changes are blocked. History and deck content are stored locally under ignored private-audit/.
