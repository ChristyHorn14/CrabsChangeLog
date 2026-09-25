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
        elif args.command == 'coverage':
            report = store.coverage(); report.pop('notes'); print(json.dumps(report, indent=2))
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
            tables = ('exports', 'audits', 'findings', 'reviews', 'applications')
            with args.output.open('x') as f:
                json.dump({t: [dict(r) for r in store.db.execute('SELECT * FROM '+t)] for t in tables}, f, indent=2, ensure_ascii=False)
    finally:
        store.close()


if __name__ == '__main__':
    try:
        run()
    except (ValueError, OSError, KeyError) as exc:
        raise SystemExit(str(exc))
