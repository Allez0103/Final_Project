"""Post-workflow packaged native smoke and insufficient-data training guard."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'runtime-data/native-validation'


def main():
    env=dict(os.environ)
    env.pop('PYTHONPATH',None);env.pop('PA2_DATABASE_URL',None)
    system_root=os.environ.get('SystemRoot','C:/Windows')
    env['PATH']=str(Path(system_root)/'System32')+';'+system_root
    env['PA2_DATA_ROOT']=str(ROOT/'runtime-data/learning-guard-v20')
    model=Path(env['PA2_DATA_ROOT'])/'must-not-create-model'
    if model.exists():raise FileExistsError(model)
    outcomes=[]
    for name,args,expected in [
        ('learning-status',['--cli','learning-status'],0),
        ('training-guard',['--cli','train-ranking','--output',str(model)],2),
        ('native-smoke',['--native-smoke',str(EVIDENCE/'native-v20.json')],0)]:
        process=subprocess.run([str(ROOT/'PA2.exe'),*args],env=env,cwd=ROOT,
            capture_output=True,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (EVIDENCE/f'{name}-v20.stdout.log').write_bytes(process.stdout)
        (EVIDENCE/f'{name}-v20.stderr.log').write_bytes(process.stderr)
        outcomes.append(dict(name=name,exit_code=process.returncode,expected=expected,
                             ok=process.returncode==expected))
    report=dict(ok=all(r['ok'] for r in outcomes) and not model.exists(),
        outcomes=outcomes,insufficient_data_created_model=model.exists(),
        pythonpath_removed=True,path_windows_only=True,executable=str(ROOT/'PA2.exe'))
    (EVIDENCE/'runtime-v20.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
