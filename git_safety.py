#!/usr/bin/env python3
"""Read-only index audit: allow small text/code only; never stages or commits."""
import subprocess
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
ALLOWED={'.py','.md','.json','.txt','.toml','.yml','.yaml'}
SPECIAL={'.gitignore','.gitattributes'}


def run():
    result=subprocess.run(['git','ls-files','-z'],cwd=ROOT,check=True,capture_output=True)
    paths=[p.decode('utf-8') for p in result.stdout.split(b'\0') if p]
    failures=[]
    for name in paths:
        p=Path(name)
        if p.suffix.lower() not in ALLOWED and p.name not in SPECIAL:
            failures.append(f'{name}: unapproved file type');continue
        if any(part in {'.venv','__pycache__','tmp','work','media','extracted','collection.media'} for part in p.parts):
            failures.append(f'{name}: temporary/media directory');continue
        raw=subprocess.run(['git','show',':'+name],cwd=ROOT,check=True,capture_output=True).stdout
        try:raw.decode('utf-8')
        except UnicodeDecodeError:failures.append(f'{name}: binary/non-UTF-8 data')
        if b'\0' in raw:failures.append(f'{name}: binary NUL byte')
    staged=subprocess.run(['git','diff','--cached','--name-only'],cwd=ROOT,check=True,capture_output=True,text=True).stdout
    if failures:
        print('FAIL: unsafe files in Git index:\n'+'\n'.join(failures));return 2
    print(f'PASS: {len(paths)} indexed files are approved text/code types.')
    print('Staged changes:\n'+(staged or '(none)'))
    print('No staging, commit or push performed.')
    return 0


if __name__=='__main__':sys.exit(run())
