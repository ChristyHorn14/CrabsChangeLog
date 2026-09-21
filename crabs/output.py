"""Text-only audit, release history and website artifacts."""
import json
import re
from datetime import date
from pathlib import Path
from .protobuf import FormatError
from .tags import deck_stats, hierarchy, summary_lines as tag_summary


def json_text(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n'


def fenced(value):
    text=json_text(value) if not isinstance(value,str) else value
    # Content may contain Markdown fences: never let note HTML execute in the report.
    fence='`'*(max([len(m) for m in re.findall(r'`+',text)]+[2])+1)
    return fence+'json\n'+text.rstrip()+'\n'+fence+'\n'


def summary_lines(d):
    s=d['summary']
    return [f"{s['cards_added']:,} cards added; {s['cards_updated']:,} existing cards updated; {s['cards_removed']:,} cards removed from the package.",
            f"{s['notes_added']:,} notes added; {s['notes_updated']:,} notes updated ({s['notes_fields_updated']:,} with field edits, {s['notes_tags_only']:,} tags only); {s['notes_removed']:,} notes removed from the package.",
            f"{s['media_added']:,} media files added; {s['media_removed']:,} removed; {s['media_updated']:,} existing media files changed."]


def report(old,new,oa,na,d,baseline,release):
    lines=[f'# Crabs release audit: {baseline} → {release}','',f"Overall: **{d['status']}** — candidate for review; not a publication or import guarantee.",'',
           '## Safety checks','']
    lines += [f"- **{c['status']} — {c['name']}:** {c['detail']}" for c in d['checks']]
    lines += ['', '## Counts','', '| Item | Baseline | Candidate |','| --- | ---: | ---: |']
    lines += [f"| {key} | {old['counts'][key]} | {new['counts'][key]} |" for key in ('notes','cards','media')]
    lines += ['',*['- '+s for s in summary_lines(d)],'',
        'Updated cards are retained note/ordinal pairs affected by changed note fields/tags/type, model definitions, referenced media bytes, or deck placement. This is an audit count, not a prediction of Anki’s import summary. New/deleted cloze ordinals count as added/removed cards.',
        '', '## Package formats and provenance','',
        'The authoritative database is chosen from package metadata. The compatibility collection.anki2 is ignored when a newer collection is present. Source SHA-256 values are checked before and after reading. No source package is written or imported.','']
    for label,a in [('Baseline',oa),('Candidate',na)]:
        lines += [f'### {label}',f"- SHA-256: `{a['sha256']}`",f"- Package metadata: {a['package_version']}",
                  f"- Database: `{a['collection_member']}`, schema {a['database_schema']}",'']
    lines += ['## Internal deck names and IDs','', '| Release | ID | Name | Cards |', '| --- | --- | --- | ---: |']
    for label,s in [('Baseline',old),('Candidate',new)]:
        for did,deck in sorted(s['decks'].items()):
            count=sum(str(c['deck_id'])==did for c in s['cards'].values())
            name=deck['name'].replace('|','\\|').replace('\n',' ')
            lines.append(f'| {label} | {did} | {name} | {count} |')
    lines += ['', '## Note-type identity inventory','', '| Release | Model ID | Name | Fields | Templates |', '| --- | --- | --- | ---: | ---: |']
    for label,s in [('Baseline',old),('Candidate',new)]:
        for mid,model in sorted(s['models'].items()):
            name=model['name'].replace('|','\\|').replace('\n',' ')
            lines.append(f"| {label} | {mid} | {name} | {len(model['flds'])} | {len(model['tmpls'])} |")
    lines += ['', '## Matching and update identity','',fenced(d['matching']),
              'GUID is the primary correspondence key. Content-only fallbacks are explicitly identified and cannot establish Anki import identity. Unmatched notes in ambiguous groups remain in added/removed lists, so those totals are provisional when ambiguity is reported.',
              '',f"- Ambiguous groups: {len(d['ambiguities'])}",f"- Changed note identifiers: {len(d['identity_changes'])}",
              f"- Changed retained card IDs: {len(d['card_identity_changes'])}",'',
              '### Ambiguities',fenced(d['ambiguities']),'### Note identifier changes',fenced(d['identity_changes']),
              '### Reused note IDs with different GUIDs',fenced(d['reused_note_ids']),
              '### Card identifier changes',fenced(d['card_identity_changes']),
              '### Changed notes not newer than baseline',fenced(d['stale_modified_notes']),
              '### Changed models not newer than baseline',fenced(d['stale_models'])]
    for title,key in [('Tag changes','tag_changes'),('Deck structure','decks'),('Note types and templates','models'),('Deck moves','deck_moves'),('Media additions, removals and replacements','media')]:
        lines += ['',f'## {title}','',fenced(d[key])]
    lines += ['', '## Media references','',
              'Literal HTML src/data/poster, CSS url(), and [sound:] references are collected from note fields, templates and CSS. Dynamic JavaScript/template-generated references and implicit LaTeX-generated names cannot be exhaustively resolved. All packaged media bytes are hashed, including unreferenced files.','',
              '### Missing references',fenced({'baseline':oa['missing_media'],'candidate':na['missing_media']}),
              '### Packaged files not found in literal references',fenced({'baseline':oa['unreferenced_media'],'candidate':na['unreferenced_media']})]
    for title,key in [('Added notes','notes_added'),('Removed notes','notes_removed'),('Modified notes — complete before/after for every changed field','notes_modified')]:
        lines += ['',f'## {title}','']
        for item in d[key]:
            nid=item.get('id',item.get('old'))
            if key=='notes_modified':
                shown={k:v for k,v in item.items() if k not in ('before','after')}
                for prop in ('model_id','extra_data'):
                    if item['before'].get(prop)!=item['after'].get(prop):
                        shown[prop]={'before':item['before'].get(prop),'after':item['after'].get(prop)}
            else:shown=item
            lines += [f'### Note {nid}',fenced(shown)]
        if not d[key]:lines.append('None.')
    for title,key in [('Added cards','cards_added'),('Removed cards','cards_removed'),('Updated cards and reasons','cards_updated')]:
        lines += ['',f'## {title}','',fenced(d[key])]
    lines += ['', '## Import behavior references','',
              '- [Anki packaged deck updates](https://docs.ankiweb.net/importing/packaged-decks.html#updating)',
              '- [Anki GUID-based note import](https://github.com/ankitects/anki/blob/main/rslib/src/import_export/package/apkg/import/notes.rs)',
              '- [Anki package format metadata](https://github.com/ankitects/anki/blob/main/rslib/src/import_export/package/meta.rs)','']
    return '\n'.join(lines)


def history(root,old,new,oa,na,d,baseline,release,project,notes=None,publication_status=None):
    internal_path=root/'releases.json'
    data=json.loads(internal_path.read_text()) if internal_path.exists() else {'schema':1,'project':project,'releases':[]}
    if data.get('schema')!=1 or data['project']!=project:raise FormatError('Release registry schema/project mismatch')
    records={r['date']:r for r in data['releases']}
    if len(records)!=len(data['releases']):raise FormatError('Duplicate dates in release registry')
    for day,s,a in [(baseline,old,oa),(release,new,na)]:
        existing=records.get(day)
        if existing and existing['source_sha256']!=a['sha256']:
            raise FormatError(f'Release {day} already records a different source package; use a new release date, never overwrite history')
        if not existing:
            records[day]={'date':day,'version':day,'total_notes':s['counts']['notes'],'total_cards':s['counts']['cards'],
                'total_media':s['counts']['media'],'source_sha256':a['sha256'],
                'publication_status':'candidate','previous_release':None,'changes':None,'whats_new':[],
                'audit_status':'not_compared','compatibility':'not_assessed'}
    # Explicitly choosing a package as the published baseline establishes its role.
    records[baseline]['publication_status']='published'
    existing=records[release]
    if existing['previous_release'] not in (None,baseline):raise FormatError('Release already compared with a different baseline')
    existing.update(tag_changes=d['tag_changes'], previous_release=baseline,changes={k:v for k,v in d['summary'].items() if k not in ('old','new')},
        audit_status=d['status'],compatibility='review_required',whats_new=summary_lines(d)+tag_summary(d['tag_changes']))
    if notes is not None:existing['editorial_notes']=notes
    if publication_status is not None:existing['publication_status']=publication_status
    data['releases']=sorted(records.values(),key=lambda r:r['date'],reverse=True)
    public={'schema':1,'project':project,'latest_release_date':data['releases'][0]['date'],
        'latest_published_release_date':max(r['date'] for r in data['releases'] if r['publication_status']=='published'),
        'previous_release_date':data['releases'][0]['previous_release'],
        'releases':[{k:v for k,v in r.items() if k!='source_sha256'} for r in data['releases']]}
    return data,public


def human_date(day):
    value=date.fromisoformat(day)
    return f'{value:%B} {value.day}, {value.year}'


def latest_markdown(public):
    r=public['releases'][0]
    state='Release candidate' if r['publication_status']=='candidate' else 'Latest release'
    text=[f"# {public['project']}",'',f"{state}: **{human_date(r['date'])}**",'',
          f"**{r['total_cards']:,} cards · {r['total_notes']:,} notes**",'',"## What’s New",'']
    text += ['- '+s for s in r['whats_new']+r.get('editorial_notes',[])]
    if r['previous_release']:text+=['',f"Previous release: {human_date(r['previous_release'])}."]
    if r['publication_status']=='candidate':text+=['','This release is under review. The currently published download remains unchanged.']
    text+=['','Card updates may include text, tags, media, or deck placement changes. Items removed from this package may remain in an existing Anki collection after import.',
           '', 'Downloads remain available through the existing Google Form.','', '[View full changelog](../CHANGELOG.md)','']
    return '\n'.join(text)


def changelog(root,public):
    path=root/'CHANGELOG.md'
    text=path.read_text() if path.exists() else '# Crabs Anki Deck — Changelog\n\n'
    # Per-release managed regions preserve all text outside the markers, including manual notes.
    for r in reversed(public['releases']):
        start=f"<!-- crabs:release:{r['date']}:start -->"
        end=f"<!-- crabs:release:{r['date']}:end -->"
        state=' — candidate, under review' if r['publication_status']=='candidate' else ''
        block='\n'.join([start,f"## {human_date(r['date'])}{state}",'',
             f"{r['total_cards']:,} cards · {r['total_notes']:,} notes",'',
             *['- '+s for s in (r['whats_new']+r.get('editorial_notes',[]) or ['Published baseline recorded for future comparisons.'])],end])
        if start in text or end in text:
            if text.count(start)!=1 or text.count(end)!=1 or text.index(start)>text.index(end):raise FormatError('Malformed changelog managed markers')
            text=text[:text.index(start)]+block+text[text.index(end)+len(end):]
        else:
            first=text.find('<!-- crabs:release:')
            if first>=0:text=text[:first]+block+'\n\n'+text[first:]
            else:text=text.rstrip()+'\n\n'+block+'\n'
    return text


def planned_outputs(root,old,new,oa,na,d,baseline,release,project,notes=None,publication_status=None):
    data,public=history(root,old,new,oa,na,d,baseline,release,project,notes,publication_status)
    outputs={root/'snapshots'/f'{baseline}.json':json_text(old),root/'snapshots'/f'{release}.json':json_text(new),
        root/'reports'/f'{baseline}_to_{release}.md':report(old,new,oa,na,d,baseline,release),
        root/'reports'/f'{baseline}_to_{release}.checks.json':json_text({'schema':1,'baseline':baseline,'candidate':release,
            'status':d['status'],'summary':d['summary'],'checks':d['checks'],'tag_changes':d['tag_changes']}),
        root/'releases.json':json_text(data),root/'website'/'releases.json':json_text(public),
        root/'website'/'whats-new.md':latest_markdown(public),root/'CHANGELOG.md':changelog(root,public)}
    # Rerunning an older comparison must not regress the latest deck artifacts.
    latest=public['latest_release_date']
    current=new if latest==release else json.loads((root/'snapshots'/f'{latest}.json').read_text())
    outputs[root/'website'/'deck-stats.json']=json_text(deck_stats(current,latest))
    outputs[root/'website'/'tags.json']=json_text(hierarchy(current,latest))
    for filename in ('how-to-use.md','updating.md'):
        source=root/'docs'/filename
        if source.exists():outputs[root/'website'/filename]=source.read_text(encoding='utf-8')
    for path,content in outputs.items():
        if path.parent.name=='snapshots' and path.exists() and path.read_text()!=content:
            raise FormatError(f'Snapshot {path.name} already contains different normalized content; history is immutable')
    return outputs
