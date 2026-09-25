"""Loopback-only review UI. Note HTML is displayed as text, never executed."""
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from .maintainer import Store, encoded, by_guid, preview, STATUSES, SEVERITIES, CATEGORIES

def comparison(original, proposed):
    """Diff exact strings without rendering or modifying Anki HTML."""
    import difflib
    import re
    old = re.findall(r'\s+|\w+|[^\w\s]', original)
    new = re.findall(r'\s+|\w+|[^\w\s]', proposed or '')
    return [(tag, ''.join(old[a:b]), ''.join(new[c:d]))
            for tag, a, b, c, d in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()]


def review_finding(store, finding):
    finding['diff'] = comparison(finding['original'], finding['review']['final']
                                 if finding['review']['status'] == 'approved' else finding['replacement'])
    finding['history'] = [dict(r) for r in store.db.execute(
        'SELECT * FROM reviews WHERE finding_id=? ORDER BY id', (finding['id'],))]
    return finding


PAGE = '''<!doctype html><html><head><meta charset="utf-8"><title>CRABS private review</title>
<style>body{font:16px system-ui;max-width:1150px;margin:30px auto;padding:0 16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f4f6;padding:12px}article{border:1px solid #aaa;padding:18px;margin:18px 0}textarea{width:98%;min-height:160px}button,input{margin:5px;padding:8px}details{margin:10px 0}.error{color:#a00}h2{font-size:20px}del{background:#ffe0e0;color:#780000}ins{background:#d8f5dc;color:#064d14}button:disabled{opacity:.5}nav{border-top:1px solid #ccc;margin-top:20px;padding-top:12px}</style></head><body>
<h1>CRABS · Private maintainer review</h1><p>Approval saves a review decision; it does not modify the deck.</p>
<p id="context">Loading batch…</p><section id="start"><label>Reviewer <input id="reviewer" placeholder="Your name" autocomplete="name"></label><button id="start-review" disabled>Start Review</button></section>
<section id="session" hidden><p id="progress"></p><button id="refresh">Refresh saved state</button><button id="preview">Preview approved patch</button><pre id="patch" hidden></pre></section>
<p id="message" role="status" aria-live="polite"></p><main id="queue"></main>
<details><summary>Coverage and selected-note audit outcomes</summary><pre id="coverage"></pre><pre id="audits"></pre></details>
<script>''' + Path(__file__).with_name('maintainer_review.js').read_text() + '</script></body></html>'



def serve(db_path, port=8765):
    db_path = Path(db_path)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, value, status=200, html=False):
            raw = value.encode() if html else encoded(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)

        def valid_host(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def do_GET(self):
            if not self.valid_host():
                return self.respond({'error': 'Invalid local host'}, 403)
            if self.path == '/':
                return self.respond(PAGE, html=True)
            store = Store(db_path)
            try:
                if self.path == '/api/options':
                    self.respond({'status': STATUSES, 'severity': SEVERITIES, 'category': CATEGORIES})
                elif self.path == '/api/preview':
                    self.respond({'preview': preview(store.patch())})
                elif self.path == '/api/state':
                    export = store.export(); notes = by_guid(export['snapshot']); findings = store.findings()
                    findings = [f for f in findings if f['source_sha256'] == export['id']]
                    counts = {s: sum(f['review']['status']==s for f in findings) for s in STATUSES}
                    for f in findings:
                        f['note'] = notes[f['guid']]
                        import copy
                        final = copy.deepcopy(f['note'])
                        conflicts = []
                        applied = set()
                        for other in findings:
                            if other['guid'] == f['guid'] and other['review']['status'] == 'approved':
                                if other['field'] in applied:
                                    conflicts.append(other['field'])
                                applied.add(other['field'])
                                for field in final['fields']:
                                    if field['name'] == other['field']:
                                        field['value'] = other['review']['final']
                        f['approved_note'] = {'note': final, 'conflicting_fields': conflicts}
                        review_finding(store, f)
                    audits = [dict(r) for r in store.db.execute('SELECT guid,outcome,version,created FROM audits WHERE export_id=?', (export['id'],))]
                    self.respond({'batch': {'id': export['id'], 'version': export['version']}, 'coverage': store.coverage(), 'findings': findings, 'counts': counts, 'audits': audits})
                else:
                    self.respond({'error': 'Not found'}, 404)
            except (ValueError, KeyError) as e:
                self.respond({'error': str(e)}, 400)
            finally:
                store.close()

        def do_POST(self):
            origin = self.headers.get('Origin')
            if (not self.valid_host() or self.headers.get('X-CRABS-Review') != '1'
                    or origin not in (None, f'http://127.0.0.1:{self.server.server_port}')
                    or self.headers.get('Content-Type') != 'application/json'):
                return self.respond({'error': 'Local same-origin review required'}, 403)
            store = Store(db_path)
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 1_000_000:
                    raise ValueError('Invalid request size')
                body = json.loads(self.rfile.read(length))
                if self.path != '/api/review':
                    return self.respond({'error': 'Not found'}, 404)
                store.review(body['id'], body['status'], body['reviewer'], body.get('final'),
                             body.get('comment', ''), body['expected_review_id'])
                finding = next(f for f in store.findings() if f['id'] == body['id'])
                finding['note'] = by_guid(store.export()['snapshot'])[finding['guid']]
                self.respond({'saved': True, 'deck_changed': False, 'finding': review_finding(store, finding)})
            except sqlite3.Error:
                self.respond({'error': 'Database save failed. Stay on this proposal and retry or refresh saved state.'}, 503)
            except (ValueError, KeyError, TypeError) as e:
                self.respond({'error': str(e)}, 400)
            finally:
                store.close()
    server = HTTPServer(('127.0.0.1', port), Handler)
    print(f'Private review: http://127.0.0.1:{server.server_port}', flush=True)
    server.serve_forever()
