import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
import zstandard
from test_release import package
from crabs.reader import read_package, digest_file
from crabs.maintainer import Store, by_guid, excluded, fingerprint, guard_edit, preview
from crabs.maintainer_patch import apply_patch


def fixture(path, modern=False):
    package(path, modern=modern)
    member = 'collection.anki21b' if modern else 'collection.anki21'
    with zipfile.ZipFile(path) as z:
        members = {n: z.read(n) for n in z.namelist()}
    raw = zstandard.ZstdDecompressor().decompress(members[member]) if modern else members[member]
    dbpath = path.with_suffix('.sqlite'); dbpath.write_bytes(raw)
    db = sqlite3.connect(dbpath)
    db.executescript('ALTER TABLE notes ADD COLUMN usn INTEGER DEFAULT 0; ALTER TABLE notes ADD COLUMN sfld TEXT; ALTER TABLE notes ADD COLUMN csum INTEGER;')
    db.execute('DELETE FROM notes'); db.execute('DELETE FROM cards')
    for i in range(15):
        front = '{{c1::Original}} α ≥ 5 <b>text</b>'
        back = 'Answer <a href="https://example.org">link</a><img src="image.png">[sound:voice.mp3]'
        db.execute('INSERT INTO notes VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (100+i, 'guid-'+str(i), 10, ' Crabs::Specialty::Peds marked ', front+'\x1f'+back, 100, '', 0, front, 1))
        db.execute('INSERT INTO cards VALUES(?,?,?,?,?,?)', (200+i, 100+i, 20, 0, 0, 999))
    # A renamed IO note type must still be excluded by fields/template signal.
    if modern:
        db.execute("INSERT INTO notetypes SELECT 11,'Image Occlusion Enhanced',mtime_secs,config FROM notetypes WHERE id=10")
        db.execute('INSERT INTO fields SELECT 11,ord,name,config FROM fields WHERE ntid=10')
        db.execute('INSERT INTO templates SELECT 11,ord,name,config FROM templates WHERE ntid=10')
    else:
        models = json.loads(db.execute('SELECT models FROM col').fetchone()[0]); m = copy.deepcopy(models['10'])
        m['id'] = 11; m['name'] = 'Image Occlusion Enhanced'; models['11'] = m
        db.execute('UPDATE col SET models=?', (json.dumps(models),))
    db.execute('INSERT INTO notes VALUES(999,?,11,?,?,100,?,0,?,1)', ('excluded', ' Crabs::Specialty::Peds ', 'Mask\x1fImage', '', 'Mask'))
    db.execute('INSERT INTO cards VALUES(999,999,20,0,0,999)')
    db.commit(); db.close()
    members[member] = zstandard.ZstdCompressor().compress(dbpath.read_bytes()) if modern else dbpath.read_bytes()
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, b in members.items(): z.writestr(n,b)
    dbpath.unlink()


class MaintainerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root = Path(self.temp.name)
        self.source = self.root/'source.apkg'; fixture(self.source)
        self.store = Store(self.root/'history.sqlite'); self.addCleanup(self.store.close)
        self.key = self.store.ingest(self.source, 'test-v1')
        self.snapshot = self.store.export()['snapshot']

    def bundle(self):
        findings=[]
        for i in range(5):
            n = self.snapshot['notes'][str(100+i)]; original=n['fields'][0]['value']
            findings.append({'guid': n['guid'], 'field': 'Front', 'original': original,
                             'replacement': original.replace('Original', 'Revised'), 'category': 'ambiguous_wording',
                             'severity': 'low', 'confidence': 'high', 'rationale': 'Synthetic workflow test, no clinical assertion',
                             'evidence_status': 'editorial', 'evidence': []})
        return {'source_sha256': self.key, 'sample_guids': ['guid-'+str(i) for i in range(15)],
                'audit_version': 'test-v1', 'author': 'synthetic test', 'findings': findings}

    def reviewed(self):
        ids = self.store.import_findings(self.bundle())
        for i, status in enumerate(['approved','rejected','deferred','approved']):
            final = self.bundle()['findings'][i]['replacement'].replace('Revised', 'Reviewer edit') if i==3 else None
            self.store.review(ids[i], status, 'Test reviewer', final)
        return ids

    def add_export(self, snapshot):
        key = hashlib.sha256(json.dumps(snapshot).encode()).hexdigest()
        with self.store.db:
            self.store.db.execute('INSERT INTO exports VALUES(?,?,?,?,?)', (key,str(self.source),'v2','later',json.dumps(snapshot)))
        return key

    def test_review_persistence_and_no_deck_mutation(self):
        original = digest_file(self.source); ids=self.reviewed()
        second = Store(self.store.path)
        self.addCleanup(second.close)
        self.assertEqual([f['review']['status'] for f in second.findings()], ['approved','rejected','deferred','approved','awaiting_review'])
        self.assertIn('Reviewer edit', second.findings()[3]['review']['final'])
        self.assertEqual(digest_file(self.source), original)
        self.assertEqual(len(second.patch()['changes']), 2)

    def test_patch_preview_and_apply_exact_legacy(self):
        self.reviewed(); patch=self.store.patch(); before=digest_file(self.source)
        self.assertIn('Total notes affected: 2',preview(patch)); self.assertIn('GUID: guid-0',preview(patch))
        output=self.root/'patched.apkg'; report=apply_patch(self.store, patch, output, patch['id'])
        self.assertEqual(report['status'],'PASS'); self.assertEqual(digest_file(self.source),before)
        result,_=read_package(output)
        for nid,note in self.snapshot['notes'].items():
            if nid in ('100','103'):
                self.assertNotEqual(note['fields'][0]['value'],result['notes'][nid]['fields'][0]['value'])
                self.assertEqual(note['fields'][1],result['notes'][nid]['fields'][1])
                self.assertEqual(note['tags'],result['notes'][nid]['tags'])
            else:self.assertEqual(note,result['notes'][nid])
        self.assertEqual(self.snapshot['cards'],result['cards'])
        self.assertEqual(set(by_guid(self.snapshot)),set(by_guid(result)))
        self.assertTrue(output.with_suffix('.validation.json').exists())

    def test_modern_package_roundtrip(self):
        source=self.root/'modern.apkg'; fixture(source,True)
        self.key=self.store.ingest(source,'modern'); self.snapshot=self.store.export()['snapshot']
        self.reviewed(); p=self.store.patch()
        self.assertEqual(apply_patch(self.store,p,self.root/'out.apkg',p['id'])['status'],'PASS')

    def test_new_unchanged_substantive_and_cosmetic_states(self):
        self.store.import_findings(self.bundle()); s=copy.deepcopy(self.snapshot)
        s['notes']['100']['fields'][0]['value'] += ' clinically changed'
        s['notes']['101']['fields'][0]['value'] = '<span>'+s['notes']['101']['fields'][0]['value']+'</span>'
        s['notes']['102']['tags'].append('metadata')
        new=copy.deepcopy(s['notes']['100']); new['id']=500; new['guid']='new-note'; s['notes']['500']=new
        key=self.add_export(s); c=self.store.coverage(key)
        self.assertEqual(c['notes']['guid-0'],'modified_needs_reaudit')
        self.assertEqual(c['notes']['guid-1'],'audited_unchanged')
        self.assertEqual(c['notes']['guid-2'],'audited_unchanged')
        self.assertEqual(c['notes']['guid-4'],'audited_unchanged')
        self.assertEqual(c['notes']['new-note'],'new_unaudited')
        self.assertEqual(c['notes']['excluded'],'excluded_image_occlusion')
        self.assertEqual(c['eligible_notes'],16)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM audits').fetchone()[0],15)

    def test_extra_media_model_changes_invalidate(self):
        n=self.snapshot['notes']['100']; before=fingerprint(self.snapshot,n)
        for what in ('extra','media','model'):
            s=copy.deepcopy(self.snapshot)
            if what=='extra':s['notes']['100']['fields'][1]['value']+=' dose changed'
            if what=='media':s['media']['image.png']['sha256']='changed'
            if what=='model':s['models']['10']['tmpls'][0]['qfmt']+='changed'
            self.assertNotEqual(before,fingerprint(s,s['notes']['100']))

    def test_history_append_only_and_rejection_dedup(self):
        ids=self.store.import_findings(self.bundle()); self.store.review(ids[0],'rejected','human')
        self.store.import_findings(self.bundle())
        self.assertEqual(len(self.store.findings()),5)
        self.assertEqual(self.store.findings()[0]['review']['status'],'rejected')
        self.store.review(ids[0],'deferred','human')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM reviews').fetchone()[0],2)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.db:self.store.db.execute('DELETE FROM reviews')
        b=self.bundle(); b['audit_version']='test-v2'; self.store.import_findings(b)
        self.assertEqual(len(self.store.findings()),10)

    def test_rejected_same_proposal_on_new_export_stays_rejected(self):
        ids=self.store.import_findings(self.bundle()); self.store.review(ids[0],'rejected','human')
        s=copy.deepcopy(self.snapshot); s['notes']['110']['tags'].append('newtag')
        key=self.add_export(s); b=self.bundle(); b['source_sha256']=key
        self.store.import_findings(b,key)
        self.assertEqual(len(self.store.findings()),5)
        self.assertEqual(self.store.findings()[0]['review']['status'],'rejected')

    def test_duplicate_guid_and_empty_guid_rejected(self):
        for guid in ('guid-0',''):
            s=copy.deepcopy(self.snapshot); s['notes']['101']['guid']=guid
            with self.assertRaises(ValueError):by_guid(s)

    def test_io_detection(self):
        s=copy.deepcopy(self.snapshot); n=s['notes']['100']; m=s['models']['10']
        for name in ('Image Occlusion', 'Image Occlusion Enhanced-019a2', 'IMAGE_OCCLUSION'):
            m['name']=name; self.assertTrue(excluded(s,n))
        m['name']='Renamed'; m['originalStockKind']=6; self.assertTrue(excluded(s,n))
        m['originalStockKind']=0; m['flds']=[{'name':'Question Mask'},{'name':'Answer Mask'}]; self.assertTrue(excluded(s,n))
        m['flds']=[{'name':'Occlusion'},{'name':'Image'}]; self.assertTrue(excluded(s,n))

    def test_ineligible_sample_and_outside_findings_blocked(self):
        for kind in ('io','outside','small'):
            b=self.bundle()
            if kind=='io':b['sample_guids'][0]='excluded'
            if kind=='outside':b['findings'][0]['guid']='elsewhere'
            if kind=='small':b['sample_guids']=b['sample_guids'][:3]
            with self.assertRaises(ValueError):self.store.import_findings(b)
        self.assertEqual(self.store.findings(),[])

    def test_stale_original_and_missing_evidence_blocked(self):
        for kind in ('stale','evidence','category'):
            b=self.bundle()
            if kind=='stale':b['findings'][0]['original']='wrong'
            if kind=='evidence':b['findings'][0]['evidence_status']='supported'
            if kind=='category':b['findings'][0]['category']='unknown'
            with self.assertRaises(ValueError):self.store.import_findings(b)

    def test_research_cannot_be_approved(self):
        b=self.bundle(); b['findings'][0]['replacement']=None; b['findings'][0]['evidence_status']='needs_research'
        ids=self.store.import_findings(b)
        with self.assertRaises(ValueError):self.store.review(ids[0],'approved','human')
        self.store.review(ids[0],'deferred','human')
        self.assertEqual(self.store.patch()['changes'],[])

    def test_cloze_html_links_media_and_unicode(self):
        old='{{c1::α}} <b>≥</b><a href="https://example.org">link</a><img src="x.png">[sound:x.mp3]'
        guard_edit(old,old.replace('α','β'))
        for new in (old.replace('c1','c2'),old.replace('<b>','<i>'),old.replace('x.png','y.png'),old.replace('https://example.org','https://evil.org'),old+'\x1fextra',old.replace('}}',''),old+'{{broken',old.replace('α','{{broken')):
            with self.assertRaises(ValueError):guard_edit(old,new)

    def test_stale_decision_and_patch_tamper(self):
        ids=self.reviewed(); p=self.store.patch()
        with self.assertRaises(ValueError):self.store.review(ids[0],'rejected','human',expected_review_id=0)
        self.store.review(ids[0],'rejected','human')
        with self.assertRaises(ValueError):apply_patch(self.store,p,self.root/'out.apkg',p['id'])
        p=self.store.patch(); p['changes'][0]['replacement']='tampered'
        with self.assertRaises(ValueError):apply_patch(self.store,p,self.root/'out.apkg',p['id'])

    def test_conflicting_approvals_blocked(self):
        ids=self.reviewed(); b=self.bundle(); b['audit_version']='different'; other=self.store.import_findings(b)
        self.store.review(other[0],'approved','human')
        with self.assertRaises(ValueError):self.store.patch()

    def test_explicit_confirmation_and_output_safety(self):
        self.reviewed(); p=self.store.patch()
        with self.assertRaises(ValueError):apply_patch(self.store,p,self.root/'out.apkg','wrong')
        with self.assertRaises(ValueError):apply_patch(self.store,p,self.source,p['id'])
        output=self.root/'exists.apkg'; output.write_bytes(b'existing')
        with self.assertRaises(ValueError):apply_patch(self.store,p,output,p['id'])
        self.assertEqual(output.read_bytes(),b'existing')

    def test_empty_patch_refused(self):
        p=self.store.patch()
        with self.assertRaises(ValueError):apply_patch(self.store,p,self.root/'out.apkg',p['id'])

    def test_changed_source_refused(self):
        self.reviewed(); p=self.store.patch(); self.source.write_bytes(b'changed')
        with self.assertRaises(ValueError):apply_patch(self.store,p,self.root/'out.apkg',p['id'])

    def test_identity_uses_guid_not_text(self):
        # All synthetic notes deliberately have identical text but distinct GUIDs.
        self.reviewed(); self.assertEqual([c['guid'] for c in self.store.patch()['changes']], ['guid-0','guid-3'])
