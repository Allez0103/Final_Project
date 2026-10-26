"""Installed EXE verification without Python paths; no ML training calls."""
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def main():
    env=dict(os.environ)
    for key in ('PYTHONPATH','PA2_DATABASE_URL','PA2_V25_PREFLIGHT'):env.pop(key,None)
    windows=Path(os.environ.get('SystemRoot','C:/Windows'))
    env['PATH']=str(windows/'System32')+';'+str(windows)
    env['PA2_DISABLE_BACKGROUND_LEARNING']='1'
    env['PA2_DATA_ROOT']=str(ROOT/'runtime-data/end-to-end-v25-context-roll')
    env['PA2_SMOKE_PROJECT']='7ff36dbc-4826-455d-9a14-2d99f2572641'
    env['PA2_SMOKE_SELECTION_ISOLATION']='1'
    outcomes=[]
    for name,flag in [('installed-gui-smoke','--gui-smoke'),('installed-native-smoke','--native-smoke')]:
        output=ROOT/f'build/v25-{name}.json'
        process=subprocess.run([str(ROOT/'PA2.exe'),flag,str(output)],env=env,cwd=ROOT,
            capture_output=True,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (ROOT/f'build/v25-{name}.stdout.log').write_bytes(process.stdout)
        (ROOT/f'build/v25-{name}.stderr.log').write_bytes(process.stderr)
        result=json.loads(output.read_text(encoding='utf-8')) if output.exists() else {}
        outcomes.append(dict(name=name,exit_code=process.returncode,result=result))
    report=dict(ok=all(r['exit_code']==0 and r['result'].get('ok') for r in outcomes),
        outcomes=outcomes,pythonpath_removed=True,path_windows_only=True,model_training_performed=False)
    (ROOT/'build/v25-installed-runtime.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(ok=report['ok'],outcomes=[dict(name=r['name'],exit_code=r['exit_code'],ok=r['result'].get('ok')) for r in outcomes])))
    return 0 if report['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
