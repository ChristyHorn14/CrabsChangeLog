"""Resumable evidence-retrieval and synthesis runner for existing CRABS notes."""
import hashlib
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .maintainer import CATEGORIES, DISPOSITIONS, SEVERITIES, guard_edit, require

DEFAULT_STYLE_GUIDE = Path(__file__).resolve().parents[1] / 'docs' / 'crabs-card-style.md'
DEFAULT_PROMPT = Path(__file__).resolve().parents[1] / 'docs' / 'evidence-backed-audit-prompt.txt'


def load_style_guide(path=DEFAULT_STYLE_GUIDE):
    text = Path(path).read_text(encoding='utf-8').strip()
    require('One audited note remains one note' in text, 'Style guide lacks existing-note-only constraint')
    require('Never put clozes in Extra' in text, 'Style guide lacks Extra cloze constraint')
    return text


def stable_key(candidate, source_sha256):
    identity = {'source_sha256': source_sha256,
                'supersedes_finding_id': candidate.get('supersedes_finding_id'),
                'finding': candidate['finding'], 'note': candidate['note']}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def response_schema():
    evidence = {'type': 'object', 'additionalProperties': False,
                'properties': {
                    'title': {'type': 'string'}, 'organization_authors': {'type': 'string'},
                    'publication': {'type': 'string'}, 'year': {'type': ['integer', 'string']},
                    'url': {'type': 'string'}, 'doi': {'type': 'string'},
                    'pmid': {'type': 'string'}, 'locator': {'type': 'string'},
                    'accessed': {'type': 'string'}, 'support': {'type': 'string'}},
                'required': ['title', 'organization_authors', 'publication', 'year', 'url',
                             'doi', 'pmid', 'locator', 'accessed', 'support']}
    change = {'type': 'object', 'additionalProperties': False,
              'properties': {'field': {'type': 'string'}, 'original': {'type': 'string'},
                             'final': {'type': 'string'}},
              'required': ['field', 'original', 'final']}
    return {'type': 'object', 'additionalProperties': False,
            'properties': {
                'guid': {'type': 'string'}, 'field': {'type': 'string'},
                'original': {'type': 'string'}, 'category': {'type': 'string', 'enum': list(CATEGORIES)},
                'severity': {'type': 'string', 'enum': list(SEVERITIES)},
                'confidence': {'type': 'string', 'enum': ['low', 'medium', 'high']},
                'rationale': {'type': 'string'},
                'evidence_status': {'type': 'string', 'enum': ['supported', 'needs_research']},
                'evidence': {'type': 'array', 'items': evidence},
                'researched_conclusion': {'type': 'string'},
                'disposition': {'type': ['string', 'null'], 'enum': list(DISPOSITIONS) + [None]},
                'remaining_uncertainty': {'type': 'string'},
                'proposed_changes': {'type': 'array', 'items': change},
                'research_attempted': {'type': 'boolean'},
                'research_limitations': {'type': 'string'}},
            'required': ['guid', 'field', 'original', 'category', 'severity', 'confidence',
                         'rationale', 'evidence_status', 'evidence', 'researched_conclusion',
                         'disposition', 'remaining_uncertainty', 'proposed_changes',
                         'research_attempted', 'research_limitations']}


class OpenAIResponsesProvider:
    """Small Responses API client; web search and JSON schema are enforced server-side."""
    endpoint = 'https://api.openai.com/v1/responses'

    def __init__(self, model, api_key=None, timeout=300):
        self.model = model
        self.api_key = api_key or os.environ.get('OPENAI_API_KEY')
        require(bool(self.api_key), 'OPENAI_API_KEY is required for evidence-backed research')
        self.timeout = timeout

    def generate(self, instructions, candidate):
        body = {'model': self.model, 'instructions': instructions,
                'input': json.dumps(candidate, ensure_ascii=False),
                'tools': [{'type': 'web_search'}],
                'text': {'format': {'type': 'json_schema', 'name': 'crabs_evidence_finding',
                                    'strict': True, 'schema': response_schema()}}}
        request = urllib.request.Request(self.endpoint,
            data=json.dumps(body).encode(), method='POST',
            headers={'Authorization': 'Bearer ' + self.api_key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors='replace')[:2000]
            raise RuntimeError(f'Research API failed ({exc.code}): {detail}') from exc
        text = payload.get('output_text')
        if not text:
            for item in payload.get('output', []):
                for content in item.get('content', []):
                    if content.get('type') in ('output_text', 'text') and content.get('text'):
                        text = content['text']; break
                if text: break
        require(bool(text), 'Research API returned no structured output')
        return json.loads(text)


def validate_result(candidate, result):
    result = dict(result)
    finding = candidate['finding']; note = candidate['note']
    fields = {f['name']: f['value'] for f in note['fields']}
    expected = {'guid', 'field', 'original', 'category', 'severity', 'confidence',
                'rationale', 'evidence_status', 'evidence', 'researched_conclusion',
                'disposition', 'remaining_uncertainty', 'proposed_changes',
                'research_attempted', 'research_limitations'}
    require(set(result) == expected,
            'Runner output may contain one finding only; notes/cards/tags are forbidden')
    require(result['guid'] == finding['guid'], 'Runner changed finding GUID')
    require(result['field'] == finding['field'] and result['original'] == finding['original'],
            'Runner changed finding identity/original')
    require(result['field'] in fields, 'Runner targeted an unknown field')
    require(result['category'] in CATEGORIES and result['severity'] in SEVERITIES,
            'Runner returned invalid category/severity')
    require(result['confidence'] in ('low', 'medium', 'high'), 'Runner returned invalid confidence')
    require(result['evidence_status'] in ('supported', 'needs_research'), 'Invalid evidence status')
    require(result.get('research_attempted') is True, 'Runner must attempt research')
    require(bool(result.get('researched_conclusion')) and bool(result.get('rationale')),
            'Runner omitted conclusion/rationale')
    changes = result.get('proposed_changes')
    require(isinstance(changes, list), 'Runner omitted proposed_changes')
    require(len({c.get('field') for c in changes}) == len(changes), 'Duplicate field proposal')
    if result['evidence_status'] == 'needs_research':
        require(not changes and result.get('disposition') is None,
                'Unresolved research may not fabricate a disposition or patch')
        require(result['confidence'] != 'high' and bool(result.get('research_limitations')),
                'Unresolved research requires limitations and non-high confidence')
    else:
        require(result.get('disposition') in DISPOSITIONS, 'Supported result needs a disposition')
        require(bool(result.get('evidence')), 'Supported result needs retrieved evidence')
        require((result['disposition'] == 'revise') == bool(changes),
                'Only revise may contain changes, and revise requires changes')
    for source in result.get('evidence', []):
        require(all(source.get(k) for k in ('title', 'organization_authors', 'publication', 'year', 'url')),
                'Incomplete evidence citation')
        require(source['url'].startswith('https://'), 'Evidence URL must be HTTPS')
    for change in changes:
        require(set(change) == {'field', 'original', 'final'}, 'Invalid proposed change shape')
        require(change['field'] in fields and change['original'] == fields[change['field']],
                'Runner changed a nonexisting/stale field')
        if change['field'].lower() == 'extra':
            require('{{c' not in change['final'].lower(), 'Extra may not contain clozes')
        guard_edit(change['original'], change['final'])
    result['supersedes_finding_id'] = candidate.get('supersedes_finding_id')
    return result


class ResearchRunner:
    def __init__(self, provider, style_guide=DEFAULT_STYLE_GUIDE, prompt=DEFAULT_PROMPT):
        self.provider = provider
        self.style = load_style_guide(style_guide)
        self.prompt = Path(prompt).read_text(encoding='utf-8').strip()

    @property
    def instructions(self):
        return (self.prompt + '\n\nAUTHORITATIVE CRABS CARD STYLE GUIDE\n' + self.style +
                '\n\nUse web search for every candidate. Return one finding object only. '
                'Every cited source must have actually been retrieved. Do not output notes, cards, tags, approvals, or patches. '
                'Preserve the existing HTML/media token sequence and cloze ordinal multiset in every final field value.')

    def run(self, workload, checkpoint_path, limit=None):
        require(workload.get('schema') == 3, 'Research workload must use schema 3')
        candidates = workload['candidates']; checkpoint_path = Path(checkpoint_path)
        completed = {}
        if checkpoint_path.exists():
            for line in checkpoint_path.read_text(encoding='utf-8').splitlines():
                row = json.loads(line); completed[row['key']] = row['result']
        processed = 0
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        for candidate in candidates:
            key = stable_key(candidate, workload['source_sha256'])
            if key in completed: continue
            if limit is not None and processed >= limit: break
            result = validate_result(candidate, self.provider.generate(self.instructions, candidate))
            with checkpoint_path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'key': key, 'result': result}, ensure_ascii=False,
                                        sort_keys=True, separators=(',', ':')) + '\n')
                stream.flush(); os.fsync(stream.fileno())
            completed[key] = result; processed += 1
        ordered = []
        for candidate in candidates:
            key = stable_key(candidate, workload['source_sha256'])
            if key in completed: ordered.append(completed[key])
        return {'schema': 3, 'audit_stage': 'evidence_backed',
                'source_sha256': workload['source_sha256'],
                'scope': workload.get('scope', 'Pediatric Otolaryngology'),
                'sample_guids': (workload.get('sample_guids') or
                                 list(dict.fromkeys(f['guid'] for f in ordered))),
                'audit_version': 'evidence-runner-' + datetime.now(timezone.utc).date().isoformat(),
                'author': 'CRABS evidence runner; human review required',
                'reprocess': workload.get('reprocess') is True,
                'findings': ordered, 'candidate_count': len(candidates),
                'completed_count': len(ordered)}


def workload_from_bundle(store, bundle):
    """Enrich future audit findings with immutable note context before research."""
    export = store.export(); require(bundle['source_sha256'] == export['id'], 'Audit targets another export')
    notes = {n['guid']: n for n in export['snapshot']['notes'].values()}
    candidates = []
    for finding in bundle['findings']:
        require(finding['guid'] in notes, 'Finding note is absent from current export')
        if finding.get('evidence_status') == 'editorial':
            continue
        candidates.append({'finding': finding, 'note': notes[finding['guid']]})
    return {'schema': 3, 'task': 'evidence_backed_future', 'reprocess': False,
            'source_sha256': export['id'], 'source_version': export['version'],
            'scope': bundle.get('scope', 'Pediatric Otolaryngology'),
            'sample_guids': bundle['sample_guids'],
            'candidate_count': len(candidates), 'candidates': candidates}
