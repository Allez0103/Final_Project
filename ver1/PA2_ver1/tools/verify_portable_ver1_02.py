"""Validate the independently unpacked release without Python on the child PATH."""
import hashlib,json,os,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REPORTS=ROOT/'runtime-data/native-validation'


def main():
    package=json.loads((REPORTS/'portable-package-ver1_02.json').read_text(encoding='utf-8'))
    unpacked=Path(package['unpacked']).resolve()
    if not unpacked.is_relative_to(ROOT/'build'):raise ValueError('Unpacked runtime outside build')
    exe=unpacked/'PA2.exe'
    expected=json.loads((ROOT/'build/v26-installed-source-check.json').read_text(encoding='utf-8'))['executable_sha256']
    if hashlib.sha256(exe.read_bytes()).hexdigest()!=expected:raise AssertionError('Not the latest EXE')
    env=dict(os.environ)
    for key in ('PYTHONPATH','PYTHONHOME','PA2_DATABASE_URL','PA2_SMOKE_PROJECT','PA2_SMOKE_SETTINGS',
                'PA2_SMOKE_SELECTION_ISOLATION','QT_QPA_PLATFORM','QT_PLUGIN_PATH','QML2_IMPORT_PATH',
                'IMAGEIO_FFMPEG_EXE','PA2_V25_PREFLIGHT','PA2_VERIFY_TOP_LANDSCAPE'):env.pop(key,None)
    windows=Path(env.get('SystemRoot','C:/Windows'))
    env['PATH']=str(windows/'System32')+';'+str(windows)
    env['PA2_DATA_ROOT']=str(ROOT/'runtime-data/portable-clean-ver1_02')
    env['PA2_DISABLE_BACKGROUND_LEARNING']='1'
    outcomes=[]
    for label,flag in [('gui','--gui-smoke'),('native','--native-smoke')]:
        output=REPORTS/f'portable-{label}-ver1_02.json'
        run=subprocess.run([str(exe),flag,str(output)],cwd=unpacked,env=env,capture_output=True,
            timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (REPORTS/f'portable-{label}-ver1_02.stdout.log').write_bytes(run.stdout)
        (REPORTS/f'portable-{label}-ver1_02.stderr.log').write_bytes(run.stderr)
        result=json.loads(output.read_text(encoding='utf-8')) if output.exists() else {}
        outcomes.append(dict(name=label,exit_code=run.returncode,result=result))
    ffmpeg=next((unpacked/'_internal/imageio_ffmpeg/binaries').glob('*.exe'))
    clip=REPORTS/'portable-encode-ver1_02.mp4'
    if clip.exists():raise FileExistsError('Refusing to overwrite encoder check')
    encoder=subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','color=c=blue:s=320x180:r=30',
        '-t','1','-c:v','libx264','-pix_fmt','yuv420p',str(clip)],env=env,capture_output=True,timeout=60,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    decode=subprocess.run([str(ffmpeg),'-v','error','-nostats','-progress','pipe:1','-i',str(clip),'-f','null','-'],
        env=env,capture_output=True,timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (REPORTS/'portable-encode-ver1_02.log').write_bytes(encoder.stderr+decode.stdout+decode.stderr)
    frames=max((int(line.split('=')[1]) for line in decode.stdout.decode().splitlines() if line.startswith('frame=')),default=0)
    check=ROOT/'build/ver1_02-unpacked-source-check.json'
    source_check=subprocess.run([sys.executable,str(ROOT/'tools/check_packaged_sources.py'),'--exe',str(exe),
        '--output',str(check)],cwd=ROOT,capture_output=True,timeout=60)
    (ROOT/'build/ver1_02-unpacked-source-check.log').write_bytes(source_check.stdout+source_check.stderr)
    source_result=json.loads(check.read_text(encoding='utf-8')) if check.exists() else {}
    ok=all(x['exit_code']==0 and x['result'].get('ok') for x in outcomes) and encoder.returncode==decode.returncode==0 and frames==30 and source_result.get('ok',False)
    result=dict(ok=ok,archive=package['archive'],archive_sha256=package['archive_sha256'],
        archive_bytes=package['archive_bytes'],unpacked=str(unpacked),executable_sha256=expected,
        outcomes=outcomes,encoder_exit=encoder.returncode,decode_exit=decode.returncode,decoded_frames=frames,
        source_modules_verified=len(source_result.get('modules',[])),source_matches=source_result.get('ok',False),
        pythonpath_removed=True,path_windows_only=True,clean_data_root=env['PA2_DATA_ROOT'],
        developer_projects_included=False,separate_pc_tested=False,model_training_performed=False)
    (REPORTS/'portable-runtime-ver1_02.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    text=f'''# PA² ver1_02 사내 배포 ZIP

2026-10-22, v26 탑뷰 자동 가로 정렬까지 반영한 실행 파일 기준.

- 파일: `{package['archive']}`
- 크기: {package['archive_bytes']:,} bytes ({package['archive_bytes']/1024/1024:.1f} MiB)
- ZIP SHA-256: `{package['archive_sha256']}`
- EXE SHA-256: `{expected}`
- 루트 폴더: PA2_ver1. PA2.exe, _internal, 사용안내, 라이브러리 고지, 파일별 체크섬 및 배포 명세 포함.
- 자체 개발 소스·가상환경·CAD·프로젝트 DB·시험 영상은 제외. 실행에 필요한 제3자 라이브러리 파일은 포함.
- 압축 생성 후 독립 폴더에 해제하고 {package['verified_files']:,}개 파일의 크기/SHA-256 일치 확인.
- 압축 해제본에서 Python 경로 제거/Windows PATH만으로 GUI 및 격리 CAD/순서 smoke 시험: {all(x['exit_code']==0 and x['result'].get('ok') for x in outcomes)}.
- 포함된 FFmpeg로 CPU 인코딩 및 전체 디코딩: {frames}/30프레임. 추적 소스 {len(source_result.get('modules',[]))}개·자산·아이콘 일치: {source_result.get('ok',False)}.
- 종합 검증: {ok}. 별도 수신 PC 시험은 아님. 모델 학습/평가/승격은 실행하지 않음.
- 기존 ZIP은 그대로 보존했고 새 버전명으로 생성함. 프로그램 기능 코드는 변경하지 않았고 사용안내만 최신화함.
- 최종 실행 파일의 62단계 조립 영상 생성/재생/탑뷰 정렬 검증은 `docs/UI_V26_TOP_LANDSCAPE_RESULT.md`에 기록되어 있음. 압축 해제본 EXE는 그 파일과 바이트 동일.

## 전달 및 실행

ZIP 전체를 전달하고, 받는 PC에서 전부 압축 해제한 후 PA2_ver1/PA2.exe를 실행한다. Python 별도 설치는 필요 없다. EXE만 따로 복사하지 말고 _internal을 같은 위치에 유지한다. 직원별 작업 데이터는 기본적으로 해당 직원의 LOCALAPPDATA/THN/PA2에 저장한다.

이 패키지는 사내 전달용이며 전자서명은 없다. 라이브러리 고지를 포함했으나 외부 공개/납품을 위한 라이선스 검토 완료나 배포 인증을 뜻하지 않는다. 자세한 고지는 압축 내 THIRD_PARTY_NOTICES에 있다.

근거: `runtime-data/native-validation/portable-package-ver1_02.json`, `portable-runtime-ver1_02.json`, `build/ver1_02-unpacked-source-check.json`.
'''
    (ROOT/'docs/DISTRIBUTION_VER1_02_RESULT.md').write_text(text,encoding='utf-8')
    print(json.dumps(dict(ok=ok,archive=package['archive'],decoded_frames=frames,
        outcomes=[dict(name=x['name'],ok=x['result'].get('ok'),exit_code=x['exit_code']) for x in outcomes])))
    return 0 if ok else 1


if __name__=='__main__':raise SystemExit(main())
