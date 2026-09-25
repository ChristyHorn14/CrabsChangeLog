"""Focused local review regression tests; all data is synthetic."""
import json
import subprocess
import sys
import unittest
import urllib.request
import urllib.error
from pathlib import Path
import test_maintainer
from crabs.maintainer_ui import comparison


class ReviewSessionTests(unittest.TestCase):
    setUp = test_maintainer.MaintainerTests.setUp
    bundle = test_maintainer.MaintainerTests.bundle
    def test_identity_provenance_restart_and_media(self):
        bundle = self.bundle()
        f = bundle['findings'][0]
        f['field'] = 'Back'
        f['original'] = self.snapshot['notes']['100']['fields'][1]['value']
        f['replacement'] = f['original'].replace('Answer', 'Automated answer')
        ids = self.store.import_findings(bundle)
        for status in ('approved', 'rejected', 'deferred'):
            for reviewer in ('', '  ', None):
                with self.assertRaises(ValueError):
                    self.store.review(ids[0], status, reviewer)
        final = f['replacement'].replace('Automated answer', 'Human answer')
        for invalid in (final.replace('image.png','other.png'), final.replace('[sound:voice.mp3]','')):
            with self.assertRaises(ValueError):
                self.store.review(ids[0], 'approved', 'Chris', invalid)
        self.store.review(ids[0], 'approved', ' Chris ', final)
        for i,status in enumerate(('rejected','deferred'),1):
            self.store.review(ids[i],status,'Chris')
        # A fresh process reads committed state, not an in-memory store/cache.
        raw = subprocess.check_output([sys.executable,'-c',
            'import json,sys; from crabs.maintainer import Store; s=Store(sys.argv[1]); print(json.dumps(s.findings())); s.close()', str(self.store.path)])
        saved = json.loads(raw)
        self.assertEqual(saved[0]['original'], f['original'])
        self.assertEqual(saved[0]['replacement'], f['replacement'])
        self.assertEqual(saved[0]['review']['final'], final)
        self.assertEqual([x['review']['reviewer'] for x in saved[:3]], ['Chris']*3)
        self.assertIn('<img src="image.png">[sound:voice.mp3]', final)
        self.assertEqual([x['review']['status'] for x in saved[:3]], ['approved','rejected','deferred'])

    def test_browser_controller(self):
        root = Path(__file__).resolve().parents[1]
        subprocess.run(['node', str(root/'tests/test_review_ui.js'), str(root/'crabs/maintainer_review.js')], check=True)

    def test_exact_diff(self):
        old = '<b>α old</b>\n<img src="image.png">[sound:x.mp3]'
        new = old.replace('old', 'new')
        parts = comparison(old,new)
        self.assertEqual(''.join(p[1] for p in parts),old)
        self.assertEqual(''.join(p[2] for p in parts),new)
        self.assertIn(('replace','old','new'),parts)

    def test_http_commit_and_rejection(self):
        ids=self.store.import_findings(self.bundle())
        proc=subprocess.Popen([sys.executable,'-u','-c',
            'import sys; from crabs.maintainer_ui import serve; serve(sys.argv[1],0)',str(self.store.path)],stdout=subprocess.PIPE,text=True)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(lambda: (proc.terminate(),proc.wait(timeout=5)))
        url=proc.stdout.readline().strip().split()[-1]
        def post(reviewer):
            request=urllib.request.Request(url+'/api/review',data=json.dumps({'id':ids[0],'status':'approved','reviewer':reviewer,'expected_review_id':0}).encode(),headers={'Content-Type':'application/json','X-CRABS-Review':'1'})
            return urllib.request.urlopen(request,timeout=5)
        with self.assertRaises(urllib.error.HTTPError) as error:post(' ')
        self.assertEqual(error.exception.code,400)
        with post('Chris') as response: result=json.load(response)
        self.assertTrue(result['saved']);self.assertEqual(result['finding']['review']['reviewer'],'Chris')
        with urllib.request.urlopen(url+'/api/state',timeout=5) as response: state=json.load(response)
        self.assertEqual(state['findings'][0]['review'],result['finding']['review'])
        self.assertEqual(state['findings'][0]['diff'],result['finding']['diff'])
