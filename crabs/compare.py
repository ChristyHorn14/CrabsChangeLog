"""Deterministic content matching, structural diff, and conservative release checks."""
from collections import Counter, defaultdict
from .reader import media_refs
from .tags import tag_changes


def index(notes, key):
    result=defaultdict(list)
    for nid,note in notes.items():
        value=key(note)
        if value is not None:result[value].append(nid)
    return result


def normalized(value):
    # Keep HTML and case; only line endings and edge whitespace are normalized for fallback matching.
    return value.replace('\r\n','\n').replace('\r','\n').strip()


def match_notes(old,new):
    left=set(old);right=set(new);matches=[];ambiguities=[]
    def stage(method,key):
        oi=index({i:old[i] for i in sorted(left)},key)
        ni=index({i:new[i] for i in sorted(right)},key)
        for value in sorted(oi.keys() & ni.keys(),key=str):
            a,b=oi[value],ni[value]
            if len(a)==len(b)==1:
                matches.append({'old':a[0],'new':b[0],'method':method})
                left.remove(a[0]);right.remove(b[0])
            else:
                ambiguities.append({'method':method,'old':a,'new':b})
    stage('guid',lambda n:n['guid'])
    # Same numeric ID is evidence, never sufficient when GUIDs disagree.
    stage('exact_content',lambda n:(n['model_id'],tuple((f['name'],normalized(f['value'])) for f in n['fields'])))
    stage('unique_first_field',lambda n:(n['model_id'],n['fields'][0]['name'],normalized(n['fields'][0]['value']))
          if n['fields'] and len(normalized(n['fields'][0]['value']))>=24 else None)
    # Only retain ambiguity groups still unresolved after all stronger evidence.
    ambiguities=[dict(a,old=[i for i in a['old'] if i in left],new=[i for i in a['new'] if i in right]) for a in ambiguities]
    ambiguities=[a for a in ambiguities if a['old'] and a['new']]
    return sorted(matches,key=lambda m:int(m['old'])),sorted(left,key=int),sorted(right,key=int),ambiguities


def changed_map(old,new):
    return {'added':{k:new[k] for k in sorted(new.keys()-old.keys())},
            'removed':{k:old[k] for k in sorted(old.keys()-new.keys())},
            'modified':{k:{'before':old[k],'after':new[k]} for k in sorted(old.keys() & new.keys()) if old[k]!=new[k]}}


def compare(old,new,old_audit,new_audit):
    matches,removed,added,ambiguous=match_notes(old['notes'],new['notes'])
    modified=[];identity=[];matched_map={};methods=Counter()
    for match in matches:
        a=old['notes'][match['old']];b=new['notes'][match['new']]
        matched_map[match['old']]=match['new'];methods[match['method']]+=1
        if (a['id'],a['guid'],a['model_id'])!=(b['id'],b['guid'],b['model_id']):
            identity.append(dict(match,before={k:a[k] for k in ('id','guid','model_id')},after={k:b[k] for k in ('id','guid','model_id')}))
        if any(a.get(k)!=b.get(k) for k in ('fields','tags','model_id','extra_data')):
            fields=[]
            for i in range(max(len(a['fields']),len(b['fields']))):
                av=a['fields'][i] if i<len(a['fields']) else None
                bv=b['fields'][i] if i<len(b['fields']) else None
                if av!=bv:fields.append({'ordinal':i,'before':av,'after':bv})
            modified.append(dict(match,fields=fields,tags_added=sorted(set(b['tags'])-set(a['tags'])),
                tags_removed=sorted(set(a['tags'])-set(b['tags'])),before=a,after=b))
    decks=changed_map(old['decks'],new['decks']);models=changed_map(old['models'],new['models'])
    media=changed_map(old['media'],new['media'])
    model_changed=set(models['modified'])
    note_changed={m['new'] for m in modified}
    changed_template_media=set()
    for mid,model in new['models'].items():
        refs=set(media_refs(model['css']))
        for template in model['tmpls']:
            for field in ('qfmt','afmt','bqfmt','bafmt'):refs.update(media_refs(template[field]))
        if refs & set(media['modified']):changed_template_media.add(mid)
    old_cards={(str(c['note_id']),c['ordinal']):c for c in old['cards'].values()}
    new_cards={(str(c['note_id']),c['ordinal']):c for c in new['cards'].values()}
    paired_new=set();card_added=[];card_removed=[];card_updated=[];card_identity=[];moves=[]
    for (nid,ordinal),a in sorted(old_cards.items()):
        mapped=matched_map.get(nid)
        b=new_cards.get((mapped,ordinal))
        if b is None:card_removed.append(a);continue
        paired_new.add(b['id'])
        if a['id']!=b['id']:card_identity.append({'before':a,'after':b})
        reasons=[]
        if mapped in note_changed:reasons.append('note content/tags/type')
        if str(new['notes'][mapped]['model_id']) in model_changed:reasons.append('note-type/template definition')
        if set(new['notes'][mapped]['media']) & set(media['modified']) or str(new['notes'][mapped]['model_id']) in changed_template_media:reasons.append('referenced media bytes')
        if a['deck_id']!=b['deck_id']:
            reasons.append('deck move');moves.append({'before':a,'after':b})
        if a['template_ordinal']!=b['template_ordinal']:reasons.append('template relationship')
        if reasons:card_updated.append({'before':a,'after':b,'reasons':reasons})
    card_added=[c for c in new['cards'].values() if c['id'] not in paired_new]
    checks=[]
    def check(status,name,detail):checks.append({'status':status,'name':name,'detail':detail})
    for label,s,a in [('Baseline',old,old_audit),('Candidate',new,new_audit)]:
        check('PASS',label+' package',f"Read and integrity-checked; {a['collection_member']}, metadata v{a['package_version']}, SQLite schema {a['database_schema']}; {s['counts']}")
        dup=[g for g,n in Counter(n['guid'] for n in s['notes'].values()).items() if n>1]
        check('FAIL' if dup else 'PASS',label+' GUID uniqueness',f'{len(dup)} duplicate GUIDs')
        if a['missing_media']:check('WARNING',label+' missing media',f"{len(a['missing_media'])} literal references absent; see audit")
    if not old['notes'] or not new['notes']:check('FAIL','Empty deck','At least one package has no notes')
    if not methods.get('guid'):check('FAIL','Update identity','No shared note GUIDs; candidate does not establish an update lineage')
    else:check('PASS','Shared note GUIDs',f"{methods['guid']} notes match by GUID; {sum(old['notes'][m['old']]['id']==new['notes'][m['new']]['id'] for m in matches if m['method']=='guid')} also preserve numeric note ID")
    if ambiguous:check('WARNING','Ambiguous matching',f'{len(ambiguous)} unresolved match groups; unmatched counts are provisional')
    fallback=[m for m in matches if m['method']!='guid']
    if fallback:check('WARNING','Content-only matches',f'{len(fallback)} inferred matches do NOT prove Anki update compatibility; changed GUIDs may duplicate notes')
    if identity:check('WARNING','Note identifier changes',f'{len(identity)} matched notes changed ID, GUID or model ID; inspect identity details')
    collisions=[i for i in old['notes'].keys() & new['notes'].keys() if old['notes'][i]['guid']!=new['notes'][i]['guid']]
    if collisions:check('WARNING','Reused numeric note IDs',f'{len(collisions)} IDs have different GUIDs')
    check('WARNING' if any(decks.values()) else 'PASS','Deck identity/structure',
          f"{len(decks['added'])} added, {len(decks['removed'])} removed, {len(decks['modified'])} changed deck definitions; compare names and IDs below")
    old_used={str(c['deck_id']) for c in old['cards'].values()};new_used={str(c['deck_id']) for c in new['cards'].values()}
    # Anchor the dominant baseline deck; additional/deleted ancillary decks still warn.
    deck_counts=Counter(str(c['deck_id']) for c in old['cards'].values())
    if deck_counts:
        anchor=min(deck_counts, key=lambda key: (-deck_counts[key], key))
        preserved=(anchor in new_used and anchor in new['decks'] and
                   old['decks'][anchor]['name']==new['decks'][anchor]['name'])
        check('PASS' if preserved else 'FAIL','Primary deck identity',
              'Dominant baseline deck must retain its exact name, ID, and active cards')
    renamed=[key for key in old['decks'].keys() & new['decks'].keys()
             if old['decks'][key]['name']!=new['decks'][key]['name']]
    if renamed:check('FAIL','Deck renamed','Retained deck IDs have changed names; restore the original names')
    unsafe=[m for m in identity if m['before']['guid']!=m['after']['guid'] or m['before']['model_id']!=m['after']['model_id']]
    if unsafe or collisions or ambiguous:
        check('FAIL','Unsafe note correspondence','Changed GUID/model identity, reused note IDs, or unresolved ambiguous matches require correction before release')

    if old_used and not old_used & new_used:check('WARNING','Active deck IDs','No shared IDs among decks containing cards')
    check('WARNING' if any(models.values()) else 'PASS','Note types/templates',
          f"{len(models['added'])} added, {len(models['removed'])} removed, {len(models['modified'])} modified note types")
    if card_identity:check('WARNING','Card IDs',f'{len(card_identity)} retained note/ordinal pairs have changed numeric card IDs')
    if moves:check('WARNING','Deck moves',f'{len(moves)} retained cards moved; package import may preserve users’ current deck placement')
    if removed or card_removed:check('WARNING','Removed content',f'{len(removed)} notes and {len(card_removed)} cards absent in candidate. Importing an update does not reliably delete existing user content; review separately')
    if len(removed)>max(20,len(old['notes'])//10):check('WARNING','Large deletion','More than 10% (or 20) baseline notes are absent')
    stale=[m['new'] for m in modified if new_audit['note_times'][m['new']]<=old_audit['note_times'][m['old']]]
    stale_models=[i for i in model_changed if new_audit['model_times'][i]<=old_audit['model_times'][i]]
    check('WARNING' if stale else 'PASS','Modified-note timestamps',f'{len(stale)} changed notes are not newer than baseline; default If newer import can skip these')
    if stale_models:check('WARNING','Note-type timestamps',f'{len(stale_models)} modified note types are not newer than baseline')
    missing_ids=sum(f.get('id') is None for m in new['models'].values() for f in m['flds']+m['tmpls'])
    if missing_ids:check('WARNING','Field/template merge IDs',f'{missing_ids} field/template definitions lack merge IDs; newer Anki may fall back to names when merging')
    check('WARNING','Import outcome limitation','Static audit only: user edits, import options, Anki version and note-type merging affect outcomes. No package has been imported. A clean separate test profile is recommended before publishing')
    summary={'old':old['counts'],'new':new['counts'],'notes_added':len(added),'notes_removed':len(removed),
        'notes_updated':len(modified),'notes_fields_updated':sum(bool(m['fields']) for m in modified),
        'notes_tags_only':sum(not m['fields'] and m['before']['model_id']==m['after']['model_id'] and m['before'].get('extra_data')==m['after'].get('extra_data') for m in modified),'cards_added':len(card_added),'cards_removed':len(card_removed),
        'cards_updated':len(card_updated),'media_added':len(media['added']),'media_removed':len(media['removed']),
        'media_updated':len(media['modified'])}
    result = {'summary':summary,'status':'FAIL' if any(c['status']=='FAIL' for c in checks) else 'WARNING' if any(c['status']=='WARNING' for c in checks) else 'PASS',
        'checks':checks,'matching':dict(methods),'ambiguities':ambiguous,'matches':matches,'identity_changes':identity,
        'reused_note_ids':sorted(collisions),'stale_modified_notes':stale,'stale_models':stale_models,
        'notes_added':[new['notes'][i] for i in added],'notes_removed':[old['notes'][i] for i in removed],
        'notes_modified':modified,'cards_added':card_added,'cards_removed':card_removed,'cards_updated':card_updated,
        'card_identity_changes':card_identity,'deck_moves':moves,'decks':decks,'models':models,'media':media}

    result['tag_changes'] = tag_changes(old, new, result)
    return result
