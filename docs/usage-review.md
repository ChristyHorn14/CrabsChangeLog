# Usage documentation review — September 20, 2026

Human-authored maintainer record; not generated. The original usage write-up is embedded in the deck index note (numeric note ID 1683516122526) in both stored snapshots and appears in the detailed audit when changed. No standalone usage guide was found in either repository. The index note itself has not been edited.

## Still supported by the current hierarchy

The retention-first philosophy, learning from the relevant source before unsuspending cards, and organization by resource, specialty, procedure and anatomy remain suitable explanatory documentation. `Crabs::Sub-I`, `Crabs::Pimped`, `Crabs::extra_anatomy`, `Crabs::Residency`, `Crabs::Index`, `Crabs::Resources`, `Crabs::Pasha`, and `Crabs::AAOHNS_PrimaryCareOtolaryngology` are present (including implicit parent branches).

## Stale paths and examples

| Historical wording | Current observation | Interpretation |
| --- | --- | --- |
| `Crabs::Elective` | `Crabs::elective` | Case differs; preserve exported spelling. |
| `Secrets_ENT` | `Crabs::secrets_ent` | Historical root is absent; current resource branch is nested. |
| `Crabs::Specialty::HeadandNeck` | `Crabs::Specialty::HN` | Old path absent; likely counterpart, not proof of a rename. |
| `Crabs::Specialty::PediatricOto` | `Crabs::Specialty::Peds` | Old path absent; likely counterpart. |
| `Crabs::Specialty::Plastics` | `Crabs::Specialty::FacialPlastics` | Old path absent; likely counterpart. |
| `Crabs::"name of subspecialty"` | `Crabs::Specialty::…` | Generic historical instruction omits a hierarchy level. |
| `DrugInducedSleepEndoscopy(DISE)` | `DrugInducedSleepEndoscopyDISE` | Parentheses differ under Procedures. |
| `FibulaFreeFlap(FFF)` | `FibulaFreeFlap-FFF` | Punctuation differs under Procedures::Flaps::FreeFlaps. |
| `OssicularChainReconstruction(OCR)` | `OssicularChainReconstruction-OCR` | Punctuation differs under Procedures. |
| `TransoralRoboticTonsil(TORS)` | `TransoralRoboticTonsil-TORS` | Punctuation differs under Procedures. |
| `Crabs::Procedure::MandibleFractures` | `Crabs::procedures::mandiblefractures` | Singular/plural, casing and spelling differ. |
| `Crabs::Procedures:: Dacryocystorhinostomy` | `Crabs::Procedures::Dacryocystorhinostomy` | Historical embedded space makes the example unreliable. |

These are observed mismatches, not a migration map. June/September comparison alone cannot prove historical renames. The malformed combined UPPP/velopharyngeal example and filtered-deck expressions should not be copied into new documentation. The old fixed Spanish card count should be replaced by the generated explorer counts.

## Author decisions — TODO

- TODO: Confirm current elective versus Sub-I sequencing and whether the historical first-pass/second-pass resource recommendations and editions remain intended. The public guide keeps the general philosophy without asserting a curriculum.
- TODO: Explain the expanded `Crabs::Residency` hierarchy and the intended relationship between `Specialty::Otology` and `Specialty::OtologyNeurotology`.
- TODO: Confirm how `Crabs::duplicates_didnt_study` should be used. The old blanket low-yield/duplicate description has not been promoted to a current recommendation.
- TODO: Review `Crabs::2023NCCN` and how its year should be explained. A tag name does not establish current clinical accuracy.
- TODO: Review `Crabs::Spanish`, `Crabs::Other`, the standalone tags (for example `Anatomy`, `Severe`, `include`) and the literal `…` root. Do not hide or merge them automatically.
- TODO: Decide whether case variants `Crabs::Procedures` and `Crabs::procedures` need eventual authoring cleanup. No deck changes were made.
- TODO: Validate procedure-specific reading/video links and any filtered-deck workflow before publishing more detailed case-preparation recommendations.
- TODO: Record future manual import tests with Anki version, import options and observed summary. The September test is owner-reported; the older verification report covers static tests only.

Maintain public explanatory text in `how-to-use.md` and `updating.md`. On each release compare their referenced paths with the generated explorer. Never infer educational recommendations from tag counts.
