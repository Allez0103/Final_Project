"""Create and independently unpack an internal-delivery ZIP, without user data."""
import argparse
from datetime import datetime,timezone
from email.parser import Parser
import hashlib,json,shutil,subprocess,tempfile,zipfile,uuid
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as source:
        while chunk:=source.read(1024*1024):value.update(chunk)
    return value.hexdigest()


def license_file(path):
    return any(piece.lower()=='licenses' for piece in path.parts) or path.name.lower().startswith(
        ('license','licence','copying','copyright','notice'))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'releases/PA2_ver1_01_windows_x64.zip')
    parser.add_argument('--version',default='ver1_01')
    parser.add_argument('--report',type=Path,default=ROOT/'runtime-data/native-validation/portable-package-ver1_01.json')
    args=parser.parse_args(); archive=args.output.resolve()
    if not archive.is_relative_to(ROOT):raise ValueError('Output must be inside the project')
    report_path=args.report.resolve()
    if not report_path.is_relative_to(ROOT):raise ValueError('Report must be inside the project')
    if archive.exists():raise FileExistsError(archive)
    if not (ROOT/'PA2.exe').is_file() or not (ROOT/'_internal').is_dir():
        raise FileNotFoundError('Current runtime is missing')
    # A developer install can already reference real user projects. Only its
    # verified runtime inventory may enter a portable package, never data roots.
    installation=json.loads((ROOT/'.pa2-install.json').read_text(encoding='utf-8'))
    if installation.get('schema')!='pa2-install-v1':raise ValueError('Invalid installation manifest')
    payload=[ROOT/'PA2.exe',ROOT/'uninst.exe']+[p for p in (ROOT/'_internal').rglob('*') if p.is_file()]
    actual={str(p.relative_to(ROOT)):digest(p) for p in payload}
    if actual!=installation['files']:raise ValueError('Runtime files differ from the verified installation inventory')
    archive.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='portable-stage-',dir=ROOT/'build'))
    bundle=staging/'PA2_ver1'; bundle.mkdir()
    shutil.copy2(ROOT/'PA2.exe',bundle/'PA2.exe')
    shutil.copy2(ROOT/'uninst.exe',bundle/'uninst.exe')
    shutil.copytree(ROOT/'_internal',bundle/'_internal')
    clean_install=dict(schema='pa2-install-v1',id=str(uuid.uuid4()),files=actual,data_roots=[])
    (bundle/'.pa2-install.json').write_text(json.dumps(clean_install,ensure_ascii=False,indent=2),encoding='utf-8')
    (bundle/'log/accuracy_log').mkdir(parents=True)
    shutil.copy2(ROOT/'V28_OPERATIONS.md',bundle/'V28_OPERATIONS.md')
    shutil.copy2(ROOT/'packaging/PORTABLE_README_KO.txt',bundle/'사용안내.txt')
    (bundle/'docs').mkdir()
    shutil.copy2(ROOT/'docs/ACCURACY_LOG.md',bundle/'docs/ACCURACY_LOG.md')
    notices=bundle/'THIRD_PARTY_NOTICES'; notices.mkdir()
    # Preserve available notices from the build environment, including optional
    # runtime dependencies. This inventory is not a legal compliance verdict.
    environment=ROOT/'.venv/Lib/site-packages'
    packages=[]
    for metadata in sorted(environment.glob('*.dist-info/METADATA')):
        info=Parser().parsestr(metadata.read_text(encoding='utf-8',errors='replace'))
        if info.get('Name','').lower()=='pa2':continue
        dist=metadata.parent; copied=[]
        for candidate in dist.rglob('*'):
            if candidate.is_file() and license_file(candidate.relative_to(dist)):
                relative=candidate.relative_to(dist)
                destination=notices/'licenses'/dist.name/relative
                destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(candidate,destination); copied.append(relative.as_posix())
        packages.append(dict(name=info.get('Name'),version=info.get('Version'),
            license=info.get('License-Expression') or info.get('License'),
            project_urls=info.get_all('Project-URL',[]),available_notice_files=copied))
    # Also preserve license files shipped outside wheel metadata.
    runtime_notices=0
    for candidate in (ROOT/'_internal').rglob('*'):
        if candidate.is_file() and license_file(candidate.relative_to(ROOT/'_internal')):
            relative=candidate.relative_to(ROOT/'_internal')
            destination=notices/'runtime-licenses'/relative
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(candidate,destination); runtime_notices+=1
    (notices/'dependency-inventory.json').write_text(json.dumps(dict(
        scope='Build environment metadata and available notices; may include development-only packages',
        compliance_review_complete=False,packages=packages),ensure_ascii=False,indent=2),encoding='utf-8')
    ffmpeg=next((bundle/'_internal/imageio_ffmpeg/binaries').glob('*.exe'))
    config=subprocess.run([str(ffmpeg),'-version'],capture_output=True,text=True,check=True,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).stdout
    license_output=subprocess.run([str(ffmpeg),'-L'],capture_output=True,text=True,check=True,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (notices/'FFmpeg-build-and-license.txt').write_text(config+'\n'+license_output.stdout+'\n'+license_output.stderr,
        encoding='utf-8')
    (notices/'README.txt').write_text(
        'Available third-party license notices are copied without alteration.\n'
        'The dependency inventory describes the build environment, not a complete binary license audit.\n'
        'Qt for Python: https://doc.qt.io/qtforpython-6/licenses.html\n'
        'FFmpeg: https://ffmpeg.org/legal.html\n'
        'Included FFmpeg reports GPL version 3 or later (--enable-gpl --enable-version3).\n'
        'Corresponding source distribution and full license compliance review are not completed by this tool.\n'
        'This is an internal delivery/test candidate, not a certification for external redistribution.\n',encoding='utf-8')
    inventory=[]
    for path in sorted(bundle.rglob('*')):
        if path.is_file():inventory.append(dict(path=path.relative_to(bundle).as_posix(),
            bytes=path.stat().st_size,sha256=digest(path)))
    (bundle/'SHA256SUMS.txt').write_text(''.join(f"{row['sha256']}  {row['path']}\n" for row in inventory),encoding='utf-8')
    metadata=dict(product='PA²',version=args.version,audience='internal-users',
        created_utc=datetime.now(timezone.utc).isoformat(),digitally_signed=False,
        developer_source_included=False,developer_project_data_included=False,
        bundled_learning_reference_data_included=True,uninstaller_included=True,
        anonymous_performance_summary_enabled=True,actual_user_logs_included=False,
        installation_data_roots_removed=True,
        matching_source_and_license_review_complete=False,files=inventory)
    (bundle/'release-manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'PACKAGING files={len(inventory)} bytes={sum(r["bytes"] for r in inventory)}',flush=True)
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=5,allowZip64=True) as output:
        output.writestr('PA2_ver1/log/','')
        output.writestr('PA2_ver1/log/accuracy_log/','')
        for path in sorted(bundle.rglob('*')):
            if path.is_file():output.write(path,path.relative_to(staging).as_posix())
    verification=Path(tempfile.mkdtemp(prefix='portable-unpacked-',dir=ROOT/'build'))
    with zipfile.ZipFile(archive) as source:
        names=source.namelist()
        broken=source.testzip()
        if broken:raise AssertionError('ZIP CRC mismatch: '+broken)
        for name in names:
            resolved=(verification/name).resolve()
            if not resolved.is_relative_to(verification) or not name.startswith('PA2_ver1/'):
                raise ValueError('Unsafe archive entry: '+name)
            if any(part in ('.venv','src','tests','runtime-data','.git') for part in Path(name).parts[:2]):
                raise ValueError('Developer files in release: '+name)
        source.extractall(verification)
    unpacked=verification/'PA2_ver1'
    for row in inventory:
        path=unpacked/row['path']
        if path.stat().st_size!=row['bytes'] or digest(path)!=row['sha256']:
            raise AssertionError('Archive mismatch: '+row['path'])
    archive_hash=digest(archive)
    clean=json.loads((unpacked/'.pa2-install.json').read_text(encoding='utf-8'))
    if clean['data_roots'] or clean['id']==installation['id']:raise AssertionError('Developer install registration leaked')
    archive.with_suffix('.zip.sha256').write_text(f'{archive_hash}  {archive.name}\n',encoding='utf-8')
    result=dict(ok=True,archive=str(archive),archive_bytes=archive.stat().st_size,
        archive_sha256=archive_hash,verified_files=len(inventory),
        runtime_notice_files=runtime_notices,license_metadata_packages=len(packages),
        staging=str(bundle),unpacked=str(unpacked),
        executable_sha256=digest(unpacked/'PA2.exe'),source_executable_unchanged=digest(ROOT/'PA2.exe')==digest(unpacked/'PA2.exe'),
        uninstaller_sha256=digest(unpacked/'uninst.exe'),runtime_inventory_verified=True,
        installation_data_roots_removed=True,zip_crc_ok=True,
        separate_pc_tested=False,internal_delivery_candidate=True,
        license_compliance_review_complete=False)
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
