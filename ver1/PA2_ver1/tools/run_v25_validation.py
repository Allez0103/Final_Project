"""Run the packaged workflow with Python paths removed; no source interpreter fallback."""
import argparse,json,os,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--exe',type=Path,default=ROOT/'build/distribution-v25/PA2/PA2.exe')
    parser.add_argument('--output',type=Path,default=ROOT/'build/v25-packaged.json')
    parser.add_argument('--normal',action='store_true')
    parser.add_argument('--data-root',type=Path,default=ROOT/'runtime-data/end-to-end-v25-context-roll')
    parser.add_argument('--landscape',action='store_true')
    args=parser.parse_args()
    env=dict(os.environ)
    for key in ('PYTHONPATH','PA2_DATABASE_URL','QT_QPA_PLATFORM','PA2_V25_PREFLIGHT'):env.pop(key,None)
    windows=Path(env.get('SystemRoot','C:/Windows'))
    env['PATH']=str(windows/'System32')+';'+str(windows)
    env['PA2_DATA_ROOT']=str(args.data_root.resolve())
    env['PA2_SMOKE_PROJECT']='7ff36dbc-4826-455d-9a14-2d99f2572641'
    env['PA2_DISABLE_BACKGROUND_LEARNING']='1'
    if args.landscape:env['PA2_VERIFY_TOP_LANDSCAPE']='1'
    command=[str(args.exe.resolve())]
    if not args.normal:command+=['--ui-v25-smoke',str(args.output.resolve())]
    result=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,timeout=1800,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    args.output.with_suffix('.stdout.log').write_bytes(result.stdout)
    args.output.with_suffix('.stderr.log').write_bytes(result.stderr)
    print(json.dumps(dict(exit_code=result.returncode,exe=str(args.exe),normal=args.normal)))
    return result.returncode


if __name__=='__main__':raise SystemExit(main())
