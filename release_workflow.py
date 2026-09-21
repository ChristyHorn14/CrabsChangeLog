#!/usr/bin/env python3
"""Test, audit, generate, and optionally synchronize a local website. Never publish."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--website', type=Path, help='Optional local chrishornungmd.com checkout')
    args, release_args = parser.parse_known_args()
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT/'release.py'), *release_args], check=True)
    if '--check-only' in release_args:
        return
    if args.website:
        public = json.loads((ROOT/'website/releases.json').read_text())
        if public['latest_release_date'] != public['latest_published_release_date']:
            print('Candidate generated for review. Website unchanged: latest release is not marked published.')
        else:
            site = args.website.resolve()
            subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=site, check=True)
            command = [sys.executable, str(site/'scripts/update_crabs_release.py'), str(ROOT/'website/releases.json')]
            subprocess.run(command, check=True)
            subprocess.run(command + ['--check'], check=True)
    print('Release workflow complete. Review outputs and Git diffs. Nothing committed, uploaded, or deployed.')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
