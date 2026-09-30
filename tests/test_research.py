import json
import tempfile
import unittest
from pathlib import Path

from crabs.research import ResearchRunner, load_style_guide, validate_result


def candidate(extra='Existing context'):
    text = 'Pediatric OSA severity is {{c1::AHI ≥10::children}} events/hour'
    return {'supersedes_finding_id': 'old-finding',
            'finding': {'guid': 'osa-guid', 'field': 'Text', 'original': text,
                        'category': 'threshold', 'severity': 'moderate',
                        'confidence': 'low', 'rationale': 'Threshold needs verification',
                        'evidence_status': 'needs_research', 'evidence': []},
            'note': {'guid': 'osa-guid', 'id': 1, 'model_id': 2, 'tags': [], 'media': [],
                     'fields': [{'name': 'Text', 'value': text},
                                {'name': 'Extra', 'value': extra}]}}


def result(c, changes=None):
    changes = changes if changes is not None else [{
        'field': 'Text', 'original': c['finding']['original'],
        'final': c['finding']['original'].replace('AHI ≥10', 'oAHI ≥10')}]
    return {'guid': c['finding']['guid'], 'field': c['finding']['field'],
            'original': c['finding']['original'], 'category': c['finding']['category'],
            'severity': c['finding']['severity'], 'confidence': 'high',
            'rationale': 'Current pediatric criteria use obstructive AHI.',
            'evidence_status': 'supported', 'evidence': [{
                'title': 'Guideline', 'organization_authors': 'Society',
                'publication': 'Journal', 'year': 2024, 'url': 'https://example.org/guideline',
                'doi': '', 'pmid': '', 'locator': 'Table 1', 'accessed': '2026-09-29',
                'support': 'Defines severe pediatric OSA.'}],
            'researched_conclusion': 'Use oAHI and retain the pediatric threshold.',
            'disposition': 'revise', 'remaining_uncertainty': '',
            'proposed_changes': changes, 'research_attempted': True,
            'research_limitations': ''}


class FakeProvider:
    def __init__(self): self.calls = 0
    def generate(self, instructions, item):
        self.calls += 1
        assert 'One audited note remains one note' in instructions
        return result(item)


class ResearchTests(unittest.TestCase):
    def test_style_guide_is_loaded_and_has_generation_constraints(self):
        guide = load_style_guide()
        for phrase in ('One audited note remains one note', 'Never put clozes in Extra',
                       '::timeframe', 'context does the learner need'):
            self.assertIn(phrase, guide)

    def test_existing_note_only_and_text_extra_contract(self):
        c = candidate()
        both = result(c, [
            {'field': 'Text', 'original': c['finding']['original'],
             'final': c['finding']['original'].replace('AHI ≥10', 'oAHI ≥10')},
            {'field': 'Extra', 'original': 'Existing context',
             'final': 'Severity is interpreted with symptoms, examination, and PSG context.'}])
        validated = validate_result(c, both)
        self.assertEqual([x['field'] for x in validated['proposed_changes']], ['Text', 'Extra'])
        bad = result(c, [{'field': 'New card', 'original': '', 'final': 'Do not create'}])
        with self.assertRaisesRegex(ValueError, 'nonexisting'):
            validate_result(c, bad)
        forbidden = result(c); forbidden['new_cards'] = [{'Text': 'Never'}]
        with self.assertRaisesRegex(ValueError, 'notes/cards/tags are forbidden'):
            validate_result(c, forbidden)

    def test_extra_only_and_no_extra_clozes(self):
        c = candidate()
        extra = result(c, [{'field': 'Extra', 'original': 'Existing context',
                            'final': 'Concise clinical context.'}])
        self.assertEqual(validate_result(c, extra)['proposed_changes'][0]['field'], 'Extra')
        extra['proposed_changes'][0]['final'] = '{{c1::Forbidden}}'
        with self.assertRaisesRegex(ValueError, 'Extra may not contain clozes'):
            validate_result(c, extra)

    def test_unresolved_requires_real_attempt_and_no_proposal(self):
        c = candidate(); unresolved = result(c, [])
        unresolved.update(evidence_status='needs_research', evidence=[], disposition=None,
                          confidence='medium', research_limitations='No population-specific source found.')
        self.assertIsNone(validate_result(c, unresolved)['disposition'])
        unresolved['research_attempted'] = False
        with self.assertRaisesRegex(ValueError, 'attempt research'):
            validate_result(c, unresolved)

    def test_resumable_idempotent_checkpoint_and_no_approval_or_deck_write(self):
        with tempfile.TemporaryDirectory() as td:
            checkpoint = Path(td)/'run.jsonl'; provider = FakeProvider()
            work = {'schema': 3, 'source_sha256': 'source', 'reprocess': True,
                    'candidates': [candidate()]}
            runner = ResearchRunner(provider)
            first = runner.run(work, checkpoint); second = runner.run(work, checkpoint)
            self.assertEqual(provider.calls, 1)
            self.assertEqual(first['findings'], second['findings'])
            self.assertNotIn('approved', json.dumps(first).lower())
            self.assertEqual(len(checkpoint.read_text().splitlines()), 1)

    def test_hennebert_style_supported_result_cannot_end_null(self):
        c = candidate(); supported = result(c, [])
        with self.assertRaisesRegex(ValueError, 'revise requires changes'):
            validate_result(c, supported)


if __name__ == '__main__': unittest.main()
