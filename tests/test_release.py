"""Synthetic packages only: no live Anki profile or real package is modified."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zstandard
from crabs.reader import read_package,digest_file
from crabs.compare import compare,match_notes
from crabs.output import planned_outputs,json_text
from crabs.protobuf import FormatError,config
import release


def varint(n):
    b=bytearray()
    while n>=128:b.append((n&127)|128);n>>=7
    b.append(n);return bytes(b)


def pb(field,value):
    if isinstance(value,str):value=value.encode()
    if isinstance(value,bytes):return varint(field*8+2)+varint(len(value))+value
    return varint(field*8)+varint(value)


def package(path,modern=False,front='A sufficiently long stable question',back='Answer',guid='shared-guid',nid=100,mod=100,media=b'picture',version=None,schema=None,due=999,extra_meta=b''):
    with tempfile.TemporaryDirectory() as temp:
        db=sqlite3.connect(str(Path(temp)/'source'))
        db.executescript('''CREATE TABLE col(ver integer,models text,decks text);
          CREATE TABLE notes(id integer,guid text,mid integer,tags text,flds text,mod integer,data text);
          CREATE TABLE cards(id integer,nid integer,did integer,ord integer,odid integer,due integer);
        ''')
        model={'id':10,'name':'Basic','type':0,'mod':10,'usn':0,'sortf':0,'css':'','latexPre':'','latexPost':'','req':[[0,'any',[0]]],
            'flds':[{'name':'Front','ord':0,'font':'Arial','size':20},{'name':'Back','ord':1,'font':'Arial','size':20}],
            'tmpls':[{'name':'Card','ord':0,'qfmt':'{{Front}}','afmt':'{{Back}}'}]}
        decks={'20':{'id':20,'name':'Crabs','dyn':0}}
        db.execute('insert into col values(?,?,?)',(schema if schema is not None else 18 if modern else 11,json.dumps({'10':model}),json.dumps(decks)))
        db.execute('insert into notes values(?,?,?,?,?,?,?)',(nid,guid,10,' tag marked ',front+'\x1f'+back+'<img src="image.png">',mod,''))
        db.execute('insert into cards values(200,?,20,0,0,?)',(nid,due))
        if modern:
            db.executescript('''CREATE TABLE notetypes(id integer,name text,mtime_secs integer,config blob);
              CREATE TABLE fields(ntid integer,ord integer,name text,config blob);
              CREATE TABLE templates(ntid integer,ord integer,name text,config blob);
              CREATE TABLE decks(id integer,name text,kind blob);''')
            db.execute('insert into notetypes values(10,?,10,?)',('Basic',pb(8,pb(2,1)+pb(3,b'\0'))))
            for i,name in enumerate(['Front','Back']):db.execute('insert into fields values(10,?,?,?)',(i,name,pb(3,'Arial')+pb(4,20)))
            db.execute('insert into templates values(10,0,?,?)',('Card',pb(1,'{{Front}}')+pb(2,'{{Back}}')))
            db.execute('insert into decks values(20,?,?)',('Crabs',pb(1,b'')))
        db.commit();db.close()
        raw=(Path(temp)/'source').read_bytes()
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('meta',pb(1,version if version is not None else 3 if modern else 2)+extra_meta)
        compress=zstandard.ZstdCompressor().compress if modern else lambda b:b
        z.writestr('collection.anki21b' if modern else 'collection.anki21',compress(raw))
        z.writestr('collection.anki2',b'Compatibility decoy, not the actual database')
        manifest=pb(1,pb(1,'image.png')+pb(2,len(media))+pb(3,hashlib.sha1(media).digest())) if modern else b'{"0":"image.png"}'
        z.writestr('media',compress(manifest));z.writestr('0',compress(media))


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'repo';self.root.mkdir()
        self.old=self.base/'old.apkg';self.new=self.base/'new.apkg'
        package(self.old);package(self.new,modern=True,back='Changed answer',mod=200)

    def pair(self):
        a,aa=read_package(self.old);b,ba=read_package(self.new)
        return a,b,aa,ba,compare(a,b,aa,ba)

    def invoke(self,extra=()):
        with patch.object(release,'ROOT',self.root),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            return release.run([str(self.old),str(self.new),'--baseline-date','2026-01-01','--release-date','2026-02-01',*extra])

    def test_formats_normalize_equally_despite_decoy(self):
        package(self.new,modern=True)
        a,aa=read_package(self.old);b,ba=read_package(self.new)
        self.assertEqual(a,b);self.assertEqual(aa['database_schema'],11);self.assertEqual(ba['database_schema'],18)
        self.assertEqual(a['notes']['100']['tags'],['tag'])

    def test_sources_unchanged_and_no_binary_outputs(self):
        hashes=[digest_file(p) for p in (self.old,self.new)]
        self.assertEqual(self.invoke(),0)
        self.assertEqual(hashes,[digest_file(p) for p in (self.old,self.new)])
        self.assertTrue(all(p.suffix in ('.json','.md') for p in self.root.rglob('*') if p.is_file()))

    def test_rerun_is_byte_identical(self):
        self.assertEqual(self.invoke(),0)
        before={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(self.invoke(),0)
        after={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_future_release_preserves_history_and_editorial_text(self):
        self.assertEqual(self.invoke(),0)
        old_snapshot=(self.root/'snapshots/2026-01-01.json').read_bytes()
        old_report=(self.root/'reports/2026-01-01_to_2026-02-01.md').read_bytes()
        changelog=self.root/'CHANGELOG.md';changelog.write_text(changelog.read_text()+'\nMy manually reviewed commentary.\n')
        third=self.base/'third.apkg';package(third,modern=True,back='Third answer',mod=300)
        with patch.object(release,'ROOT',self.root),contextlib.redirect_stdout(io.StringIO()):
            code=release.run([str(self.new),str(third),'--baseline-date','2026-02-01','--release-date','2027-01-15'])
        self.assertEqual(code,0)
        data=json.loads((self.root/'website/releases.json').read_text())
        self.assertEqual(len(data['releases']),3);self.assertEqual(data['latest_release_date'],'2027-01-15')
        self.assertEqual(data['latest_published_release_date'],'2026-02-01')
        self.assertIn('My manually reviewed commentary.',changelog.read_text())
        self.assertEqual(old_snapshot,(self.root/'snapshots/2026-01-01.json').read_bytes())
        self.assertEqual(old_report,(self.root/'reports/2026-01-01_to_2026-02-01.md').read_bytes())

    def test_unknown_package_version_fails_without_outputs(self):
        package(self.new,modern=True,version=99)
        self.assertEqual(self.invoke(),2);self.assertEqual(list(self.root.iterdir()),[])

    def test_corrupt_package_fails(self):
        self.new.write_bytes(b'not a zip');self.assertEqual(self.invoke(),2)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_check_only_writes_nothing(self):
        self.assertEqual(self.invoke(['--check-only']),0);self.assertEqual(list(self.root.iterdir()),[])

    def test_strict_warning_blocks_outputs(self):
        self.assertEqual(self.invoke(['--strict']),2);self.assertEqual(list(self.root.iterdir()),[])

    def test_conflicting_release_is_not_overwritten(self):
        self.assertEqual(self.invoke(),0)
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        package(self.new,modern=True,back='Different candidate')
        self.assertEqual(self.invoke(),2)
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_guid_survives_changed_numeric_id_and_first_field(self):
        package(self.new,modern=True,nid=101,front='Changed question',back='Changed answer',mod=200)
        a,b,aa,ba,d=self.pair()
        self.assertEqual(d['summary']['notes_added'],0);self.assertEqual(d['summary']['notes_updated'],1)
        self.assertEqual(d['matching'],{'guid':1});self.assertEqual(len(d['identity_changes']),1)

    def test_content_fallback_does_not_claim_import_identity(self):
        package(self.new,modern=True,guid='new-guid',nid=101)
        a,b,aa,ba,d=self.pair()
        self.assertEqual(d['matching'],{'exact_content':1});self.assertEqual(d['status'],'FAIL')
        self.assertTrue(any(c['name']=='Content-only matches' for c in d['checks']))

    def test_ambiguous_fallback_is_not_guessed(self):
        a,_,_,_,_=self.pair()
        note=a['notes']['100']
        old={'1':dict(note,id=1,guid='a'),'2':dict(note,id=2,guid='b')}
        new={'3':dict(note,id=3,guid='c')}
        matches,removed,added,ambiguities=match_notes(old,new)
        self.assertEqual(matches,[]);self.assertTrue(ambiguities);self.assertEqual(len(removed),2)

    def test_same_named_media_replacement_detected(self):
        package(self.new,modern=True,media=b'replacement')
        *_,d=self.pair()
        self.assertEqual(d['summary']['media_updated'],1);self.assertEqual(d['summary']['media_added'],0)
        self.assertEqual(d['summary']['cards_updated'],1)

    def test_stale_modified_note_timestamp_warns(self):
        package(self.new,modern=True,back='Changed',mod=50)
        *_,d=self.pair();self.assertEqual(d['stale_modified_notes'],['100'])

    def test_deletion_and_deck_move_are_distinct(self):
        a,b,aa,ba,d=self.pair()
        b['decks']['21']=dict(b['decks']['20'],id=21,name='Other')
        b['cards']['200']['deck_id']=21
        d=compare(a,b,aa,ba)
        self.assertEqual(len(d['deck_moves']),1);self.assertEqual(d['summary']['cards_removed'],0)
        b['notes'].clear();b['cards'].clear();b['counts'].update(notes=0,cards=0)
        d=compare(a,b,aa,ba);self.assertEqual(d['status'],'FAIL');self.assertEqual(d['summary']['cards_removed'],1)

    def test_website_has_no_internal_data_or_paths(self):
        self.assertEqual(self.invoke(),0)
        text=(self.root/'website/releases.json').read_text()
        for forbidden in ['source_sha256','guid','model_id',str(self.base),'"fields":','"templates":']:
            self.assertNotIn(forbidden,text)

    def test_symlink_output_does_not_touch_target(self):
        target=self.base/'protected';target.write_text('untouched')
        (self.root/'CHANGELOG.md').symlink_to(target)
        self.assertEqual(self.invoke(),2);self.assertEqual(target.read_text(),'untouched')

    def test_signed_merge_identifiers_are_preserved(self):
        result=config(pb(9,2**64-1),{9:('id','int64',None)})
        self.assertEqual(result['id'],-1)

    def test_unknown_database_schema_fails(self):
        package(self.new,modern=True,schema=99)
        self.assertEqual(self.invoke(),2);self.assertEqual(list(self.root.iterdir()),[])

    def test_unknown_metadata_field_fails(self):
        package(self.new,modern=True,extra_meta=pb(9,1))
        self.assertEqual(self.invoke(),2);self.assertEqual(list(self.root.iterdir()),[])

    def test_scheduling_and_timestamps_do_not_change_snapshot(self):
        package(self.new,modern=True,due=456789,mod=9999)
        a,_=read_package(self.old);b,_=read_package(self.new)
        self.assertEqual(a,b)

    def test_template_only_media_replacement_updates_card(self):
        a,b,aa,ba,d=self.pair()
        a['notes']['100']['media']=[];b['notes']['100']['media']=[]
        a['notes']['100']['fields']=copy.deepcopy(b['notes']['100']['fields'])
        for snapshot in (a,b):snapshot['models']['10']['css']='body {background:url(image.png)}'
        b['media']['image.png']['sha256']='changed'
        d=compare(a,b,aa,ba)
        self.assertEqual(d['summary']['notes_updated'],0)
        self.assertEqual(d['summary']['cards_updated'],1)

    def test_explicit_local_published_status(self):
        self.assertEqual(self.invoke(['--publication-status','published']),0)
        data=json.loads((self.root/'website/releases.json').read_text())
        self.assertEqual(data['latest_published_release_date'],'2026-02-01')
        self.assertEqual(self.invoke(),0)
        data=json.loads((self.root/'website/releases.json').read_text())
        self.assertEqual(data['releases'][0]['publication_status'],'published')


if __name__=='__main__':unittest.main()
