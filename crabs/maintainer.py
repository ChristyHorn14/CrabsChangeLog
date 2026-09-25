"""Private, append-only proposal/review history over the release reader's notes."""
import copy
import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from .reader import read_package, media_refs

SPECIALTY = 'Pediatric Otolaryngology'
STATUSES = ('awaiting_review', 'approved', 'rejected', 'deferred')
CATEGORIES = ('clinical_accuracy', 'outdated_recommendation', 'outdated_guideline',
              'threshold', 'dose', 'classification', 'staging', 'diagnostic_criteria',
              'oversimplification', 'ambiguous_wording', 'contradiction', 'redundancy',
              'card_construction', 'cloze_construction', 'answer_leakage',
              'excessive_information', 'low_value', 'extra_field', 'organization')
SEVERITIES = ('low', 'moderate', 'high', 'critical')


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def checksum(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def by_guid(snapshot):
    result = {}
    for key, n in snapshot['notes'].items():
        require(str(n['id']) == key and n['guid'] and n['guid'] not in result,
                'Empty/duplicate GUID or inconsistent numeric note ID')
        require(len({f['name'] for f in n['fields']}) == len(n['fields']), 'Duplicate field names')
        result[n['guid']] = n
    return result


def excluded(snapshot, note):
    m = snapshot['models'][str(note['model_id'])]
    name = re.sub(r'[^a-z]', '', m['name'].lower())
    fields = {f['name'].lower() for f in m['flds']}
    templates = encoded(m.get('tmpls', [])).lower()
    return ('imageocclusion' in name or m.get('originalStockKind') == 6
            or {'question mask', 'answer mask'} <= fields
            or {'occlusion', 'image'} <= fields or 'image-occlusion' in templates)


def pediatric(note):
    return any(t == 'Crabs::Specialty::Peds' or
               t.startswith('Crabs::Pasha::Chapter9PediatricOtolaryngology::')
               for t in note['tags'])


def fingerprint(snapshot, note):
    # Intentionally narrow cosmetic rule: only attribute-free span wrappers.
    # Every other field byte, cloze, URL, media byte, and model definition counts.
    fields = [{**f, 'value': re.sub(r'</?span>', '', f['value'], flags=re.I)} for f in note['fields']]
    return checksum({'rules': 1, 'fields': fields,
                     'model': snapshot['models'][str(note['model_id'])],
                     'media': {m: snapshot['media'].get(m) for m in note['media']}})


def guard_edit(old, new):
    require(isinstance(new, str) and new != old, 'Replacement must be different text')
    depth = 0
    for match in re.finditer(r'\{\{c[1-9]\d*::|\{\{|\}\}', new):
        token = match.group()
        if token.startswith('{{c'):
            depth += 1
        elif token == '}}':
            depth -= 1
            require(depth >= 0, 'Unbalanced cloze syntax')
        else:
            raise ValueError('Unsupported or malformed cloze/template syntax')
    require(depth == 0, 'Unbalanced cloze syntax')
    require('\x1f' not in new and '\x00' not in new, 'Invalid field control character')
    # Conservatively prohibit any markup/media/card-generation changes in pilot.
    tokens = lambda v: re.findall(r'<[^>]*>|\[sound:[^\]]*\]|\{\{c\d+::|\}\}', v)
    require(tokens(old) == tokens(new), 'Pilot preserves exact HTML, media tags and cloze delimiters/ordinals')
    require(media_refs(old) == media_refs(new), 'Media references must remain unchanged')
    require(Counter(re.findall(r'\{\{c\d+::', new)) == Counter(re.findall(r'\{\{c\d+::', old)), 'Cloze mismatch')


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS exports(id TEXT PRIMARY KEY, path TEXT, version TEXT, created TEXT, snapshot TEXT);
        CREATE TABLE IF NOT EXISTS audits(id INTEGER PRIMARY KEY, export_id TEXT REFERENCES exports(id),
          guid TEXT, fingerprint TEXT, version TEXT, created TEXT, outcome TEXT, UNIQUE(export_id,guid,version));
        CREATE TABLE IF NOT EXISTS findings(id TEXT PRIMARY KEY, export_id TEXT REFERENCES exports(id), payload TEXT);
        CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY, finding_id TEXT REFERENCES findings(id),
          status TEXT, final TEXT, reviewer TEXT, comment TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS applications(id TEXT PRIMARY KEY, payload TEXT);
        ''')
        for table in ('exports', 'audits', 'findings', 'reviews', 'applications'):
            for action in ('UPDATE', 'DELETE'):
                self.db.execute(f'''CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action}
                 BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'History is append-only'); END''')
        self.db.commit()

    def close(self):
        self.db.close()

    def ingest(self, path, version):
        snapshot, provenance = read_package(path)
        by_guid(snapshot)
        key = provenance['sha256']
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO exports VALUES(?,?,?,?,?)',
                            (key, str(Path(path).resolve()), version, now(), encoded(snapshot)))
        return key

    def export(self, key=None):
        row = (self.db.execute('SELECT * FROM exports WHERE id=?', (key,)).fetchone() if key else
               self.db.execute('SELECT * FROM exports ORDER BY rowid DESC LIMIT 1').fetchone())
        require(row is not None, 'Import a deck export first')
        return dict(row) | {'snapshot': json.loads(row['snapshot'])}

    def coverage(self, key=None):
        export = self.export(key); s = export['snapshot']; states = {}
        previous = self.db.execute('SELECT snapshot FROM exports WHERE rowid < (SELECT rowid FROM exports WHERE id=?)', (export['id'],)).fetchall()
        seen = {n['guid'] for row in previous for n in json.loads(row[0])['notes'].values()}
        for guid, n in by_guid(s).items():
            if not pediatric(n):
                continue
            if excluded(s, n):
                states[guid] = 'excluded_image_occlusion'; continue
            audit = self.db.execute('SELECT * FROM audits WHERE guid=? ORDER BY id DESC LIMIT 1', (guid,)).fetchone()
            if audit:
                state = 'audited_unchanged' if audit['fingerprint'] == fingerprint(s, n) else 'modified_needs_reaudit'
            else:
                state = 'new_unaudited' if previous and guid not in seen else 'never_audited'
            states[guid] = state
        c = Counter(states.values()); total = len(states); excluded_count = c['excluded_image_occlusion']
        return {'source_version': export['version'], 'source_sha256': export['id'],
                'scope': SPECIALTY, 'total_notes': total, 'eligible_notes': total-excluded_count,
                'audited_eligible_notes': c['audited_unchanged'],
                'unaudited_eligible_notes': total-excluded_count-c['audited_unchanged'],
                'excluded_image_occlusion_notes': excluded_count, 'states': dict(c), 'notes': states,
                'meaning': 'Audited means reviewed for this limited pilot; no issue identified is not verified medically correct.'}

    def import_findings(self, bundle, key=None):
        export = self.export(key); s = export['snapshot']; notes = by_guid(s)
        require(bundle['source_sha256'] == export['id'], 'Proposals target another source package')
        guids = bundle['sample_guids']
        require(10 <= len(guids) <= 20 and len(set(guids)) == len(guids), 'Pilot requires 10–20 unique notes')
        for guid in guids:
            require(guid in notes and pediatric(notes[guid]) and not excluded(s, notes[guid]), 'Ineligible pilot note')
        findings = []; timestamp = now()
        for raw in bundle['findings']:
            f = copy.deepcopy(raw); guid = f['guid']
            require(guid in guids, 'Finding outside pilot')
            n = notes[guid]; values = {v['name']: v['value'] for v in n['fields']}
            require(f['field'] in values and f['original'] == values[f['field']], 'Stale original field')
            require(f['category'] in CATEGORIES and f['severity'] in SEVERITIES, 'Unknown category/severity')
            require(f['confidence'] in ('low', 'medium', 'high'), 'Unknown confidence')
            require(f['evidence_status'] in ('supported', 'editorial', 'needs_research'), 'Unknown evidence status')
            require(bool(f['rationale']), 'Rationale required')
            if f['evidence_status'] == 'supported':
                require(bool(f['evidence']), 'Evidence required')
            for evidence in f['evidence']:
                require(all(evidence.get(k) for k in ('title', 'organization_authors', 'publication', 'year', 'url')), 'Incomplete citation')
                require(evidence['url'].startswith('https://'), 'Evidence URL must be HTTPS')
            if f['replacement'] is not None:
                guard_edit(f['original'], f['replacement'])
            else:
                require(f['evidence_status'] == 'needs_research', 'Only research findings may omit replacement')
            f.update(note_id=n['id'], card_ids=[c['id'] for c in s['cards'].values() if c['note_id'] == n['id']],
                     specialty=SPECIALTY, subspecialty=next((t.split('::')[-1] for t in n['tags'] if 'Chapter9' in t), SPECIALTY),
                     source_deck_version=export['version'], source_sha256=export['id'],
                     audit_version=bundle['audit_version'], note_fingerprint=fingerprint(s, n),
                     author=bundle.get('author', 'AI proposal'))
            # Source release/date are excluded: identical rejected proposals do not reappear on re-export.
            identity = {k: v for k, v in f.items() if k not in ('source_deck_version', 'source_sha256', 'note_id', 'card_ids')}
            f['id'] = checksum(identity); f['audit_date'] = timestamp
            findings.append(f)
        with self.db:
            for f in findings:
                self.db.execute('INSERT OR IGNORE INTO findings VALUES(?,?,?)', (f['id'], export['id'], encoded(f)))
            for guid in guids:
                outcome = 'proposals' if any(f['guid'] == guid for f in findings) else 'no_issue_identified'
                self.db.execute('INSERT OR IGNORE INTO audits(export_id,guid,fingerprint,version,created,outcome) VALUES(?,?,?,?,?,?)',
                                (export['id'], guid, fingerprint(s, notes[guid]), bundle['audit_version'], timestamp, outcome))
        return [f['id'] for f in findings]

    def findings(self):
        result = []
        for row in self.db.execute('SELECT payload FROM findings ORDER BY rowid'):
            f = json.loads(row[0])
            review = self.db.execute('SELECT * FROM reviews WHERE finding_id=? ORDER BY id DESC LIMIT 1', (f['id'],)).fetchone()
            f['review'] = dict(review) if review else {'id': 0, 'status': 'awaiting_review', 'final': None}
            result.append(f)
        return result

    def review(self, finding_id, status, reviewer, final=None, comment='', expected_review_id=None):
        require(status in STATUSES and status != 'awaiting_review', 'Invalid review decision')
        require(isinstance(reviewer, str) and reviewer.strip(), 'Reviewer name required')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            f = next((f for f in self.findings() if f['id'] == finding_id), None)
            require(f is not None, 'Unknown finding')
            if expected_review_id is not None:
                require(f['review']['id'] == expected_review_id, 'Decision changed since page loaded; refresh')
            if status == 'approved':
                require(f['evidence_status'] != 'needs_research', 'Research finding must be deferred until a new evidence-backed proposal is imported')
                final = f['replacement'] if final is None else final
                guard_edit(f['original'], final)
            else:
                require(final is None, 'Final content only belongs to approvals')
            self.db.execute('INSERT INTO reviews(finding_id,status,final,reviewer,comment,created) VALUES(?,?,?,?,?,?)',
                            (finding_id, status, final, reviewer.strip(), comment, now()))

    def patch(self, key=None):
        export = self.export(key); s = export['snapshot']; notes = by_guid(s); changes = []; seen = set()
        for f in self.findings():
            if f['review']['status'] != 'approved':
                continue
            # All approvals are source-bound. A newer export needs new review/import.
            if f['source_sha256'] != export['id']:
                continue
            n = notes.get(f['guid'])
            require(n and not excluded(s, n) and pediatric(n), 'Approval targets ineligible note')
            field = next(v for v in n['fields'] if v['name'] == f['field'])
            require(field['value'] == f['original'] and fingerprint(s, n) == f['note_fingerprint'], 'Stale proposal')
            pair = (f['guid'], f['field']); require(pair not in seen, 'Conflicting approvals for same field; reject/defer one')
            seen.add(pair); guard_edit(f['original'], f['review']['final'])
            changes.append({'finding_id': f['id'], 'review_id': f['review']['id'], 'guid': f['guid'],
                            'note_id': n['id'], 'field': f['field'], 'original': f['original'],
                            'replacement': f['review']['final']})
        body = {'schema': 1, 'source_sha256': export['id'], 'source_version': export['version'],
                'changes': sorted(changes, key=lambda c: (c['guid'], c['field'])), 'tag_changes': [],
                'notes_affected': len({c['guid'] for c in changes})}
        return body | {'id': checksum(body)}


def preview(patch):
    lines = [f"Patch {patch['id']}", f"Source: {patch['source_version']} / {patch['source_sha256']}",
             f"Total notes affected: {patch['notes_affected']}", 'Tag changes: none',
             'Preview only; source deck is unchanged.']
    for c in patch['changes']:
        lines += ['', f"GUID: {c['guid']} | Note: {c['note_id']} | Field: {c['field']}",
                  'ORIGINAL (exact):', c['original'], 'APPROVED REPLACEMENT (exact):', c['replacement']]
    return '\n'.join(lines) + '\n'


def expected_snapshot(snapshot, patch):
    result = copy.deepcopy(snapshot); notes = by_guid(result)
    for c in patch['changes']:
        n = notes[c['guid']]
        require(n['id'] == c['note_id'] and not excluded(result, n), 'Identity/exclusion violation')
        field = next(f for f in n['fields'] if f['name'] == c['field'])
        require(field['value'] == c['original'], 'Original value mismatch')
        guard_edit(field['value'], c['replacement']); field['value'] = c['replacement']
    return result
