# Crabs Anki release workflow

Compare a previously published Anki deck with a new candidate, audit update identity and educational changes, and generate text snapshots, release notes and website metadata. Source packages stay outside this Git repository. This tool never runs Anki, imports a package, changes a live collection, repacks a deck, stages files, commits, pushes, uploads or deploys anything.

## For the next release

After September has actually been released, export your next deck from Anki and keep it beside the original September package. For example, for a January 15, 2027 candidate:

```sh
cd /Users/chrishornung/Developer/Anki/CrabsChangeLog
.venv/bin/python release.py ../9-20-26Crabs.apkg ../1-15-27Crabs.apkg \
  --baseline-date 2026-09-20 --release-date 2027-01-15
.venv/bin/python git_safety.py
git status --short
```

Substitute your actual candidate filename and release date. **Until September is published, June remains the published baseline.** Choosing a package as the baseline records your assertion that it was published. Filenames have no role in note/deck identity and do not determine release dates.

Stop and read the console checks, the new `reports/<baseline>_to_<candidate>.md`, `CHANGELOG.md`, and `website/whats-new.md`. `WARNING` requires review; `FAIL` blocks generation. No command here commits or publishes anything.

## Setup

Python **3.9 or newer** and one pinned dependency, Zstandard, are required. Python's standard library supplies SQLite, ZIP handling, hashing and the test runner. No Anki installation or profile access is needed. Initial setup (or recreating the ignored environment):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

The repository's `.venv` is local only, not part of Git. The CLI resolves output paths relative to the script, so you may invoke it from another directory; input paths remain relative to your shell's current directory. Commands in this README assume this repository as the current directory.

## First actual comparison

```sh
.venv/bin/python release.py ../6-20-26Crabs.apkg ../9-20-26Crabs.apkg \
  --baseline-date 2026-06-20 --release-date 2026-09-20
```

Actual package inspection found:

| Package | Metadata | Authoritative collection | DB schema | Media manifest |
| --- | --- | --- | --- | --- |
| June 20 | version 2 | `collection.anki21` | 11 | JSON |
| September 20 | version 3 | `collection.anki21b` | 18 | Zstandard-compressed protobuf |

Both ZIPs also contain a small `collection.anki2` compatibility database. Reading that instead would produce a misleading deck snapshot. The adapter selects the authoritative database from package metadata. September's database and media members are Zstandard-compressed. June's database uses ordinary ZIP compression.

Initial results: **4,094 → 4,275 notes**, **5,364 → 5,653 cards**, **2,871 → 3,063 packaged media files**. There are 183 added, 2 removed and 399 modified notes (249 with field edits and 150 tags only); 291 added, 2 removed and 473 updated retained cards. There are 193 media additions, 1 removal and no same-name byte replacements.

All 4,092 retained notes preserve GUIDs and numeric note IDs. The seven common models are unchanged; a native Image Occlusion model was added. The main deck's name and ID are unchanged. `Cases` is absent in September and one retained card moved into the main deck. Read the report for the precise affected IDs and content. These facts support update continuity but do not guarantee an individual's import outcome.

## Commands and options

`release.py BASELINE CANDIDATE --baseline-date YYYY-MM-DD --release-date YYYY-MM-DD`

Both input paths and both dates are required. The candidate date must be later than the baseline date. ISO dates also serve as version identifiers; there is one package per release date. They are explicit labels supplied by you, not inferred from note timestamps, package names or export timestamps.

Optional arguments:

| Option | Meaning |
| --- | --- |
| `--check-only` | Read and compare both packages, print safety checks/counts, write no release outputs. |
| `--strict` | Stop with exit 2 on warnings as well as failures; generates no release outputs. |
| `--project "Crabs Anki Deck"` | Public project name; must agree with an existing release registry. |
| `--notes-file reviewed-notes.txt` | Add reviewed public editorial bullets, one nonempty line per bullet. These persist on later reruns without this option. |
| `--publication-status candidate` | Explicitly designate local release metadata as a candidate. Default for a new entry. |
| `--publication-status published` | After your review and actual release, mark local metadata as published. Does not upload, commit, change the Google Form, or deploy the website. |

A safety-only check:

```sh
.venv/bin/python release.py ../6-20-26Crabs.apkg ../9-20-26Crabs.apkg \
  --baseline-date 2026-06-20 --release-date 2026-09-20 --check-only
```

A standalone deterministic snapshot:

```sh
.venv/bin/python snapshot.py /path/to/deck.apkg --output snapshots/2027-01-15.json
```

The standalone output must be a `.json` path inside this repository and cannot replace different existing content. It does not record a release in the registry. Normally use `release.py` to do everything together.

After you have reviewed and actually distributed a release, rerun its comparison with `--publication-status published` to update only its local designation and generated public text. No automated publication is implemented.

## Read-only guarantees and limits

Inputs must have `.apkg` extensions and resolve outside this repository. ZIPs are opened read-only. Only the authoritative database is decompressed into an OS temporary directory, then opened by SQLite using `mode=ro&immutable=1` with `query_only=on`. Temporary files are cleaned on normal completion and Python exceptions. Media is streamed through checksums, never saved. Each package's SHA-256 and modification time are checked across extraction. No live Anki path is opened.

A hard process kill or power loss can leave an OS temporary directory named `crabs-audit-*`, a `.release.lock`, or `.crabs-*.txt` staging files. These are not source packages; remove stale artifacts only after ensuring no audit is running, then rerun. The lock prevents concurrent release builders. Outputs are prepared and validated before writes; each file replacement is atomic, but the entire multi-file release is not a filesystem transaction. A rerun recovers an interrupted write.

Packages are large, redundant binaries that cannot produce useful Git content diffs. The June and September packages total roughly 580 MB; the human-readable snapshots and audit are a small fraction of that and contain no media binaries. They do contain full educational note text: review repository visibility before choosing to publish them. The separate `website/` files contain only compact release metadata and public bullets.

## What snapshots contain

`snapshots/<date>.json` contains sorted mappings for decks, models, notes, cards and media, plus counts and detected media references. Pretty-printed UTF-8 JSON preserves multiline field values as escaped strings and keeps one field value per line. Stable keyed records avoid row-order churn in ordinary `git diff`. The snapshot schema is explicitly versioned.

Included:

- Deck IDs, names/subdeck paths, descriptions and normal/filtered kind (filtered exports currently rejected).
- Note IDs, GUIDs, model IDs, ordered named fields with exact text/HTML, sorted content tags, nonempty opaque note `data`, and media references.
- Card IDs, note relationships, content deck IDs, ordinals and template relationships. Cloze card ordinals remain distinct even when they share template zero.
- Note types, field names/order and available merge IDs, field presentation settings, templates, browser templates, CSS, LaTeX settings and card-generation requirements. Unknown JSON extension properties are retained rather than silently dropped.
- Media filenames, byte sizes and SHA-256 of actual decompressed bytes. Same-name replacements therefore show as changes, even when field references do not change.

Excluded or normalized:

- Review logs, learning/review scheduling, due dates, intervals, ease, repetitions, lapses, queues, flags, deck study limits, deck option presets, UI collapsed state, editor sticky preferences, sync counters and collection runtime metadata.
- `marked` and `leech` tags, because they are study-state tags; other tags remain exact and sorted.
- Note/model modification times and package hash are excluded from content snapshots. They are used separately for release provenance and import-age checks.
- Model default target deck for adding new notes, transient tags/version caches, and redundant storage checksums are excluded. Template-specific deck overrides are retained.
- Filtered-deck origin is normalized to the original content deck when available. Filtered deck definitions are rejected instead of producing an incomplete release interpretation.

No HTML whitespace rewriting is applied to snapshot field contents. Cosmetic HTML differences remain visible because they can change rendering. Media reference detection handles literal HTML `src`, `data`, `poster`, CSS `url()` and `[sound:]`; remote/data URLs are excluded. Dynamic JavaScript references, template-computed names and implicit LaTeX-generated files cannot be resolved exhaustively. All packaged media still receives a checksum.

## Matching notes and cards

1. Match unique **GUIDs** first. Anki's packaged-deck importer uses GUID correspondence; numeric note IDs can be remapped by import and are not trusted alone.
2. For remaining notes, match unique exact field content within the same model ID. Only line endings and edge whitespace are normalized for this fallback.
3. For remaining notes, match a unique identical first field within the same model ID when it is at least 24 characters long. This conservative fallback can recognize a changed answer when the question remains unchanged.
4. Report duplicate-key ambiguity instead of selecting an arbitrary note. Unresolved notes stay in unmatched added/removed lists, with provisional counts and a warning. Duplicate GUIDs cause FAIL. No fuzzy semantic matching is attempted.

Fallback matching is an **audit inference**, never proof of update compatibility. Every fallback is identified in the detailed report and triggers a warning. Short keys, fully rewritten notes, and simultaneous model-ID/content changes may remain unmatched. Retained GUIDs take precedence even when all fields changed. Numeric ID/GUID/model changes and reused numeric IDs are reported separately.

Cards are paired by matched note plus ordinal, so regenerated numeric card IDs do not automatically become deletion/addition pairs. Template/schema changes trigger warnings; ordinal-based counts require review if templates were reordered. Added/deleted cloze ordinals count as card additions/removals. Updated-card totals count distinct retained cards affected by note fields/tags/type, model/template definition, referenced media byte changes, or deck placement. They are not a forecast of Anki's import summary. A deck move alone can update a card without modifying its note.

## PASS, WARNING and FAIL

- **PASS**: the specific check succeeded. It is not a blanket guarantee that every user's collection will import identically.
- **WARNING**: review is required. Examples include deck/model changes, deletions, content-only matches, identifier changes, ambiguous matches, missing literal media references, absent field/template merge IDs, stale changed-note timestamps and the general limits of static import prediction. Text outputs are generated, but remain candidates by default.
- **FAIL**: stop, exit 2 and do not generate release artifacts. Examples include unknown formats/schemas, invalid or corrupt packages, missing manifest entries, checksum mismatches, inconsistent note/card references, duplicate GUIDs, empty decks, no shared GUID lineage, reused dates for different packages, or conflicting snapshots.

Normal success, including reviewed-needed warnings, exits 0. `--strict` treats warnings as blocking and exits 2. The generic import-outcome limitation is deliberately a warning, so current static audits will require review in strict mode. `--check-only` performs no release-output writes. Format failures print a useful diagnostic and stop rather than falling back to the compatibility database.

The checker validates note counts, card counts, media counts, internal deck definitions, model definitions, identifier continuity and whether changed notes/models have newer modification times. Default Anki imports may skip notes if users have newer local edits or select Never update. Model changes/merging and Anki version matter. Field/template merge IDs were introduced in newer Anki; older definitions can lack them and merging may fall back to names. Missing notes/cards in an update package should **not** be described as automatically deleted from existing user collections.

Before distributing a structurally changed deck, you can manually test in a disposable separate Anki profile, first importing the published baseline and then the candidate using representative options. This tool does not perform that test and never touches your live collection.

## Outputs, history and idempotency

| File | Purpose |
| --- | --- |
| `snapshots/<date>.json` | Immutable normalized educational content and structure. |
| `reports/<old>_to_<new>.md` | Human audit: checks, identities, complete added/removed notes, every changed field before/after, tags, cards, media and structural changes. |
| `reports/<old>_to_<new>.checks.json` | Compact machine-readable checks and counts. |
| `releases.json` | Internal release registry, source SHA-256 provenance and retained history. |
| `CHANGELOG.md` | User-facing quantitative history with optional reviewed editorial bullets. |
| `website/releases.json` | Compact public release history, totals, deltas, status and What's New; no raw notes, local paths or internal IDs. |
| `website/whats-new.md` | Newest recorded release, labeled as candidate until explicitly marked published. |

Repeated extraction produces identical snapshot bytes. Repeating the same release command produces identical output bytes, without duplicate records or meaningless filename suffixes. A date is bound to one source package checksum. Different bytes under the same date are rejected even if the visible content appears equivalent: use a new date for a genuinely new build, or restore the original untouched package. Snapshots are never silently replaced with different content. Past reports and snapshots are retained.

Future comparisons append a new date, preserve previous release records, and mark the explicitly selected baseline as published. Re-running an older recorded comparison does not make it the newest website release. Latest output is selected by date. If you need multiple release builds on one date, that is not currently supported; do not edit snapshots or bypass the history guard.

Changelog sections use `<!-- crabs:release:... -->` markers. Generated text within a marker pair is replaced deterministically. Put manual prose outside those markers, or use `--notes-file` to store reviewed public bullets in the registry and website outputs. Automatic bullets report measured changes only. The tool does not infer clinical corrections or semantic topic claims from counts. Imported manual historical sections outside markers are preserved.

## Website integration later

No website repository or deployment is changed. The Google Form remains the download gateway; package binaries never appear in website data. A future website build can copy/fetch only `website/releases.json` and render its history. Distinguish `latest_release_date` (newest candidate or published entry) from `latest_published_release_date`. For a live download page, filter to `publication_status == "published"` and display that version. Never auto-advertise a candidate as downloadable.

Render the release date/version, total cards, public What's New bullets, previous version and full history. Once a user knows their installed version, they can compare it with the website's latest published date. Connect your existing Google Form URL and the final deployed changelog URL in the website itself. Neither URL was provided, so no download link was fabricated. The Markdown uses a repository-relative changelog link; adjust it when copying to another website route. No integration is tightly coupled to this codebase.

## Optional future version card

You can later create one informational note in your authoring Anki collection, such as `Crabs release: 2027-01-15`, and preserve its GUID, note type, field order and template on every release. Update the version field before exporting. Existing users could find that note in Browse and compare it with the website. Keep it clearly informational; users may suspend its card if desired. Its update remains subject to the same import settings/local edits as any note. Prefer one persistent note over creating a new version card each release. **No such note was added to either current package.**

## Future format changes and code layout

`crabs/reader.py` isolates ZIP, compression and SQLite support. `crabs/protobuf.py` strictly reads the small documented messages needed for metadata, media, deck kinds and schema-18 models. `crabs/compare.py` works only on normalized snapshots; `crabs/output.py` manages audit/public artifacts. `release.py` handles validation, dates, locking and writes. `snapshot.py` exposes extraction separately.

Supported package metadata versions are 1, 2 and 3. Legacy schema 11 is supported with `collection.anki2`/`collection.anki21`; modern schema 18 is supported with `collection.anki21b`. Missing metadata follows Anki's legacy filename selection. Unknown collection members, metadata versions, database versions, protobuf fields/wire types and filtered-deck formats fail closed. The adapter does not claim support for all future Anki versions. Update the reader and regression tests when a new format arrives; no need to rewrite release/changelog logic. Database and manifest decompression have 1 GiB and 64 MiB limits respectively.

Format and import references consulted for this implementation:

- [Anki package metadata selection](https://github.com/ankitects/anki/blob/main/rslib/src/import_export/package/meta.rs)
- [Anki package/media message definitions](https://github.com/ankitects/anki/blob/main/proto/anki/import_export.proto)
- [Anki note-type definitions](https://github.com/ankitects/anki/blob/main/proto/anki/notetypes.proto)
- [Anki deck definitions](https://github.com/ankitects/anki/blob/main/proto/anki/decks.proto)
- [Anki package note importing](https://github.com/ankitects/anki/blob/main/rslib/src/import_export/package/apkg/import/notes.rs)
- [Anki manual: updating packaged decks](https://docs.ankiweb.net/importing/packaged-decks.html#updating)

## Complete release checklist

1. Export the updated deck; preserve the previous published export. Keep both outside this repository.
2. Run the dated comparison command above. On FAIL, fix the identified problem; do not treat partial output from an interrupted run as a completed release.
3. Review safety checks, full audit, additions/deletions, model/deck changes, before/after fields and compatibility warnings.
4. Review or add public wording; rerun with `--notes-file` if needed. Avoid unsupported semantic claims.
5. Inspect `git diff`, `git status --short`, snapshots and website files. The larger snapshots/report are intended for local inspection as well as Git; GitHub may truncate large rendered diffs.
6. **Stop for your approval before committing or pushing.** After approving, stage only the reviewed text/code files, run `.venv/bin/python git_safety.py` again, and inspect `git diff --cached --stat` and `git diff --cached --name-only`. The guard permits only approved UTF-8 text/code types in Git's index and rejects binary data and extraction/media paths. It never stages anything itself.
7. Commit/push only when you explicitly choose to. Upload the original untouched candidate through the existing Google Form/download workflow. Mark local metadata published only after the release is actually distributed; review/commit those text changes as well.
8. Keep that original candidate as the baseline for the next export. Run the same workflow with new paths/dates; no source-code edits are required.

`.gitignore` excludes packages, extracted Anki databases, media, temporary files, the environment, Python caches and macOS metadata. Ignore rules do not remove already tracked files; the separate index guard checks that case. Nothing in this repository automates Git commit/push or public distribution.
