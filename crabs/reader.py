"""Anki ZIP/SQLite readers. Source files are only opened in rb/r mode.

Only a database is decompressed to a TemporaryDirectory; SQLite opens it mode=ro.
Media is streamed through hashes without being saved to disk.
"""
import hashlib
import html
import io
import json
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote
from .protobuf import FormatError, message, one, config, varint

MAX_DB = 1024 ** 3
MAX_META = 64 * 1024 ** 2


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def decoded(stream, modern):
    if not modern:
        return stream
    try:
        import zstandard
    except ImportError as e:
        raise FormatError('Zstandard is required: install requirements.txt in your virtual environment') from e
    return zstandard.ZstdDecompressor().stream_reader(stream)


def bounded(stream, limit):
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise FormatError('Decompressed metadata/database exceeds safety limit')
    return data


FIELD = {1: ('sticky','bool',False), 2: ('rtl','bool',False), 3: ('font','text',''),
         4: ('size','int',0), 5: ('description','text',''), 6: ('plainText','bool',False),
         7: ('collapsed','bool',False), 8: ('excludeFromSearch','bool',False),
         9: ('id','int64',None), 10: ('tag','int',None), 11: ('preventDeletion','bool',False),
         255: ('other','json',{})}
TEMPLATE = {1: ('qfmt','text',''), 2: ('afmt','text',''), 3: ('bqfmt','text',''),
            4: ('bafmt','text',''), 5: ('did','int64',0), 6: ('bfont','text',''),
            7: ('bsize','int',0), 8: ('id','int64',None), 255: ('other','json',{})}
MODEL = {1: ('type','int',0), 2: ('sortf','int',0), 3: ('css','text',''),
         4: ('did','int64',0), 5: ('latexPre','text',''), 6: ('latexPost','text',''),
         7: ('latexsvg','bool',False), 9: ('originalStockKind','int',0),
         10: ('originalId','int64',None), 255: ('other','json',{})}


def flatten(cfg):
    other = cfg.pop('other', {})
    if not isinstance(other, dict) or set(other) & set(cfg):
        raise FormatError('Unsupported/conflicting Anki extension configuration')
    cfg.update(other)
    return cfg


def normalize_model(model):
    # Same canonical shape for legacy JSON and schema-18 protobuf.
    model = dict(model)
    for key in ['mod','usn','did','tags','vers']:
        model.pop(key, None)
    model.setdefault('originalStockKind', 0)
    model.setdefault('originalId', None)
    model.setdefault('latexsvg', False)
    for field in model['flds']:
        for _, (name, _, default) in FIELD.items():
            if name != 'other': field.setdefault(name, default)
        field.setdefault('media', [])
        # Editor preferences do not affect educational content.
        for name in ['sticky','collapsed','excludeFromSearch']:
            field.pop(name, None)
    for template in model['tmpls']:
        for _, (name, _, default) in TEMPLATE.items():
            if name != 'other': template.setdefault(name, default)
        template['did'] = template.get('did') or None
        template.pop('mod', None)
        template.pop('usn', None)
    model['flds'].sort(key=lambda f: f['ord'])
    model['tmpls'].sort(key=lambda t: t['ord'])
    if [f['ord'] for f in model['flds']] != list(range(len(model['flds']))):
        raise FormatError('Noncontiguous model field ordinals')
    if [t['ord'] for t in model['tmpls']] != list(range(len(model['tmpls']))):
        raise FormatError('Noncontiguous template ordinals')
    if model['type'] not in (0, 1):
        raise FormatError('Unsupported note-type kind')
    return model


def read_structure(db, version):
    times = {}
    if version == 11:
        col = db.execute('select models, decks from col').fetchone()
        models = {}
        for m in json.loads(col[0]).values():
            times[str(m['id'])] = m['mod']
            models[str(m['id'])] = normalize_model(m)
        decks = {str(d['id']): {'id':d['id'], 'name':d['name'],
                 'description':d.get('desc',''), 'markdown_description':bool(d.get('md',False)),
                 'kind':'filtered' if d.get('dyn') else 'normal'} for d in json.loads(col[1]).values()}
    else:
        models = {}
        for row in db.execute('select id,name,mtime_secs,config from notetypes order by id'):
            mid, name, mod, raw = row
            msg = message(raw, {**{k:({0} if t in ('int','int64','bool') else {2}) for k,(_,t,_) in MODEL.items()}, 8:{2}})
            # Parse repeated requirements separately; leave the rest to the scalar reader.
            cfg = {}
            for k, spec in MODEL.items():
                if k in msg:
                    val = one(msg,k)
                    typ=spec[1]
                    if typ == 'text':val=val.decode('utf-8')
                    elif typ == 'json':val=json.loads(val)
                    elif typ == 'bool':val=bool(val)
                    elif typ == 'int64' and val>=2**63:val-=2**64
                    cfg[spec[0]]=val
                else:cfg[spec[0]]=spec[2]
            cfg=flatten(cfg)
            req=[]
            for raw_req in msg.get(8,[]):
                r=message(raw_req,{1:{0},2:{0},3:{0,2}})
                ords=[]
                for v in r.get(3,[]):
                    if isinstance(v,int):ords.append(v)
                    else:
                        p=0
                        while p<len(v):
                            n,p=varint(v,p);ords.append(n)
                kind=one(r,2,0)
                if kind not in (0,1,2):raise FormatError('Unsupported card requirement kind')
                req.append([one(r,1,0),['none','any','all'][kind],ords])
            cfg.update(id=mid,name=name,req=req,flds=[],tmpls=[])
            for f in db.execute('select ord,name,config from fields where ntid=? order by ord',(mid,)):
                cfg['flds'].append(dict(flatten(config(f[2],FIELD)),ord=f[0],name=f[1]))
            for t in db.execute('select ord,name,config from templates where ntid=? order by ord',(mid,)):
                cfg['tmpls'].append(dict(flatten(config(t[2],TEMPLATE)),ord=t[0],name=t[1]))
            models[str(mid)]=normalize_model(cfg)
            times[str(mid)]=mod
        decks={}
        for did,name,raw in db.execute('select id,name,kind from decks order by id'):
            kind=message(raw,{1:{2},2:{2}})
            if 2 in kind:
                raise FormatError('Filtered decks are not supported for release exports; export normal decks')
            normal=message(one(kind,1,b''),{**{k:{0} for k in (1,2,3,5,6,7)},4:{2},8:{2},9:{2},10:{5}})
            decks[str(did)]={'id':did,'name':name.replace('\x1f','::'),
                'description':one(normal,4,b'').decode('utf-8'),
                'markdown_description':bool(one(normal,5,0)),'kind':'normal'}
    if any(d['kind']=='filtered' for d in decks.values()):
        raise FormatError('Filtered decks are not supported for release exports')
    return models, decks, times


def media_refs(text):
    refs = re.findall(r'\[sound:([^\]]+)\]', text, re.I)
    refs += [a or b or c for a,b,c in re.findall(r'(?:src|data|poster)\s*=\s*(?:"([^"]*)"|\x27([^\x27]*)\x27|([^\s>]+))',text,re.I)]
    refs += re.findall(r'url\(\s*[\x27"]?([^\x27"\)]+)',text,re.I)
    result=set()
    for value in refs:
        value=unquote(html.unescape(value.strip()))
        if value and not re.match(r'(?:[a-z]+:|//|#)',value,re.I) and '{{' not in value:
            result.add(value)
    return sorted(result)


def read_package(path):
    path=Path(path)
    if path.suffix.lower() != '.apkg':raise FormatError('Input must be an .apkg deck package')
    initial_stat=path.stat()
    source_hash=digest_file(path)
    with zipfile.ZipFile(path,'r') as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)):raise FormatError('Duplicate ZIP member names')
        if 'meta' in names:
            version=one(message(archive.read('meta'),{1:{0}}),1,0)
        else:version=2 if 'collection.anki21' in names else 1
        members={1:'collection.anki2',2:'collection.anki21',3:'collection.anki21b'}
        if version not in members:raise FormatError(f'Unsupported Anki package metadata version {version}')
        member=members[version]
        unknown=[n for n in names if not n.isdigit() and n not in {'meta','media',member,'collection.anki2'}]
        if unknown:raise FormatError(f'Unsupported archive members: {unknown}')
        if member not in names or 'media' not in names:raise FormatError('Missing authoritative collection or media manifest')
        modern=version==3
        with tempfile.TemporaryDirectory(prefix='crabs-audit-') as temp:
            dbpath=Path(temp)/'collection.sqlite'
            with archive.open(member) as src, decoded(src,modern) as stream:
                dbpath.write_bytes(bounded(stream,MAX_DB))
            db=sqlite3.connect(dbpath.as_uri()+'?mode=ro&immutable=1',uri=True)
            try:
                db.execute('pragma query_only=on')
                # Anki's Unicode collation is irrelevant to numeric ordering here.
                db.create_collation('unicase',lambda a,b:(a.casefold()>b.casefold())-(a.casefold()<b.casefold()))
                if db.execute('pragma quick_check').fetchall()!=[('ok',)]:raise FormatError('SQLite integrity check failed')
                rows=db.execute('select ver from col').fetchall()
                expected=18 if modern else 11
                if rows!=[(expected,)]:raise FormatError(f'Unsupported database schema {rows}; expected schema {expected} for {member}')
                models,decks,model_times=read_structure(db,expected)
                notes={};note_times={}
                for nid,guid,mid,tags,fields,mod,data in db.execute('select id,guid,mid,tags,flds,mod,data from notes order by id'):
                    if str(mid) not in models:raise FormatError('Note references a missing note type')
                    values=fields.split('\x1f')
                    if len(values)!=len(models[str(mid)]['flds']):raise FormatError('Note field count disagrees with note type')
                    if not guid:raise FormatError('Note has empty GUID')
                    notes[str(nid)]={'id':nid,'guid':guid,'model_id':mid,
                        'fields':[{'name':f['name'],'value':v} for f,v in zip(models[str(mid)]['flds'],values)],
                        'tags':sorted(set(tags.split())-{'marked','leech'}),
                        'media':media_refs(fields)}
                    if data:notes[str(nid)]['extra_data']=data
                    note_times[str(nid)]=mod
                cards={};seen=set()
                for cid,nid,did,ordinal,odid in db.execute('select id,nid,did,ord,odid from cards order by id'):
                    if str(nid) not in notes or str(odid or did) not in decks:raise FormatError('Dangling card note/deck reference')
                    model=models[str(notes[str(nid)]['model_id'])]
                    if ordinal<0 or (model['type']==0 and ordinal>=len(model['tmpls'])):raise FormatError('Invalid card template ordinal')
                    if (nid,ordinal) in seen:raise FormatError('Duplicate card for note/template ordinal')
                    seen.add((nid,ordinal))
                    cards[str(cid)]={'id':cid,'note_id':nid,'deck_id':odid or did,'ordinal':ordinal,
                        'template_ordinal':0 if model['type']==1 else ordinal}
            finally:db.close()
        with archive.open('media') as src, decoded(src,modern) as stream:
            raw=bounded(stream,MAX_META)
        entries=[]
        if modern:
            manifest=message(raw,{1:{2}})
            for index,raw_entry in enumerate(manifest.get(1,[])):
                e=message(raw_entry,{1:{2},2:{0},3:{2},255:{0}})
                if 255 in e:raise FormatError('Unsupported modern legacy_zip_filename media field')
                entries.append((str(index),one(e,1,b'').decode('utf-8'),one(e,2,0),one(e,3,b'')))
        else:
            mapping=json.loads(raw)
            if not isinstance(mapping,dict):raise FormatError('Invalid legacy media manifest')
            entries=[(index,name,None,None) for index,name in mapping.items()]
        media={}
        for index,name,expected_size,expected_sha1 in entries:
            if not isinstance(name,str) or not name or '/' in name or '\\' in name or name in ('.','..') or '\x00' in name:
                raise FormatError('Unsafe or invalid media filename')
            if name in media or not index.isdigit() or index not in names:raise FormatError('Duplicate or missing media entry')
            h=hashlib.sha256();h1=hashlib.sha1();size=0
            with archive.open(index) as src, decoded(src,modern) as stream:
                for chunk in iter(lambda:stream.read(1024*1024),b''):
                    size+=len(chunk);h.update(chunk);h1.update(chunk)
            if modern and (size!=expected_size or h1.digest()!=expected_sha1):raise FormatError(f'Media integrity mismatch: {name}')
            media[name]={'sha256':h.hexdigest(),'bytes':size}
        if {n for n in names if n.isdigit()}!={e[0] for e in entries}:raise FormatError('Unmapped media archive members')
    if digest_file(path)!=source_hash or path.stat().st_mtime_ns!=initial_stat.st_mtime_ns:
        raise FormatError('Source package changed during audit; no output generated')
    template_refs=set()
    for m in models.values():
        template_refs.update(media_refs(m['css']))
        for t in m['tmpls']:
            for key in ('qfmt','afmt','bqfmt','bafmt'):template_refs.update(media_refs(t[key]))
    referenced=set(template_refs)
    for n in notes.values():referenced.update(n['media'])
    snapshot={'snapshot_schema':1,'decks':decks,'models':models,'notes':notes,'cards':cards,
        'media':dict(sorted(media.items())),'referenced_media':sorted(referenced),
        'counts':{'notes':len(notes),'cards':len(cards),'media':len(media)}}
    audit={'sha256':source_hash,'package_version':version,'collection_member':member,'database_schema':expected,
           'note_times':note_times,'model_times':model_times,
           'missing_media':sorted(referenced-set(media)),
           'unreferenced_media':sorted(set(media)-referenced)}
    return snapshot,audit
