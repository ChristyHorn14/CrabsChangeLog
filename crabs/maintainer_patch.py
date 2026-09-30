"""Copy-on-write APKG patching, with exact normalized and raw SQLite validation."""
import copy
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path
from .reader import read_package, digest_file, decoded, bounded, MAX_DB
from .compare import compare
from .maintainer import require, expected_snapshot, checksum, encoded, now


def db_dump(db):
    schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    tables = {}
    for kind, name, _, _ in schema:
        if kind == 'table':
            quoted = '"' + name.replace('"', '""') + '"'
            columns = [r[1] for r in db.execute('PRAGMA table_info(' + quoted + ')')]
            rows = sorted(db.execute('SELECT * FROM ' + quoted).fetchall(), key=repr)
            tables[name] = {'columns': columns, 'rows': rows}
    return schema, tables


def cache_text(value):
    # Pilot only handles text/html caches without embedded media or executable markup.
    require(not re.search(r'<(?:img|audio|video|object|source|script|style)\b|<!--', value, re.I),
            'Editing first/sort field with media/script/style is outside this pilot')
    return html.unescape(re.sub(r'<[^>]*>', '', value)).replace('\xa0', ' ')


def apply_patch(store, patch, output, confirmation):
    # Serialize application with all human decisions, even from another process.
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        return _apply_patch(store, patch, output, confirmation)


def _apply_patch(store, patch, output, confirmation):
    require(confirmation == patch['id'], 'Explicit confirmation must equal the previewed patch ID')
    require(patch == store.patch(patch['source_sha256']), 'Patch changed/tampered or decisions are stale; preview again')
    require(bool(patch['changes']), 'No approved changes to apply')
    export = store.export(patch['source_sha256']); source = Path(export['path']); output = Path(output).resolve()
    require(output.suffix.lower() == '.apkg' and not output.exists() and output != source.resolve(), 'Output must be a new .apkg path')
    require(not output.with_suffix('.validation.json').exists(), 'Validation report path already exists')
    require(digest_file(source) == patch['source_sha256'], 'Source package changed')
    original, audit = read_package(source)
    expected = expected_snapshot(original, patch)
    member = audit['collection_member']; modern = audit['package_version'] == 3
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='crabs-patch-', dir=output.parent) as temp:
        temp = Path(temp); dbpath = temp/'collection.sqlite'; candidate = temp/'candidate.apkg'
        with zipfile.ZipFile(source) as archive:
            with archive.open(member) as src, decoded(src, modern) as stream:
                dbpath.write_bytes(bounded(stream, MAX_DB))
            db = sqlite3.connect(dbpath)
            db.create_collation('unicase', lambda a,b: (a.casefold()>b.casefold())-(a.casefold()<b.casefold()))
            try:
                before_schema, before_tables = db_dump(db)
                expected_tables = {k: {'columns': list(v['columns']), 'rows': list(v['rows'])} for k,v in before_tables.items()}
                columns = before_tables['notes']['columns']
                changes_by_id = {}
                for c in patch['changes']:
                    changes_by_id.setdefault(c['note_id'], []).append(c)
                for nid, changes in changes_by_id.items():
                    matches = [r for r in before_tables['notes']['rows'] if r[columns.index('id')] == nid]
                    require(len(matches) == 1, 'Missing/duplicate numeric ID')
                    old = matches[0]; row = dict(zip(columns, old)); note = original['notes'][str(nid)]
                    require(row['guid'] == note['guid'], 'GUID mismatch')
                    fields = row['flds'].split('\x1f'); new_fields = list(fields); changed_indices = set()
                    names = [f['name'] for f in note['fields']]
                    for c in changes:
                        index = names.index(c['field']); require(fields[index] == c['original'], 'Stale raw field')
                        new_fields[index] = c['replacement']; changed_indices.add(index)
                    values = {'flds': '\x1f'.join(new_fields), 'mod': max(int(time.time()), row['mod']+1)}
                    if 'usn' in columns:
                        values['usn'] = -1
                    sort_index = original['models'][str(note['model_id'])].get('sortf', 0)
                    if 'sfld' in columns and sort_index in changed_indices:
                        values['sfld'] = cache_text(new_fields[sort_index])
                    if 'csum' in columns and 0 in changed_indices:
                        values['csum'] = int(hashlib.sha1(cache_text(new_fields[0]).encode()).hexdigest()[:8], 16)
                    db.execute('UPDATE notes SET ' + ','.join(k+'=?' for k in values) + ' WHERE id=? AND guid=?',
                               (*values.values(), nid, note['guid']))
                    revised = row | values
                    expected_tables['notes']['rows'].remove(old)
                    expected_tables['notes']['rows'].append(tuple(revised[k] for k in columns))
                db.commit()
                require(db.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'SQLite integrity failure')
                after_schema, after_tables = db_dump(db)
                for t in expected_tables.values():
                    t['rows'].sort(key=repr)
                require(after_schema == before_schema and after_tables == expected_tables,
                        'Raw SQLite changed outside approved fields and declared note caches/mod/usn')
            finally:
                db.close()
            raw = dbpath.read_bytes()
            if modern:
                import zstandard
                raw = zstandard.ZstdCompressor().compress(raw)
            with zipfile.ZipFile(candidate, 'w') as dest:
                dest.comment = archive.comment
                for info in archive.infolist():
                    if info.filename == member:
                        dest.writestr(info, raw)
                    else:
                        with archive.open(info) as src, dest.open(info, 'w') as out:
                            shutil.copyfileobj(src, out, 1024*1024)
        result, result_audit = read_package(candidate)
        require(result == expected, 'Output differs from exact approved snapshot')
        # Validate every non-database ZIP member, including opaque compatibility DB and media manifest.
        with zipfile.ZipFile(source) as a, zipfile.ZipFile(candidate) as b:
            require(a.namelist() == b.namelist(), 'ZIP structure changed')
            for name in a.namelist():
                if name == member:
                    continue
                def member_hash(z):
                    h = hashlib.sha256()
                    with z.open(name) as stream:
                        for chunk in iter(lambda: stream.read(1024*1024), b''):
                            h.update(chunk)
                    return h.hexdigest()
                require(member_hash(a) == member_hash(b), 'Non-database archive member changed')
        require(digest_file(source) == patch['source_sha256'], 'Source mutated during application')
        comparison = compare(original, result, audit, result_audit)
        require(comparison['status'] != 'FAIL', 'Existing release validation failed')
        require(patch == store.patch(patch['source_sha256']), 'Review decisions changed during application; preview again')
        report = {'status': 'PASS', 'created': now(), 'patch_id': patch['id'],
                  'source_sha256': patch['source_sha256'], 'output_sha256': digest_file(candidate),
                  'notes_affected': patch['notes_affected'], 'approved_changes': patch['changes'],
                  'checks': ['Exact approved snapshot equality', 'All GUIDs and numeric IDs preserved; no duplicates',
                             'Rejected/deferred/awaiting proposals not applied', 'All unapproved fields and tags unchanged',
                             'Cloze delimiters/ordinals, HTML, links and media references preserved',
                             'Image-occlusion notes untouched', 'All other SQLite rows/tables/schema unchanged',
                             'Only flds plus changed-note mod/usn and applicable sfld/csum caches updated',
                             'All other ZIP members byte-identical after ZIP decompression',
                             'Source package SHA-256 unchanged', 'Output re-read by existing release parser'],
                  'release_comparison': comparison,
                  'limitation': 'Static validation; import into a disposable Anki profile before distribution.'}
        # Hard-link publishes atomically and fails if another process created this name.
        os.link(candidate, output)
    with store.db:
        store.db.execute('INSERT INTO applications VALUES(?,?)', (checksum(report), encoded(report)))
    report_path = output.with_suffix('.validation.json')
    with report_path.open('x') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write('\n')
    return report


def export_cleared(store, plan, output, confirmation):
    """Create a cleared-note-only APKG and verify the published artifact by re-reading it."""
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        require(confirmation == plan['id'], 'Explicit confirmation must equal the previewed export ID')
        require(plan == store.cleared_export(plan['source_sha256']),
                'Export plan changed or decisions are stale; preview again')
        require(plan['cleared'], 'No cleared notes are eligible for export')
        export = store.export(plan['source_sha256']); source = Path(export['path'])
        output = Path(output).resolve(); manifest_path = output.with_suffix('.manifest.json')
        validation_path = output.with_suffix('.validation.json')
        require(output.suffix.lower() == '.apkg' and output != source.resolve(),
                'Output must be a new .apkg path')
        require(not output.exists() and not manifest_path.exists() and not validation_path.exists(),
                'Output, manifest, or validation path already exists')
        require(digest_file(source) == plan['source_sha256'], 'Source package changed')
        original, source_audit = read_package(source)
        source_notes = {n['guid']: n for n in original['notes'].values()}
        selected = {n['guid']: n for n in plan['cleared']}
        require(len(selected) == len(plan['cleared']), 'Duplicate GUID in export plan')
        expected = {}
        for guid, item in selected.items():
            note = source_notes.get(guid)
            require(note and note['id'] == item['note_id'] and note['model_id'] == item['model_id'],
                    'Missing or ambiguous note identity')
            revised = copy.deepcopy(note)
            values = {f['name']: f for f in revised['fields']}
            require(list(values) == item['field_names'], 'Field schema changed')
            for change in item['changes']:
                require(values[change['field']]['value'] == change['before'], 'Stale export field')
                values[change['field']]['value'] = change['after']
            expected[guid] = revised

        member = source_audit['collection_member']; modern = source_audit['package_version'] == 3
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='crabs-cleared-', dir=output.parent) as temp_name:
            temp = Path(temp_name); dbpath = temp/'collection.sqlite'; candidate = temp/'candidate.apkg'
            with zipfile.ZipFile(source) as archive:
                with archive.open(member) as src, decoded(src, modern) as stream:
                    dbpath.write_bytes(bounded(stream, MAX_DB))
                db = sqlite3.connect(dbpath)
                db.create_collation('unicase', lambda a,b: (a.casefold()>b.casefold())-(a.casefold()<b.casefold()))
                try:
                    note_columns = [r[1] for r in db.execute('PRAGMA table_info(notes)')]
                    keep_note_ids = {item['note_id'] for item in plan['cleared']}
                    keep_card_ids = {cid for item in plan['cleared'] for cid in item['card_ids']}
                    rows = db.execute('SELECT * FROM notes').fetchall()
                    id_index = note_columns.index('id')
                    for row in rows:
                        if row[id_index] not in keep_note_ids:
                            db.execute('DELETE FROM notes WHERE id=?', (row[id_index],))
                    card_columns = [r[1] for r in db.execute('PRAGMA table_info(cards)')]
                    for row in db.execute('SELECT * FROM cards').fetchall():
                        if row[card_columns.index('id')] not in keep_card_ids:
                            db.execute('DELETE FROM cards WHERE id=?', (row[card_columns.index('id')],))
                    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if 'revlog' in tables:
                        db.execute('DELETE FROM revlog WHERE cid NOT IN (SELECT id FROM cards)')
                    changes = {item['note_id']: item['changes'] for item in plan['cleared'] if item['changes']}
                    for note_id, note_changes in changes.items():
                        matches = [row for row in rows if row[id_index] == note_id]
                        require(len(matches) == 1, 'Missing/duplicate numeric note ID')
                        row = dict(zip(note_columns, matches[0])); note = original['notes'][str(note_id)]
                        require(row['guid'] == note['guid'], 'GUID mismatch')
                        fields = row['flds'].split('\x1f'); names = [f['name'] for f in note['fields']]
                        changed_indices = set()
                        for change in note_changes:
                            index = names.index(change['field'])
                            require(fields[index] == change['before'], 'Stale raw export field')
                            fields[index] = change['after']; changed_indices.add(index)
                        values = {'flds': '\x1f'.join(fields), 'mod': max(int(time.time()), row['mod']+1)}
                        if 'usn' in note_columns: values['usn'] = -1
                        sort_index = original['models'][str(note['model_id'])].get('sortf', 0)
                        if 'sfld' in note_columns and sort_index in changed_indices:
                            values['sfld'] = cache_text(fields[sort_index])
                        if 'csum' in note_columns and 0 in changed_indices:
                            values['csum'] = int(hashlib.sha1(cache_text(fields[0]).encode()).hexdigest()[:8], 16)
                        db.execute('UPDATE notes SET ' + ','.join(k+'=?' for k in values) +
                                   ' WHERE id=? AND guid=?', (*values.values(), note_id, row['guid']))
                    db.commit()
                    require(db.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'SQLite integrity failure')
                    require(db.execute('SELECT COUNT(*) FROM notes').fetchone()[0] == len(selected),
                            'Unexpected note count after filtering')
                    require({r[0] for r in db.execute('SELECT id FROM cards')} == keep_card_ids,
                            'Unexpected card identity after filtering')
                finally:
                    db.close()
                raw = dbpath.read_bytes()
                if modern:
                    import zstandard
                    raw = zstandard.ZstdCompressor().compress(raw)
                with zipfile.ZipFile(candidate, 'w') as dest:
                    dest.comment = archive.comment
                    for info in archive.infolist():
                        if info.filename == member: dest.writestr(info, raw)
                        else:
                            with archive.open(info) as src, dest.open(info, 'w') as out:
                                shutil.copyfileobj(src, out, 1024*1024)
            result, _ = read_package(candidate)
            result_by_guid = {n['guid']: n for n in result['notes'].values()}
            require(set(result_by_guid) == set(expected), 'Post-build note identity mismatch')
            result_cards = {c['id']: c for c in result['cards'].values()}
            expected_card_ids = {cid for item in plan['cleared'] for cid in item['card_ids']}
            require(set(result_cards) == expected_card_ids, 'Post-build card identity/count mismatch')
            for guid, wanted in expected.items():
                actual = result_by_guid[guid]
                require(actual['id'] == wanted['id'] and actual['model_id'] == wanted['model_id'],
                        'Post-build note identity mismatch')
                require(actual['fields'] == wanted['fields'] and actual['tags'] == wanted['tags'],
                        'Post-build fields/tags mismatch')
                require(actual['media'] == wanted['media'], 'Post-build media references mismatch')
            require(digest_file(source) == plan['source_sha256'], 'Source mutated during export')
            require(plan == store.cleared_export(plan['source_sha256']),
                    'Review decisions changed during export; preview again')
            output_sha = digest_file(candidate)
            os.link(candidate, output)
        created = now()
        manifest = dict(plan, export_id=plan['id'], created=created, output=str(output),
                        output_sha256=output_sha,
                        provenance={'generator': 'CrabsChangeLog cleared export',
                                    'source_recovery_path': str(source.resolve()),
                                    'audit_history_database': str(store.path.resolve())})
        report = {'status': 'PASS', 'created': created, 'export_id': plan['id'],
                  'source_sha256': plan['source_sha256'], 'output_sha256': output_sha,
                  'counts': plan['counts'],
                  'checks': ['Cleared/completed-only eligibility', 'Stable note GUID and numeric ID preservation',
                             'Exact source card identity; no generated cards', 'Note type and field schema preservation',
                             'Tags and media references preserved', 'Cloze structure preserved by approved-edit guard',
                             'Source fingerprint/drift validation', 'Post-build package re-read and exact comparison',
                             'Source package and append-only audit history unchanged'],
                  'limitation': 'Anki packages can create notes when imported into a collection that does not already contain these GUIDs; import into the matching source collection/profile.'}
        with manifest_path.open('x') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False); f.write('\n')
        with validation_path.open('x') as f:
            json.dump(report, f, indent=2, ensure_ascii=False); f.write('\n')
        store.db.execute('INSERT INTO applications VALUES(?,?)', (checksum(manifest), encoded(manifest)))
        return report
