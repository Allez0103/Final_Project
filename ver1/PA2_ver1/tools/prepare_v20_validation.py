"""Copy only managed inputs/database; preserve previous videos, caches and ZIPs."""
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'runtime-data/end-to-end-v19-final'
TARGET = ROOT/'runtime-data/end-to-end-v20-final'
REPORT = ROOT/'runtime-data/native-validation/v20-preservation.json'


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024*1024):
            value.update(chunk)
    return value.hexdigest()


def inventory():
    files = list(SOURCE.rglob('*')) + list((ROOT/'releases').glob('*.zip'))
    reference = Path('C:/Users/Win11Pro/Desktop/제공 파일')
    files += list(reference.rglob('*.stp')) + list(reference.rglob('*.step'))
    userdb = Path('C:/Users/Win11Pro/AppData/Local/THN/PA2/database/pa2-dev.sqlite3')
    if userdb.exists():
        files.append(userdb)
    return {str(p.resolve()): {'bytes': p.stat().st_size, 'sha256': digest(p)}
            for p in files if p.is_file()}


def main():
    import sys
    global TARGET, REPORT
    if '--packaged' in sys.argv:
        TARGET = ROOT/'runtime-data/end-to-end-v20-packaged'
        REPORT = ROOT/'runtime-data/native-validation/v20-packaged-preservation.json'
    if '--verify' in sys.argv:
        before = json.loads(REPORT.read_text(encoding='utf-8'))
        after = inventory()
        before.update(verified=True, unchanged=before['files'] == after,
            differences=[p for p in before['files'].keys() | after.keys()
                         if before['files'].get(p) != after.get(p)])
        REPORT.write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in before.items() if k != 'files'}, ensure_ascii=False))
        return 0 if before['unchanged'] else 1
    if TARGET.exists() or REPORT.exists():
        raise FileExistsError('Existing v20 verification copy; never overwrite')
    files = inventory(); TARGET.mkdir()
    for name in ('assets', 'cache', 'database'):
        shutil.copytree(SOURCE/name, TARGET/name)
    # Reuse the read-only geometry/color cache already exercised in preflight.
    # The final database remains a fresh copy of the original v19 database.
    if '--packaged' in sys.argv:
        cached = ROOT/'runtime-data/end-to-end-v20-final/cache/shape'
        for entry in cached.iterdir():
            target = TARGET/'cache/shape'/entry.name
            if entry.is_dir() and (entry/'complete.json').exists() and not target.exists():
                shutil.copytree(entry,target)
    for path in (SOURCE/'projects').rglob('*.json'):
        target = TARGET/path.relative_to(SOURCE)
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, target)
    report = dict(source=str(SOURCE), target=str(TARGET), files=files,
        file_count=len(files), previous_exe_sha256=digest(ROOT/'PA2.exe'), verified=False)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (TARGET/'v20-isolated-copy.json').write_text(json.dumps({'source': str(SOURCE)}), encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'files'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
