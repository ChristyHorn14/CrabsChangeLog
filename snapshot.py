#!/usr/bin/env python3
"""Extract one deterministic snapshot without comparing or releasing anything."""
import argparse
from pathlib import Path
import sys
from crabs.reader import read_package
from crabs.output import json_text
from crabs.protobuf import FormatError
from release import ROOT, safe_outputs, write_outputs


def run(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package',type=Path)
    parser.add_argument('--output',required=True,type=Path,help='JSON path inside this repository')
    args=parser.parse_args(argv)
    try:
        if ROOT in args.package.resolve().parents:raise FormatError('Source packages must stay outside the repository')
        if args.output.suffix!='.json':raise FormatError('Snapshot output must be .json')
        result,_=read_package(args.package)
        content=json_text(result)
        safe_outputs(ROOT,{args.output:content},[args.package])
        if args.output.exists() and args.output.read_text()!=content:raise FormatError('Refusing to overwrite a different snapshot')
        write_outputs({args.output:content})
        print(f"Snapshot verified: {result['counts']}")
        return 0
    except Exception as e:
        print(f'FAIL: {type(e).__name__}: {e}',file=sys.stderr);return 2


if __name__=='__main__':sys.exit(run())
