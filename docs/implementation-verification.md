# Crabs documentation pipeline verification

Implementation verified locally on September 20, 2026. Human-authored record of this implementation, not a generated release fact.

- 23 pre-existing tests passed before changes; all 35 pipeline tests passed afterward (12 added).
- All 11 website tests passed, including mixed/candidate bundle rejection, hierarchy/count validation, HTML escaping, editorial notes, generated-file equality, local links and unique HTML IDs.
- The full `release_workflow.py` command ran against the original June 20 and September 20 packages with the actual local website checkout. Both package hashes still match the registry's original hashes. Both normalized snapshot files remained byte-identical to their Git versions.
- Rerunning the complete pipeline and website import changed none of the 59 compared repository files/assets. Generation is deterministic and retained historical release records.
- Independent brute-force membership/card queries against the current normalized snapshot matched all direct/aggregate counts for all 621 hierarchy nodes.
- Public generated files contain no local filesystem paths, package hashes, GUIDs, note/model IDs, educational fields or template definitions.
- Chromium checks passed at 1440px, 390px and 320px: no horizontal overflow, collapsed initial tree, keyboard expansion, literal punctuation/Unicode search, no-result state, clear/restore, collapse-all, and no runtime errors. Native tree expansion and documentation worked with JavaScript disabled. Desktop Crabs and mobile homepage screenshots were visually inspected.
- Git diff whitespace checks passed in both repositories; the homepage changed only inside its existing release markers. Shared styles, existing tool links and download URL remain unchanged. The source repository Git index safety guard passed; nothing was staged, committed, pushed, uploaded or deployed.

## Current package

CrabsMcChaffey Light Year ENT Deck: 4,275 notes, 5,653 cards, 580 explicit content tags, 621 hierarchy nodes, 3,063 verified media entries, 8 note-type definitions, 28 untagged notes. The release date is the explicit operator label, not an inferred package timestamp.

June → September: 183/399/2 notes added/modified/removed; 291/473/2 cards added/updated/removed; 17 exact tags added and one removed. Largest depth-1 branch expansion is `Crabs::Residency`, +233 associated notes net; retagging contributes, so this is not a count of newly authored notes.

## Limits and follow-up

The author reports a successful June-then-September import in a clean profile. This implementation did not repeat that manual Anki test or touch any live collection. Exact import version/options/results are not recorded. Existing static warnings remain: removed ancillary deck/content, one card move, new note type, and 94 legacy field/template definitions without merge IDs. None was silently converted into an update guarantee.

See `usage-review.md` for historical tag mismatches and educational decisions requiring author review. Case variants, legacy tags and suspicious standalone/ellipsis tags are exposed faithfully, not renamed or removed.

The existing download form is a Google Forms `/edit` URL. It was preserved, not replaced or submitted; respondent access should be verified by the owner. External destinations were preserved; validation did not authenticate as a fresh download recipient.

Writes are atomic per file, not across repositories. Rerun after interruption. Future unknown Anki formats still fail closed and require an adapter/test update. Public bundle dates/counts must match before the site imports. The full static tag tree is lightweight at current size; substantially larger future decks may benefit from lazy rendering.

Routine supported-format releases require the documented Python command, review and ordinary publishing steps, not ChatGPT Work or any LLM.
