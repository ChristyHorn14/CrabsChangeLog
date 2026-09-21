#!/usr/bin/env python3
"""Build a read-only Anki release audit. Never commits, pushes, or publishes."""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys
import tempfile
from crabs.reader import read_package
from crabs.compare import compare
from crabs.output import planned_outputs
from crabs.protobuf import FormatError
from crabs.tags import deck_stats, summary_lines as tag_summary

ROOT=Path(__file__).resolve().parent


def iso_date(value):
    try:
        parsed=date.fromisoformat(value)
        if parsed.isoformat()!=value:raise ValueError()
        return value
    except ValueError:raise argparse.ArgumentTypeError('Use a YYYY-MM-DD date')


def safe_outputs(root,outputs,inputs):
    protected={p.resolve() for p in inputs}
    for path in outputs:
        if path.is_symlink() or path.resolve() in protected or root.resolve() not in path.resolve().parents:
            raise FormatError('Output path is a symlink, outside the repository, or overlaps a source input')


def write_outputs(outputs):
    # Prepare all text before replacing anything; each replacement is atomic.
    # A power loss between replacements is recoverable by rerunning the same command.
    staged=[]
    try:
        for path,text in outputs.items():
            path.parent.mkdir(parents=True,exist_ok=True)
            if path.exists() and path.read_text(encoding='utf-8')==text:continue
            fd,temp=tempfile.mkstemp(prefix='.crabs-',suffix='.txt',dir=path.parent)
            staged.append((Path(temp),path))
            with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
                f.write(text);f.flush();os.fsync(f.fileno())
        for temp,path in staged:os.replace(temp,path)
    finally:
        for temp,_ in staged:temp.unlink(missing_ok=True)


def run(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline',type=Path,help='Untouched previously published .apkg outside this repository')
    parser.add_argument('candidate',type=Path,help='Untouched candidate .apkg outside this repository')
    parser.add_argument('--baseline-date',required=True,type=iso_date)
    parser.add_argument('--release-date',required=True,type=iso_date)
    parser.add_argument('--project',default='Crabs Anki Deck')
    parser.add_argument('--publication-status',choices=['candidate','published'],help='Explicit local metadata designation after your review; does not publish or upload anything')
    parser.add_argument('--check-only',action='store_true',help='Read/compare and print checks without writing release outputs')
    parser.add_argument('--strict',action='store_true',help='Treat WARNING as blocking (exit 2, no generated release outputs)')
    parser.add_argument('--notes-file',type=Path,help='Optional UTF-8 file of reviewed public bullets, one per line; persists on rerun')
    args=parser.parse_args(argv)
    lock=ROOT/'.release.lock'
    acquired=False
    try:
        if args.baseline_date>=args.release_date:raise FormatError('Candidate date must be later than baseline date')
        for p in (args.baseline,args.candidate):
            if ROOT in p.resolve().parents:raise FormatError('Keep source .apkg files outside the repository')
        if args.baseline.resolve()==args.candidate.resolve():raise FormatError('Baseline and candidate must be different files')
        if not args.check_only:
            try:
                fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                os.close(fd);acquired=True
            except FileExistsError:raise FormatError('Another release run is active (.release.lock); if a previous run crashed, remove only that stale lock')
        old,oa=read_package(args.baseline)
        new,na=read_package(args.candidate)
        delta=compare(old,new,oa,na)
        for check in delta['checks']:print(f"{check['status']}: {check['name']} — {check['detail']}")
        print(json.dumps(delta['summary'],indent=2))
        stats=deck_stats(new,args.release_date)
        print(f"Tags: {stats['total_tags']:,} exact content tags; {stats['total_tag_nodes']:,} hierarchy nodes; {stats['untagged_notes']:,} untagged notes")
        for line in tag_summary(delta['tag_changes']):print(line)
        if delta['status']=='FAIL' or (args.strict and delta['status']=='WARNING'):
            print('STOP: release outputs were not written.',file=sys.stderr);return 2
        if args.check_only:return 0
        notes=None
        if args.notes_file:
            notes=[line.strip().removeprefix('- ') for line in args.notes_file.read_text(encoding='utf-8').splitlines() if line.strip()]
        outputs=planned_outputs(ROOT,old,new,oa,na,delta,args.baseline_date,args.release_date,args.project,notes,args.publication_status)
        safe_outputs(ROOT,outputs,[args.baseline,args.candidate])
        write_outputs(outputs)
        print('\nGenerated/verified:')
        for path in outputs:print('  '+str(path.relative_to(ROOT)))
        print('\nSTOP FOR REVIEW. No Git staging, commit, push, publication or Anki import was performed.')
        return 0
    except Exception as error:
        print(f'FAIL: {type(error).__name__}: {error}\nSTOP: no further release processing. Source packages were opened read-only.',file=sys.stderr)
        return 2
    finally:
        if acquired:lock.unlink(missing_ok=True)


if __name__=='__main__':sys.exit(run())
