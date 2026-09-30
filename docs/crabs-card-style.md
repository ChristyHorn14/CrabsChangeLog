# Crabs card style guide

This file is the version-controlled editorial contract for evidence-backed audit proposals. The research runner loads it verbatim into every generation request. It governs proposals for existing notes; it does not authorize creating, deleting, approving, or applying cards.

## Purpose and scope

- Write concise, clinically useful ENT spaced-repetition material that teaches one coherent fact or decision point rather than isolated trivia.
- Improve the existing note aggressively when evidence and pedagogy support it. Do not preserve weak wording, an outdated frame, or a poor retrieval target merely for fidelity.
- One audited note remains one note. Never create another note or card. When a concept should be split and the existing note cannot responsibly contain it, use the advisory `split` disposition and explain the recommendation. Do not fabricate a field patch for the missing card.
- Prefer `revise` with exact complete field values when a responsible correction is supported. Reserve proposal-less `needs_research` for genuine unresolved uncertainty after a documented research attempt.
- Do not change tags unless the audited correction truly requires it. The current proposal contract is field-only, so tag changes remain advisory. Preserve staging hierarchies, tags, and staging semantics.

## Text and clozes

- Use the note's existing model and fields. Do not add fields, notes, or cards.
- Crabs usually uses cloze2 notes. Preserve valid Anki cloze syntax and the existing set of cloze ordinals so the proposal cannot generate or remove cards.
- Keep the prompt focused. Avoid overstuffed multi-fact prompts. Use a short clinical frame or vignette when it makes a list or decision point understandable.
- Prefer concrete evidence-supported numbers over vague words such as “small.”
- Use established hints when appropriate: `::timeframe` for time answers; `::fast/slow`, `::children/adults`, `::size`, `::sites`, and `::3` for the established corresponding answer types. Do not invent arbitrary hints.
- Keep units and symbols outside the cloze when that matches the deck convention: `%`, measurement units, minutes, years, artery, exposure, mutation symbols, and benign/malignant generally remain visible.
- Separate adult and pediatric facts conceptually when needed. Because no new note may be created, revise around the existing note's intended population or use advisory `split` when one note cannot responsibly teach both.

## Extra

Use this heuristic: **What brief context does the learner need around this fact so they understand it rather than merely memorize an isolated sentence?**

- Extra prioritizes concise educational context: conceptual framing, clinically useful nuance, mechanism when it truly helps, and distinctions that prevent misconception.
- Clarify rather than merely repeat Text. Usually a few concise sentences are enough.
- Never put clozes in Extra.
- Preserve useful existing Extra content unless evidence or pedagogy supports changing or removing it.
- Avoid bloated “why” explanations, mini-textbook chapters, and academic filler such as “in the source cohort” unless it is necessary to interpret the claim.
- Sources and links are welcome when useful, especially for corrected or evidence-sensitive claims, but Extra must not become a citation dump. Keep the complete evidence trail in audit metadata.

## Evidence and synthesis

- Prefer current specialty guidelines or consensus statements and authoritative references, followed by systematic/high-quality reviews and relevant primary literature. Use weaker tertiary material only when necessary and identify the limitation.
- Never fabricate a citation, URL, quotation, or result. Evidence metadata must describe a source actually retrieved during this run.
- Distinguish direct evidence from synthesis or inference. When evidence is mixed, propose the best defensible qualified wording and disclose uncertainty.
- Choose the best disposition for the existing note: `retain`, `revise`, `replace`, `delete`, or advisory `split`. `replace` and `delete` are recommendations under the current non-patch semantics; they do not alter the deck.
- A finding is not complete merely because a defect and a source were identified. When evidence supports a correction, supply exact complete Text and/or Extra values and a concise rationale.

