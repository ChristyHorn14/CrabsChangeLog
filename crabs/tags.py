"""Exact, case-preserving tag paths and set-based counts; no inferred taxonomy."""
from collections import defaultdict

STUDY_TAGS = {'marked', 'leech'}


def parse_tags(raw):
    """Match the existing snapshot policy: split whitespace, deduplicate, omit study state."""
    return sorted(set(raw.split()) - STUDY_TAGS)


def tag_index(snapshot):
    direct = defaultdict(set)
    aggregate = defaultdict(set)
    for nid, note in snapshot['notes'].items():
        for tag in set(note['tags']):
            direct[tag].add(nid)
            parts = tag.split('::')
            for depth in range(1, len(parts) + 1):
                aggregate['::'.join(parts[:depth])].add(nid)
    cards = defaultdict(set)
    for cid, card in snapshot['cards'].items():
        cards[str(card['note_id'])].add(cid)
    return direct, aggregate, cards


def hierarchy(snapshot, release_date):
    direct, aggregate, cards = tag_index(snapshot)
    nodes = {}
    for path in sorted(aggregate):
        parts = path.split('::')
        nodes[path] = dict(name=parts[-1], path=path, depth=len(parts)-1,
            explicit=path in direct, direct_notes=len(direct.get(path, set())),
            aggregate_notes=len(aggregate[path]),
            direct_cards=len(set().union(*(cards[n] for n in direct.get(path, set())))),
            aggregate_cards=len(set().union(*(cards[n] for n in aggregate[path]))), children=[])
    roots = []
    for path, node in nodes.items():
        if '::' in path:
            nodes[path.rsplit('::', 1)[0]]['children'].append(node)
        else:
            roots.append(node)
    return dict(schema=1, release_date=release_date, count_unit='notes_and_cards',
                total_tags=len(direct), total_nodes=len(nodes), roots=roots)


def deck_stats(snapshot, release_date):
    direct, aggregate, _ = tag_index(snapshot)
    used = {str(c['deck_id']) for c in snapshot['cards'].values()}
    names = sorted(snapshot['decks'][i]['name'] for i in used)
    # A multi-deck package has no invented singular deck name.
    roots = sorted({name.split('::')[0] for name in names})
    tagged = set().union(*direct.values())
    return dict(schema=1, release_date=release_date, release_date_source='release_argument',
        deck_name=roots[0] if len(roots)==1 else None, deck_names=names,
        total_notes=len(snapshot['notes']), total_cards=len(snapshot['cards']),
        total_tags=len(direct), total_tag_nodes=len(aggregate),
        total_media=len(snapshot['media']), total_note_types=len(snapshot['models']),
        untagged_notes=len(snapshot['notes'])-len(tagged),
        excluded_tags=sorted(STUDY_TAGS))


def tag_changes(old, new, delta):
    od, oa, _ = tag_index(old)
    nd, na, _ = tag_index(new)
    added_notes = {str(n['id']) for n in delta['notes_added']}
    removed_notes = {str(n['id']) for n in delta['notes_removed']}
    rows = []
    for path in sorted(oa.keys() | na.keys()):
        before, after = oa.get(path, set()), na.get(path, set())
        # Count a modified matched pair once even if it carries several child tags
        # or moves between branches. Association on either side qualifies.
        modified = sum(m['old'] in before or m['new'] in after for m in delta['notes_modified'])
        row = dict(path=path, depth=len(path.split('::'))-1,
            before_notes=len(before), after_notes=len(after), net_notes=len(after)-len(before),
            added_notes=len(after & added_notes), removed_notes=len(before & removed_notes),
            modified_notes=modified)
        if row['net_notes'] or row['added_notes'] or row['removed_notes'] or modified:
            rows.append(row)
    new_paths = na.keys()-oa.keys()
    return dict(schema=1, count_unit='notes', tags_added=sorted(nd.keys()-od.keys()),
        tags_removed=sorted(od.keys()-nd.keys()),
        branches_added=sorted(p for p in new_paths if '::' not in p or p.rsplit('::',1)[0] not in new_paths),
        branches_removed=sorted(p for p in oa.keys()-na.keys() if '::' not in p or p.rsplit('::',1)[0] in na),
        by_branch=rows)


def major_changes(changes):
    # A stable mechanical definition, not a clinical importance judgment.
    return [row for row in changes['by_branch'] if row['depth']==1]


def summary_lines(changes):
    added, removed = len(changes['tags_added']), len(changes['tags_removed'])
    lines = [f"{added:,} exact {'tag' if added==1 else 'tags'} added; {removed:,} exact {'tag' if removed==1 else 'tags'} removed."]
    expansion = sorted((r for r in major_changes(changes) if r['net_notes']>0),
                       key=lambda r: (-r['net_notes'], r['path']))[:5]
    for row in expansion:
        lines.append(f"{row['path']}: +{row['net_notes']:,} associated notes net "
                     f"({row['added_notes']:,} newly added; {row['removed_notes']:,} removed; "
                     f"{row['modified_notes']:,} modified retained notes associated before or after).")
    lines.append('Branch counts include descendants and overlap across branches; changes can reflect retagging as well as new content.')
    return lines
