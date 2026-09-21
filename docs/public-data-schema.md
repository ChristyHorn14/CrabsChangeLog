# Public data contract — schema 1

All JSON is UTF-8, sorted object keys, two-space indentation, trailing newline. Tag paths, sibling nodes, and branch changes are sorted by exact Unicode path (case preserved). No clock, locale, filesystem path, educational field content or internal identifier is included. Breaking changes require a schema increment; readers may ignore additive fields.

`website/releases.json` retains schema 1 and history. New release records add `tag_changes` (schema 1). Older records without tag changes mean **not calculated**, not zero. Existing delta definitions are unchanged. Editorial notes persist via `--notes-file`; never edit generated Markdown.

## deck-stats.json

| Field | Type / meaning |
| --- | --- |
| schema | integer, 1 |
| release_date | ISO date of newest recorded release, candidate or published |
| release_date_source | `release_argument`; not inferred from export or note timestamps |
| deck_name | exact common top-level name of decks containing cards, or null for multiple unrelated roots |
| deck_names | sorted list of exact active deck names |
| total_notes / total_cards | integer package row counts |
| total_tags | distinct exact content tags explicitly carried by notes |
| total_tag_nodes | explicit tags plus implicit ancestors |
| total_media | manifest entries with verified packaged bytes; not references or unique image contents |
| total_note_types | exported note-type definitions, including unused definitions |
| untagged_notes | notes with no content tags |
| excluded_tags | `leech`, `marked`: existing snapshot study-state exclusions |

Totals are nonnegative integers. Stats include all exported notes/cards, not only a chosen tag. Empty/default decks do not contribute names. The operator supplies the date; the immutable package hash binds that label in the internal registry.

## tags.json

Envelope: `schema: 1`, `release_date`, `count_unit: "notes_and_cards"`, `total_tags`, `total_nodes`, `roots` (array of nodes).

Every node has these core fields:

- `name`: final path component, preserved exactly.
- `path`: full `::` path, also the stable node key.
- `depth`: zero-based; a root has depth 0.
- `explicit`: whether any note carries this exact path.
- `direct_notes`, `direct_cards`: distinct items whose note explicitly carries this exact path.
- `aggregate_notes`, `aggregate_cards`: distinct items under this path, including itself and descendants.
- `children`: child nodes; empty for a leaf.

A note in parent and child or multiple descendants counts once in that branch. Cards are the union of cards belonging to those notes. Overlapping siblings/roots cannot be summed. Tags belong to notes. Unicode, punctuation, quotes, slashes, literal asterisks, mixed case and empty `::` components are preserved, not sanitized into another taxonomy. Consumers must escape display text. `Crabs::Procedures` and `Crabs::procedures` remain distinct exact paths regardless of Anki search case folding. Unused tag-cache entries are excluded.

## Release record: tag_changes

- `schema: 1`, `count_unit: "notes"`.
- `tags_added`, `tags_removed`: sorted exact explicit tags entering/leaving the package.
- `branches_added`, `branches_removed`: highest newly present/absent paths, including implicit ancestors; descendants beneath a newly introduced branch are not repeated.
- `by_branch`: changed paths with `path`, zero-based `depth`, `before_notes`, `after_notes`, signed `net_notes`, `added_notes`, `removed_notes`, `modified_notes`.

Counts use aggregate membership. Added/removed notes follow existing comparison matching. Modified counts count each retained modified note pair once if associated **before OR after**, so moves appear on both branches. Modification means fields, tags, model or extra data changed; template/media-only card updates do not imply modified notes. Retagging can change `net_notes` without adding/deleting notes. No rename or educational significance is inferred. Unchanged counts with modified notes still appear.

“Major” mechanically means depth 1 (children of any root). Summaries show the five major branches with highest positive `net_notes`, exact path breaking ties. This stable definition makes no clinical importance claim.

## Publication and ownership

Stats and tags describe `latest_release_date`, even on older comparison reruns. The website importer requires dates/totals to match the latest published record and refuses a mixed/candidate bundle. The already imported website stays unchanged while a candidate is prepared.

Human-authored: `docs/how-to-use.md`, `docs/updating.md`, `docs/usage-review.md`, optional notes-file input. The first two are copied unchanged into `website/`. Public Markdown supports headings, paragraphs, single-level bullets, inline code and HTTPS links, with no raw HTML. The website escapes text. Author TODOs remain in the maintainer review document.

Generated: snapshots, reports/checks, registry, marked changelog regions and `website/*`. In the website repository, `crabs/data/*`, `crabs/index.html` and the marked homepage release block are generated. Templates, styles and search interaction are human-maintained. Do not copy packages, snapshots, audits or media into the website.
