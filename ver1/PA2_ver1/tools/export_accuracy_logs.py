"""Backfill anonymous performance JSONs from existing local generation logs."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from pa2.run_log import RunLog


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log-dir',type=Path,help='Private log directory; default: beside PA2.exe')
    args=parser.parse_args()
    logs=RunLog()
    if args.log_dir:
        logs.root=args.log_dir.resolve()
        if not logs.root.is_dir():parser.error('--log-dir must be an existing directory')
    result=logs.export_existing()
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 1 if result['failed'] else 0


if __name__=='__main__':
    raise SystemExit(main())
