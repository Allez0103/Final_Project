"""Independent UI regression data; never modify reference/team/user originals."""
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'runtime-data/end-to-end-v20-packaged'
TARGET=ROOT/'runtime-data/end-to-end-v23-ui'
REPORT=ROOT/'build/v23-preservation.json'


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while chunk:=f.read(1024*1024):h.update(chunk)
    return h.hexdigest()


def inventory():
    files=list(SOURCE.rglob('*'))+list((ROOT/'releases').glob('*.zip'))
    for directory in [Path('C:/Users/Win11Pro/Desktop/제공 파일'),
                      Path('C:/Users/Win11Pro/Desktop/PA2_UI소스_v7_GPT전달용')]:
        files+=list(directory.rglob('*'))
    files += [Path('C:/Users/Win11Pro/Desktop/PA2_UI소스_v7_GPT읽기용.md')]
    user=Path('C:/Users/Win11Pro/AppData/Local/THN/PA2')
    files+=list((user/'database').glob('*'))+[user/'settings.json']
    return {str(p.resolve()):dict(bytes=p.stat().st_size,sha256=digest(p))
            for p in files if p.is_file()}


def main():
    if '--verify' in sys.argv:
        before=json.loads(REPORT.read_text(encoding='utf-8'));after=inventory()
        before.update(verified=True,unchanged=before['files']==after,
            differences=[p for p in before['files'].keys()|after.keys()
                         if before['files'].get(p)!=after.get(p)])
        REPORT.write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in before.items() if k!='files'},ensure_ascii=False))
        return 0 if before['unchanged'] else 1
    if TARGET.exists() or REPORT.exists():raise FileExistsError('Existing validation copy; refusing overwrite')
    files=inventory();TARGET.mkdir()
    for name in ('assets','cache','database'):shutil.copytree(SOURCE/name,TARGET/name)
    for path in (SOURCE/'projects').rglob('*.json'):
        dest=TARGET/path.relative_to(SOURCE);dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,dest)
    report=dict(source=str(SOURCE),target=str(TARGET),files=files,file_count=len(files),
        previous_exe_sha256=digest(ROOT/'PA2.exe'),verified=False)
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (TARGET/'v23-isolated-copy.json').write_text(json.dumps(dict(source=str(SOURCE))),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='files'}))
    return 0


if __name__=='__main__':raise SystemExit(main())
