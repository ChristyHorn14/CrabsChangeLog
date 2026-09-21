import copy
import json
import unittest
from crabs.tags import parse_tags, hierarchy, deck_stats, tag_changes
from crabs.output import json_text
from crabs.compare import compare
import test_release


def sample():
    return dict(notes={'1': {'id':1, 'tags':['Crabs', 'Crabs::A', 'Crabs::A::one', 'Crabs::B']},
                       '2': {'id':2, 'tags':['Crabs::A::two', 'Crabs::A::one']},
                       '3': {'id':3, 'tags':[]}},
                cards={'10':{'note_id':1,'deck_id':20}, '11':{'note_id':1,'deck_id':20},
                       '12':{'note_id':2,'deck_id':20}},
                decks={'20':{'name':'Crabs'}}, models={'1':{}}, media={})


class TagTests(unittest.TestCase):
    def test_parse_exact_case_unicode_and_study_tags(self):
        self.assertEqual(parse_tags(' Crabs::é*\tCrabs::é* marked leech A::x/y(p+) a::x "q" …::x '),
                         ['"q"','A::x/y(p+)','Crabs::é*','a::x','…::x'])

    def test_hierarchy_distinct_notes_and_cards(self):
        tree=hierarchy(sample(),'2026-01-01');root=tree['roots'][0];a=root['children'][0]
        self.assertEqual((root['direct_notes'],root['aggregate_notes'],root['aggregate_cards']),(1,2,3))
        self.assertEqual((a['direct_notes'],a['aggregate_notes'],a['aggregate_cards']),(1,2,3))
        self.assertEqual(a['depth'],1)
        self.assertEqual([c['path'] for c in a['children']],['Crabs::A::one','Crabs::A::two'])
        self.assertEqual(tree['total_tags'],5)

    def test_implicit_parent_and_unusual_components(self):
        s=sample();s['notes']['1']['tags']=['…::é/<script>*','A::::B','Case::x','case::x'];s['notes']['2']['tags']=[]
        roots=hierarchy(s,'2026-01-01')['roots'];a=roots[0]
        self.assertFalse(a['explicit']);self.assertEqual(a['direct_notes'],0)
        self.assertEqual(a['children'][0]['name'],'');self.assertEqual(len(roots),4)
        self.assertEqual(roots[-1]['children'][0]['name'],'é/<script>*')

    def test_retagging_and_changes_union_before_after(self):
        old=sample();new=copy.deepcopy(old);new['notes']['1']['tags']=['New::branch']
        new['notes']['4']={'id':4,'tags':['New::branch','New::branch::child']};del new['notes']['2']
        delta={'notes_added':[new['notes']['4']], 'notes_removed':[old['notes']['2']],
               'notes_modified':[{'old':'1','new':'1'}]}
        c=tag_changes(old,new,delta)
        self.assertEqual(c['branches_added'],['New']);self.assertEqual(c['branches_removed'],['Crabs'])
        self.assertIn('Crabs::A',c['tags_removed'])
        self.assertEqual(c['tags_added'],['New::branch','New::branch::child'])
        row=next(r for r in c['by_branch'] if r['path']=='New')
        self.assertEqual((row['after_notes'],row['added_notes'],row['modified_notes']),(2,1,1))
        row=next(r for r in c['by_branch'] if r['path']=='Crabs')
        self.assertEqual((row['removed_notes'],row['modified_notes']),(1,1))

    def test_stats_schema_and_deterministic_order(self):
        s=sample();stats=deck_stats(s,'2026-01-01')
        self.assertEqual(set(stats),{'schema','release_date','release_date_source','deck_name','deck_names',
            'total_notes','total_cards','total_tags','total_tag_nodes','total_media','total_note_types',
            'untagged_notes','excluded_tags'})
        self.assertEqual(stats['total_notes'],3);self.assertEqual(stats['untagged_notes'],1)
        t=hierarchy(s,'2026-01-01')
        self.assertEqual(set(t),{'schema','release_date','count_unit','total_tags','total_nodes','roots'})
        self.assertEqual(set(t['roots'][0]),{'name','path','depth','explicit','direct_notes','aggregate_notes',
            'direct_cards','aggregate_cards','children'})
        s['notes']=dict(reversed(list(s['notes'].items())))
        self.assertEqual(json_text(t),json_text(hierarchy(s,'2026-01-01')))

    def test_no_changes_and_no_tags(self):
        s=sample();c=tag_changes(s,s,dict(notes_added=[],notes_removed=[],notes_modified=[]))
        self.assertEqual(c['by_branch'],[]);self.assertEqual(c['tags_added'],[])
        for n in s['notes'].values():n['tags']=[]
        self.assertEqual(hierarchy(s,'2026-01-01')['roots'],[])
        self.assertEqual(deck_stats(s,'2026-01-01')['untagged_notes'],3)


class IdentityTests(unittest.TestCase):
    setUp=test_release.ReleaseTests.setUp
    pair=test_release.ReleaseTests.pair
    invoke=test_release.ReleaseTests.invoke

    def test_renamed_deck_blocks(self):
        a,b,aa,ba,_=self.pair();b['decks']['20']['name']='Renamed'
        d=compare(a,b,aa,ba);self.assertEqual(d['status'],'FAIL')
        self.assertTrue(any(c['name']=='Deck renamed' and c['status']=='FAIL' for c in d['checks']))

    def test_primary_deck_id_loss_blocks(self):
        a,b,aa,ba,_=self.pair();b['decks']['21']=b['decks'].pop('20');b['cards']['200']['deck_id']=21
        self.assertEqual(compare(a,b,aa,ba)['status'],'FAIL')

    def test_model_identity_change_blocks_even_with_shared_guid(self):
        a,b,aa,ba,_=self.pair();b['models']['11']=b['models']['10'];b['notes']['100']['model_id']=11
        self.assertEqual(compare(a,b,aa,ba)['status'],'FAIL')

    def test_editorial_notes_persist(self):
        source=self.base/'editorial.txt';source.write_text('Author note.\n')
        self.assertEqual(self.invoke(['--notes-file',str(source)]),0);self.assertEqual(self.invoke(),0)
        self.assertIn('Author note.',(self.root/'website/whats-new.md').read_text())
        public=json.loads((self.root/'website/releases.json').read_text())
        self.assertEqual(public['releases'][0]['tag_changes']['schema'],1)

    def test_older_rerun_does_not_regress_stats_or_tags(self):
        from unittest.mock import patch
        import contextlib
        import io
        import release
        self.assertEqual(self.invoke(),0)
        third=self.base/'third.apkg'
        test_release.package(third,modern=True,back='Third answer',mod=300)
        with patch.object(release,'ROOT',self.root),contextlib.redirect_stdout(io.StringIO()):
            code=release.run([str(self.new),str(third),'--baseline-date','2026-02-01','--release-date','2026-03-01'])
        self.assertEqual(code,0)
        before=[(self.root/'website'/p).read_bytes() for p in ('deck-stats.json','tags.json')]
        self.assertEqual(self.invoke(),0)
        self.assertEqual(before,[(self.root/'website'/p).read_bytes() for p in ('deck-stats.json','tags.json')])

    def test_deck_failure_writes_nothing(self):
        from unittest.mock import patch
        import release
        a,b,aa,ba,_=self.pair();b['decks']['20']['name']='Renamed'
        with patch.object(release,'read_package',side_effect=[(a,aa),(b,ba)]):
            self.assertEqual(self.invoke(),2)
        self.assertEqual(list(self.root.iterdir()),[])
