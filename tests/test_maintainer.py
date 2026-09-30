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
        tags = ' Crabs::Specialty::Peds marked '
        if i < 10:
            tags += 'Crabs::Residency::HN::ThyroidCancer '
        db.execute('INSERT INTO notes VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (100+i, 'guid-'+str(i), 10, tags, front+'\x1f'+back, 100, '', 0, front, 1))
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

    def test_residency_hn_scope_import(self):
        bundle = {'source_sha256': self.key,
                  'scope': 'Residency Head and Neck',
                  'sample_guids': ['guid-'+str(i) for i in range(10)],
                  'audit_version': 'residency-hn-test-v1',
                  'author': 'synthetic test', 'findings': []}
        self.assertEqual(self.store.import_findings(bundle), [])
        self.assertEqual(self.store.db.execute(
            'SELECT COUNT(*) FROM audits WHERE version=?', ('residency-hn-test-v1',)).fetchone()[0], 10)
        bundle['scope'] = 'Unknown'
        with self.assertRaises(ValueError):
            self.store.import_findings(bundle)

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

    def test_evidence_backed_import_requires_research_attempt_before_deferral(self):
        b=self.bundle(); b['schema']=2; b['audit_stage']='evidence_backed'
        b['findings'][0]['replacement']=None; b['findings'][0]['evidence_status']='needs_research'
        with self.assertRaisesRegex(ValueError,'documented research attempt'):
            self.store.import_findings(b)
        b['findings'][0]['research_attempted']=True
        b['findings'][0]['research_limitations']='Authoritative sources conflict on the population and threshold.'
        self.assertEqual(len(self.store.import_findings(b)),len(b['findings']))

    def schema3_bundle(self, disposition='revise', changes=None):
        b=self.bundle(); n=self.snapshot['notes']['100']; front=n['fields'][0]['value']
        b.update(schema=3,audit_stage='evidence_backed',audit_version='evidence-v3')
        f=b['findings'][0]
        f.update(evidence_status='supported',evidence=[{
            'title':'Guideline','organization_authors':'Society','publication':'Journal',
            'year':2026,'url':'https://example.org/guideline'}],
            researched_conclusion='The evidence supports an exact actionable result.',
            disposition=disposition,remaining_uncertainty='Low-certainty implementation detail.',
            proposed_changes=changes if changes is not None else [{
                'field':'Front','original':front,'final':front.replace('Original','Evidence-backed')}])
        b['findings']=[f]
        return b

    def test_schema3_osa_style_evidence_cannot_stop_at_null_proposal(self):
        b=self.schema3_bundle(); f=b['findings'][0]
        f.update(proposed_changes=[],replacement=None,disposition=None,
                 evidence_status='needs_research',research_attempted=True,
                 research_limitations='Synthesis was not completed despite a directly relevant guideline.',
                 rationale='High-confidence evidence-backed OSA concern')
        with self.assertRaisesRegex(ValueError,'require synthesis'):
            self.store.import_findings(b)
        f.update(evidence_status='supported',disposition='revise')
        f['proposed_changes']=[{'field':'Front','original':f['original'],
                                'final':f['original'].replace('Original','Phenotype-specific')}]
        ids=self.store.import_findings(b)
        saved=next(x for x in self.store.findings() if x['id']==ids[0])
        self.assertEqual(saved['disposition'],'revise')
        self.assertEqual(saved['proposed_changes'][0]['field'],'Front')

    def test_schema3_text_extra_and_cross_field_proposals(self):
        n=self.snapshot['notes']['100']; front=n['fields'][0]['value']; back=n['fields'][1]['value']
        cases=[
            [{'field':'Front','original':front,'final':front.replace('Original','Focused')}],
            [{'field':'Back','original':back,'final':back.replace('Answer','Qualified')}],
            [{'field':'Front','original':front,'final':front.replace('Original','Focused')},
             {'field':'Back','original':back,'final':back.replace('Answer','Qualified')}]]
        for i,changes in enumerate(cases):
            b=self.schema3_bundle(changes=changes); b['audit_version']=f'evidence-v3-{i}'
            ids=self.store.import_findings(b); f=next(x for x in self.store.findings() if x['id']==ids[0])
            self.assertEqual([c['field'] for c in f['proposed_changes']], [c['field'] for c in changes])

    def test_nonpatch_disposition_can_be_reviewed_without_deck_change(self):
        b=self.schema3_bundle(disposition='split',changes=[]); ids=self.store.import_findings(b)
        before=digest_file(self.source); self.store.review(ids[0],'approved','human',edits=[])
        self.assertEqual(self.store.patch()['changes'],[])
        self.assertEqual(digest_file(self.source),before)

    def test_backfill_selection_supersession_history_and_idempotency(self):
        b=self.bundle()
        for i in range(4):
            b['findings'][i].update(replacement=None,evidence_status='needs_research')
        ids=self.store.import_findings(b)
        self.store.review(ids[0],'approved','human',edits=[{
            'field':'Front','original':b['findings'][0]['original'],
            'final':b['findings'][0]['original'].replace('Original','Human')}],comment='human evidence')
        self.store.review(ids[1],'needs_research','human')
        self.store.review(ids[2],'deferred','human')
        self.store.review(ids[3],'rejected','human')
        export=self.store.backfill_candidates()
        selected={x['supersedes_finding_id'] for x in export['candidates']}
        self.assertNotIn(ids[0],selected); self.assertIn(ids[1],selected); self.assertIn(ids[2],selected)
        self.assertNotIn(ids[3],selected)
        prior=next(x for x in export['candidates'] if x['supersedes_finding_id']==ids[1])
        rb=self.schema3_bundle(); rb.update(reprocess=True,sample_guids=['guid-1'])
        f=rb['findings'][0]; source=self.snapshot['notes']['101']['fields'][0]['value']
        f.update(guid='guid-1',original=source,supersedes_finding_id=ids[1],
                 proposed_changes=[{'field':'Front','original':source,
                                    'final':source.replace('Original','Researched')}])
        first=self.store.import_findings(rb); second=self.store.import_findings(rb)
        self.assertEqual(first,second)
        self.assertEqual(sum(x['id']==first[0] for x in self.store.findings()),1)
        old=next(x for x in self.store.findings() if x['id']==ids[1])
        self.assertEqual(old['review']['status'],'needs_research')
        self.assertEqual(old['superseded_by'],first[0])
        queue_ids={u['finding']['id'] for u in self.store.review_queue()['units'] if u['kind']=='finding'}
        self.assertNotIn(ids[1],queue_ids); self.assertIn(first[0],queue_ids)

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

    def two_field_bundle(self, extra_research=False):
        n=self.snapshot['notes']['100']; front=n['fields'][0]['value']; back=n['fields'][1]['value']
        findings=[{'guid':'guid-0','field':'Front','original':front,
                   'replacement':front.replace('Original','Revised'),'category':'ambiguous_wording',
                   'severity':'low','confidence':'high','rationale':'front finding',
                   'evidence_status':'editorial','evidence':[]}]
        if extra_research:
            findings=[{'guid':'guid-0','field':'Back','original':back,'replacement':None,
                       'category':'outdated_guideline','severity':'high','confidence':'medium',
                       'rationale':'back needs research','evidence_status':'needs_research','evidence':[]}]
        return {'source_sha256':self.key,'sample_guids':['guid-'+str(i) for i in range(15)],
                'audit_version':'field-test','author':'test','findings':findings}

    def test_text_correct_extra_needs_research(self):
        ids=self.store.import_findings(self.two_field_bundle(True)); q=self.store.review_queue()
        front=next(u for u in q['units'] if u['field']=='Front'); back=next(u for u in q['units'] if u['field']=='Back')
        self.assertEqual(front['kind'],'unchanged'); self.assertEqual(back['kind'],'finding')
        self.store.field_review(self.key,'guid-0','Front','reviewed_unchanged','human',0)
        self.store.review(ids[0],'needs_research','human')
        self.assertEqual(self.store.review_queue()['notes'][0]['status'],'complete')

    def test_extra_correct_text_change_and_partial_queue(self):
        ids=self.store.import_findings(self.two_field_bundle()); self.store.review(ids[0],'approved','human')
        q=self.store.review_queue(); note=q['notes'][0]
        self.assertEqual(note['status'],'partially_reviewed')
        pending=[u for u in q['units'] if not u['resolved']]
        self.assertEqual([(u['field'],u['kind']) for u in pending],[('Back','unchanged')])
        self.store.field_review(self.key,'guid-0','Back','reviewed_unchanged','human',0)
        self.assertEqual(self.store.review_queue()['notes'][0]['status'],'complete')

    def test_changes_in_both_fields_and_independent_application(self):
        b=self.two_field_bundle(); n=self.snapshot['notes']['100']; back=n['fields'][1]['value']
        b['findings'].append({'guid':'guid-0','field':'Back','original':back,
            'replacement':back.replace('Answer','Changed'),'category':'ambiguous_wording','severity':'low',
            'confidence':'high','rationale':'back finding','evidence_status':'editorial','evidence':[]})
        ids=self.store.import_findings(b); self.store.review(ids[0],'approved','human')
        self.assertEqual([c['field'] for c in self.store.patch()['changes']],['Front'])
        q=self.store.review_queue(); self.assertEqual(q['notes'][0]['status'],'partially_reviewed')
        self.store.review(ids[1],'deferred','human')
        self.assertEqual(q['units'][1]['field'],'Back')
        self.assertEqual(self.store.review_queue()['notes'][0]['status'],'complete')

    def test_extra_approved_while_text_unresolved(self):
        b=self.two_field_bundle(); n=self.snapshot['notes']['100']; back=n['fields'][1]['value']
        b['findings'].append({'guid':'guid-0','field':'Back','original':back,
            'replacement':back.replace('Answer','Changed'),'category':'ambiguous_wording','severity':'low',
            'confidence':'high','rationale':'back finding','evidence_status':'editorial','evidence':[]})
        ids=self.store.import_findings(b); self.store.review(ids[1],'approved','human')
        self.assertEqual(self.store.review_queue()['notes'][0]['status'],'partially_reviewed')
        self.assertEqual([(c['field'],c['replacement']) for c in self.store.patch()['changes']],
                         [('Back',back.replace('Answer','Changed'))])

    def test_legacy_decision_interpreted_as_field_resolution(self):
        ids=self.store.import_findings(self.two_field_bundle()); self.store.review(ids[0],'rejected','legacy')
        q=self.store.review_queue(); front=next(u for u in q['units'] if u['field']=='Front')
        self.assertTrue(front['resolved']); self.assertEqual(front['finding']['review']['status'],'rejected')

    def test_reset_date_is_append_only_and_prior_day_untouched(self):
        ids=self.store.import_findings(self.bundle())
        with self.store.db:
            self.store.db.execute('INSERT INTO reviews(finding_id,status,final,reviewer,comment,created) VALUES(?,?,?,?,?,?)',
                                  (ids[0],'rejected',None,'human','','2026-09-25T16:00:00+00:00'))
            self.store.db.execute('INSERT INTO reviews(finding_id,status,final,reviewer,comment,created) VALUES(?,?,?,?,?,?)',
                                  (ids[1],'deferred',None,'human','','2026-09-26T16:00:00+00:00'))
        result=self.store.reset_reviews_for_local_date('2026-09-26','America/New_York')
        self.assertEqual(result['historical_review_actions'],1); self.assertEqual(result['findings_returned_to_pending'],1)
        fs=self.store.findings(); self.assertEqual(fs[0]['review']['status'],'rejected'); self.assertEqual(fs[1]['review']['status'],'awaiting_review')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM reviews').fetchone()[0],3)
        again=self.store.reset_reviews_for_local_date('2026-09-26','America/New_York')
        self.assertEqual(again['findings_returned_to_pending'],0)

    def test_reviewed_unchanged_never_creates_patch_or_blank(self):
        self.store.import_findings(self.two_field_bundle(True))
        self.store.field_review(self.key,'guid-0','Front','reviewed_unchanged','human',0)
        self.assertEqual(self.store.patch()['changes'],[])

    def test_cross_field_resolution_text_unchanged_extra_edited(self):
        ids=self.store.import_findings(self.two_field_bundle()); n=self.snapshot['notes']['100']
        back=n['fields'][1]['value']; revised=back.replace('Answer','Qualified answer')
        self.store.review(ids[0],'approved','human',edits=[{'field':'Back','original':back,'final':revised}])
        f=self.store.findings()[0]
        self.assertEqual(f['field'],'Front'); self.assertIsNone(f['review']['final'])
        self.assertEqual([(e['finding_id'],e['field'],e['original'],e['final']) for e in f['review']['edits']],
                         [(ids[0],'Back',back,revised)])
        self.assertEqual(len(self.store.findings()),1)  # No fabricated Back finding.
        change=self.store.patch()['changes'][0]
        self.assertEqual((change['field'],change['finding_field'],change['consequential']),('Back','Front',True))

    def test_cross_field_resolution_edits_text_and_extra(self):
        ids=self.store.import_findings(self.two_field_bundle()); n=self.snapshot['notes']['100']
        front=n['fields'][0]['value']; back=n['fields'][1]['value']
        edits=[{'field':'Front','original':front,'final':front.replace('Original','Focused')},
               {'field':'Back','original':back,'final':back.replace('Answer','Qualified')}]
        self.store.review(ids[0],'approved','human',edits=edits)
        patch=self.store.patch(); self.assertEqual([c['field'] for c in patch['changes']],['Back','Front'])
        self.assertEqual({c['consequential'] for c in patch['changes'] if c['field']=='Back'},{True})
        self.assertEqual({c['consequential'] for c in patch['changes'] if c['field']=='Front'},{False})

    def test_extra_finding_can_prompt_text_edit(self):
        b=self.two_field_bundle(); n=self.snapshot['notes']['100']; front=n['fields'][0]['value']; back=n['fields'][1]['value']
        b['findings'][0].update(field='Back',original=back,replacement=back.replace('Answer','Revised answer'))
        ids=self.store.import_findings(b)
        self.store.review(ids[0],'approved','human',edits=[{'field':'Front','original':front,'final':front.replace('Original','Focused')}])
        c=self.store.patch()['changes'][0]
        self.assertEqual((c['field'],c['finding_field'],c['consequential']),('Front','Back',True))

    def test_independent_findings_keep_independent_statuses_with_cross_edit(self):
        b=self.two_field_bundle(); n=self.snapshot['notes']['100']; front=n['fields'][0]['value']; back=n['fields'][1]['value']
        b['findings'].append({'guid':'guid-0','field':'Back','original':back,
            'replacement':back.replace('Answer','Changed'),'category':'ambiguous_wording','severity':'low',
            'confidence':'high','rationale':'back finding','evidence_status':'editorial','evidence':[]})
        ids=self.store.import_findings(b)
        self.store.review(ids[0],'approved','human',edits=[{'field':'Front','original':front,'final':front.replace('Original','Focused')}])
        fs=self.store.findings(); self.assertEqual(fs[0]['review']['status'],'approved'); self.assertEqual(fs[1]['review']['status'],'awaiting_review')
        self.assertEqual(self.store.review_queue()['notes'][0]['status'],'partially_reviewed')

    def test_cross_field_resolution_applies_atomically(self):
        ids=self.store.import_findings(self.two_field_bundle()); n=self.snapshot['notes']['100']; front=n['fields'][0]['value']; back=n['fields'][1]['value']
        edits=[{'field':'Front','original':front,'final':front.replace('Original','Focused')},
               {'field':'Back','original':back,'final':back.replace('Answer','Qualified')}]
        self.store.review(ids[0],'approved','human',edits=edits); patch=self.store.patch()
        out=self.root/'cross-field.apkg'; apply_patch(self.store,patch,out,patch['id']); result,_=read_package(out)
        values={f['name']:f['value'] for f in result['notes']['100']['fields']}
        self.assertIn('Focused',values['Front']); self.assertIn('Qualified',values['Back'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM applications').fetchone()[0],1)

    def test_cross_field_resolution_is_atomic_on_validation_failure(self):
        ids=self.store.import_findings(self.two_field_bundle()); n=self.snapshot['notes']['100']; front=n['fields'][0]['value']; back=n['fields'][1]['value']
        with self.assertRaises(ValueError):
            self.store.review(ids[0],'approved','human',edits=[
                {'field':'Front','original':front,'final':front.replace('Original','Focused')},
                {'field':'Back','original':back,'final':back.replace('image.png','other.png')}])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM reviews').fetchone()[0],0)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM review_edits').fetchone()[0],0)

    def test_research_required_allows_documented_human_correction_only(self):
        b=self.two_field_bundle(True); ids=self.store.import_findings(b); n=self.snapshot['notes']['100']
        front=n['fields'][0]['value']; revised=front.replace('Original','Evidence-backed')
        with self.assertRaisesRegex(ValueError,'research/evidence note'):
            self.store.review(ids[0],'approved','human',edits=[
                {'field':'Front','original':front,'final':revised}])
        self.store.review(ids[0],'approved','human',comment='Checked current guideline, section 4',edits=[
            {'field':'Front','original':front,'final':revised}])
        f=self.store.findings()[0]
        self.assertEqual(f['review']['comment'],'Checked current guideline, section 4')
        self.assertEqual(f['review']['edits'][0]['final'],revised)

    def test_cross_field_edit_and_provenance_survive_reopen(self):
        ids=self.store.import_findings(self.two_field_bundle()); n=self.snapshot['notes']['100']
        back=n['fields'][1]['value']; revised=back.replace('Answer','Persisted context')
        self.store.review(ids[0],'approved','human',comment='evidence note',edits=[
            {'field':'Back','original':back,'final':revised}])
        path=self.store.path; self.store.close(); self.store=Store(path)
        f=self.store.findings()[0]; edit=f['review']['edits'][0]
        self.assertEqual((f['field'],edit['field'],edit['finding_id']),('Front','Back',ids[0]))
        self.assertEqual((edit['original'],edit['final']),(back,revised))
        self.assertEqual((f['review']['reviewer'],f['review']['comment']),('human','evidence note'))
