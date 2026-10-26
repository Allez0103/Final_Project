"""Copy, inventory and later verify the preserved v17 project, read-only."""
import argparse,hashlib,json,shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'runtime-data/end-to-end-v17-final'
DESTINATION=ROOT/'runtime-data/end-to-end-v19-final'
REPORT=ROOT/'runtime-data/native-validation/v19-source-preservation.json'

def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):value.update(chunk)
    return value.hexdigest()

def inventory():
    return {p.relative_to(SOURCE).as_posix():{'bytes':p.stat().st_size,'sha256':digest(p)}
            for p in SOURCE.rglob('*') if p.is_file()}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--verify',action='store_true');args=parser.parse_args()
    if args.verify:
        before=json.loads(REPORT.read_text(encoding='utf-8'));after=inventory()
        before.update(verified_after=True,original_data_unchanged=before['files']==after,
            differences=[name for name in before['files'].keys()|after.keys() if before['files'].get(name)!=after.get(name)])
        REPORT.write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in before.items() if k!='files'},ensure_ascii=False))
        if not before['original_data_unchanged']:raise AssertionError('Original v17 data changed')
    else:
        if DESTINATION.exists() or REPORT.exists():raise FileExistsError('Existing v19 verification copy/report')
        files=inventory();shutil.copytree(SOURCE,DESTINATION)
        report={'source':str(SOURCE),'test_copy':str(DESTINATION),'files':files,'file_count':len(files),
            'total_bytes':sum(row['bytes'] for row in files.values()),'previous_executable_sha256':digest(ROOT/'PA2.exe'),
            'verified_after':False}
        REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='files'},ensure_ascii=False))

if __name__=='__main__':main()
