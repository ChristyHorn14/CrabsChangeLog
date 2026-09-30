#!/usr/bin/env python3
"""Private CRABS pilot: run --help or read docs/private-maintainer.md."""
import argparse
import json
from pathlib import Path
from crabs.maintainer import Store, preview
from crabs.maintainer_patch import apply_patch

ROOT = Path(__file__).resolve().parent


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT/'private-audit'/'history.sqlite')
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('ingest'); p.add_argument('package'); p.add_argument('--version', required=True)
    p = commands.add_parser('import-findings'); p.add_argument('file', type=Path)
    p = commands.add_parser('export-backfill'); p.add_argument('output', type=Path)
    p = commands.add_parser('prepare-work-backfill'); p.add_argument('output', type=Path)
    p.add_argument('--limit', type=int, default=10)
    commands.add_parser('work-backfill-status')
    p = commands.add_parser('research')
    p.add_argument('input', type=Path); p.add_argument('output', type=Path)
    p.add_argument('--checkpoint', type=Path); p.add_argument('--model')
    p.add_argument('--limit', type=int); p.add_argument('--no-import', action='store_true')
    p.add_argument('--style-guide', type=Path)
    p = commands.add_parser('reset-reviews'); p.add_argument('--date', required=True); p.add_argument('--timezone', default='America/New_York')
    commands.add_parser('coverage')
    p = commands.add_parser('serve'); p.add_argument('--port', type=int, default=8765)
    p = commands.add_parser('preview'); p.add_argument('--output', type=Path)
    p = commands.add_parser('apply'); p.add_argument('patch', type=Path); p.add_argument('--output', type=Path, required=True); p.add_argument('--confirm', required=True)
    p = commands.add_parser('export-history'); p.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.command == 'serve':
        from crabs.maintainer_ui import serve
        serve(args.db, args.port); return
    store = Store(args.db)
    try:
        if args.command == 'ingest':
            print(store.ingest(args.package, args.version))
        elif args.command == 'import-findings':
            print(json.dumps(store.import_findings(json.loads(args.file.read_text()))))
        elif args.command == 'export-backfill':
            body = store.backfill_candidates()
            with args.output.open('x') as f:
                json.dump(body, f, indent=2, ensure_ascii=False); f.write('\n')
            print(json.dumps({'output': str(args.output), 'candidate_count': body['candidate_count']}))
        elif args.command == 'prepare-work-backfill':
            if args.limit < 1 or args.limit > 20:
                raise ValueError('--limit must be between 1 and 20')
            body = store.backfill_candidates()
            total = body['candidate_count']
            body['candidates'] = body['candidates'][:args.limit]
            body['candidate_count'] = len(body['candidates'])
            body['work_driven'] = True
            body['remaining_before_batch'] = total
            body['remaining_after_import'] = total - body['candidate_count']
            with args.output.open('x') as f:
                json.dump(body, f, indent=2, ensure_ascii=False); f.write('\n')
            print(json.dumps({'output': str(args.output),
                              'batch_count': body['candidate_count'],
                              'remaining_before_batch': total,
                              'remaining_after_import': body['remaining_after_import']}))
        elif args.command == 'work-backfill-status':
            body = store.backfill_candidates()
            print(json.dumps({'source_version': body['source_version'],
                              'source_sha256': body['source_sha256'],
                              'remaining_eligible_candidates': body['candidate_count']}, indent=2))
        elif args.command == 'research':
            from crabs.research import (DEFAULT_STYLE_GUIDE, OpenAIResponsesProvider,
                                        ResearchRunner, workload_from_bundle)
            body = json.loads(args.input.read_text())
            workload = body if 'candidates' in body else workload_from_bundle(store, body)
            model = args.model or __import__('os').environ.get('CRABS_RESEARCH_MODEL')
            if not model:
                raise ValueError('--model or CRABS_RESEARCH_MODEL is required')
            checkpoint = args.checkpoint or args.output.with_suffix(args.output.suffix + '.jsonl')
            result = ResearchRunner(OpenAIResponsesProvider(model),
                                    args.style_guide or DEFAULT_STYLE_GUIDE).run(
                                        workload, checkpoint, args.limit)
            if args.output.exists():
                args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
            else:
                with args.output.open('x') as f:
                    json.dump(result, f, indent=2, ensure_ascii=False); f.write('\n')
            if (not args.no_import and not workload.get('reprocess') and
                    result['completed_count'] != result['candidate_count']):
                raise ValueError('A partial future-audit run may not be imported; resume it or use --no-import')
            imported = [] if args.no_import or not result['findings'] else store.import_findings(result)
            print(json.dumps({'output': str(args.output), 'candidate_count': result['candidate_count'],
                              'completed_count': result['completed_count'],
                              'imported_count': len(imported)}))
        elif args.command == 'coverage':
            report = store.coverage(); report.pop('notes'); print(json.dumps(report, indent=2))
        elif args.command == 'reset-reviews':
            print(json.dumps(store.reset_reviews_for_local_date(args.date, args.timezone), indent=2))
        elif args.command == 'preview':
            patch = store.patch(); print(preview(patch))
            if args.output:
                with args.output.open('x') as f:
                    json.dump(patch, f, indent=2, ensure_ascii=False); f.write('\n')
                with args.output.with_suffix('.preview.txt').open('x') as f:
                    f.write(preview(patch))
        elif args.command == 'apply':
            report = apply_patch(store, json.loads(args.patch.read_text()), args.output, args.confirm)
            print(f"{report['status']}: {report['notes_affected']} notes changed. Report: {args.output.with_suffix('.validation.json')}")
        elif args.command == 'export-history':
            tables = ('exports', 'audits', 'findings', 'reviews', 'field_reviews', 'review_edits', 'applications')
            with args.output.open('x') as f:
                json.dump({t: [dict(r) for r in store.db.execute('SELECT * FROM '+t)] for t in tables}, f, indent=2, ensure_ascii=False)
    finally:
        store.close()


if __name__ == '__main__':
    try:
        run()
    except (ValueError, OSError, KeyError) as exc:
        raise SystemExit(str(exc))
