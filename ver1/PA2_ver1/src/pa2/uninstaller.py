"""Manifest-only runtime removal; no wildcard deletion of the source/workspace."""
import ctypes,hashlib,json,os,shutil,stat,subprocess,sys,tempfile,time,uuid
from pathlib import Path

MANIFEST='.pa2-install.json'
OWNED='.pa2-owned.json'
MANAGED=('projects','database','assets','cache','jobs','learning','logs','settings.json')

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def atomic(p,value):
    tmp=p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)
def no_links(p):
    p=Path(p).absolute()
    for node in (p,*p.parents):
        if node.exists() and (node.is_symlink() or getattr(node.lstat(),'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024)):
            raise ValueError('링크/정션 경로는 삭제하지 않습니다: '+str(node))
    return p.resolve()
def safe_root(p):
    root=no_links(p)
    forbidden={Path.home().resolve(),Path(root.anchor),Path(os.environ.get('WINDIR','C:/Windows')).resolve()}
    if root in forbidden or len(root.parts)<3:raise ValueError('광범위 경로 삭제 금지: '+str(root))
    return root
def child(root,relative):
    part=Path(relative)
    if part.is_absolute() or '..' in part.parts or not part.parts:raise ValueError('관리 영역 밖 경로')
    p=no_links(root/part)
    if not p.is_relative_to(root) or p==root:raise ValueError('관리 영역 밖 경로')
    return p

def register_data(install,data):
    """Called only by the running application, never by the uninstaller itself."""
    install=safe_root(install);data=safe_root(data);path=install/MANIFEST
    if not path.exists():return  # Source checkouts are never uninstall targets.
    m=read(path);assert m['schema']=='pa2-install-v1'
    if data==install or install.is_relative_to(data):raise ValueError('데이터 경로가 프로그램/소스 상위입니다.')
    marker=data/OWNED
    owners=read(marker).get('owners',{}) if marker.exists() else {}
    owners[m['id']]=str(install)
    atomic(marker,{'schema':'pa2-owned-data-v1','owners':owners})
    m['data_roots']=sorted(set(m.get('data_roots',[]))|{str(data)});atomic(path,m)

def inventory(install):
    install=safe_root(install)
    paths=[install/'PA2.exe',install/'uninst.exe']+list((install/'_internal').rglob('*'))
    files={str(p.relative_to(install)):sha(p) for p in paths if p.is_file()}
    if 'PA2.exe' not in files or 'uninst.exe' not in files:raise ValueError('실행 파일 누락')
    existing=read(install/MANIFEST) if (install/MANIFEST).exists() else {}
    value={'schema':'pa2-install-v1','id':existing.get('id',str(uuid.uuid4())),
           'files':files,'data_roots':existing.get('data_roots',[])}
    atomic(install/MANIFEST,value);return value

def build_plan(install):
    install=safe_root(install);m=read(install/MANIFEST)
    if m.get('schema')!='pa2-install-v1':raise ValueError('올바른 설치 명세가 아닙니다.')
    files=[];preserved=[];directories=set();roots=[install]
    for relative,digest in m['files'].items():
        parts=Path(relative).parts
        if relative not in ('PA2.exe','uninst.exe') and parts[0]!='_internal':raise ValueError('프로그램 관리 목록 위반')
        p=child(install,relative)
        if not p.exists():continue
        if sha(p)!=digest:preserved.append(str(p));continue
        files.append(str(p))
    log=install/'log'
    if log.exists():
        no_links(log)
        for p in log.iterdir():
            no_links(p)
            if not p.is_file() or p.suffix!='.json':continue
            try:owned=str(read(p).get('schema_version','')).startswith('pa2-')
            except (ValueError,OSError):owned=False
            if owned:
                files.append(str(p))
                if p.with_suffix('.lck').exists():files.append(str(no_links(p.with_suffix('.lck'))))
        # Only this known child directory and this exact schema are managed.
        # Unknown files remain intact; never recursively delete the log root.
        summaries=log/'accuracy_log'
        if summaries.exists():
            no_links(summaries)
            for p in summaries.iterdir():
                no_links(p)
                if not p.is_file() or p.suffix!='.json':continue
                try:owned=read(p).get('schema_version')=='pa2-accuracy-log-v1'
                except (ValueError,OSError,AttributeError):owned=False
                if owned:files.append(str(p))
    for text in m.get('data_roots',[]):
        root=safe_root(text)
        if not root.exists():continue
        if root==install or install.is_relative_to(root):raise ValueError('광범위 데이터 경로')
        owners=read(root/OWNED).get('owners',{})
        if owners.get(m['id'])!=str(install):raise ValueError('등록된 프로젝트 소유 경로가 다릅니다: '+str(root))
        if len(owners)!=1:raise ValueError('다른 설치와 공유하는 프로젝트는 자동 삭제하지 않습니다: '+str(root))
        roots.append(root)
        for name in MANAGED:
            target=child(root,name)
            if not target.exists():continue
            if target.is_file():files.append(str(target))
            else:
                for base,dirs,names in os.walk(target,followlinks=False):
                    no_links(base)
                    for d in dirs:no_links(Path(base)/d)
                    for n in names:files.append(str(no_links(Path(base)/n)))
                    directories.add(str(Path(base)))
        files.append(str(root/OWNED))
    for text in files:
        p=Path(text)
        for parent in p.parents:
            if parent in roots:break
            if any(parent.is_relative_to(root) for root in roots):directories.add(str(parent))
    files.append(str(install/MANIFEST))
    # Include hashes and manifest so approval cannot silently cover a changed plan.
    value=dict(schema='pa2-uninstall-plan-v1',install=str(install),installation_id=m['id'],roots=list(map(str,roots)),
        files=sorted(set(files)),directories=sorted(directories,key=lambda s:(len(Path(s).parts),s.casefold()),reverse=True),preserved=preserved)
    value['approval']=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
    return value

def ensure_closed(install):
    if os.name!='nt':return
    from ctypes import wintypes
    kernel=ctypes.windll.kernel32;psapi=ctypes.windll.psapi
    kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.QueryFullProcessImageNameW.argtypes=[ctypes.c_void_p,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    ids=(wintypes.DWORD*65536)();used=wintypes.DWORD()
    if not psapi.EnumProcesses(ids,ctypes.sizeof(ids),ctypes.byref(used)):raise OSError('실행 상태 확인 실패')
    target=(Path(install)/'PA2.exe').resolve()
    for pid in list(ids)[:used.value//ctypes.sizeof(wintypes.DWORD)]:
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:continue
        try:
            text=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(32768)
            if kernel.QueryFullProcessImageNameW(handle,0,text,ctypes.byref(size)) and Path(text.value).resolve()==target:
                raise ValueError('PA²와 CAD/학습 작업을 모두 종료한 뒤 다시 실행하세요.')
        finally:kernel.CloseHandle(handle)

def execute(install,approval):
    ensure_closed(install)
    plan=build_plan(install)
    if plan['approval']!=approval:raise ValueError('삭제 범위가 바뀌었습니다. 다시 확인하세요.')
    # Preflight ALL paths before the first deletion. Every target is rechecked.
    for text in plan['files']+plan['directories']:no_links(text)
    removed=[];errors=[]
    # Manifest goes last, leaving recovery information if another file is locked.
    markers=[p for p in plan['files'] if Path(p).name==OWNED]
    targets=[p for p in plan['files'] if Path(p).name not in (MANIFEST,OWNED)]+markers+[str(Path(install)/MANIFEST)]
    for text in targets:
        p=no_links(text)
        if not any(p.is_relative_to(Path(root)) and p!=Path(root) for root in plan['roots']):raise ValueError('삭제 경로 이탈')
        if p.name in (MANIFEST,OWNED) and errors:continue
        try:
            if p.exists():p.unlink();removed.append(str(p))
        except OSError as exc:errors.append(dict(path=str(p),error=str(exc)))
    for text in plan['directories']:
        p=no_links(text)
        try:p.rmdir()
        except OSError:pass  # Unknown files/directories are preserved, never rmtree.
    return dict(ok=not errors,removed=removed,errors=errors,preserved=plan['preserved'],roots=plan['roots'])

def message(text,title='PA² 제거',flags=0):
    return ctypes.windll.user32.MessageBoxW(None,text,title,flags)

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--root');parser.add_argument('--approved');parser.add_argument('--parent',type=int)
    parser.add_argument('--report');parser.add_argument('--test-remove',action='store_true');args=parser.parse_args()
    root=Path(args.root).resolve() if args.root else Path(sys.executable).resolve().parent
    try:
        plan=build_plan(root)
        ensure_closed(root)
        if args.report and any(Path(args.report).resolve().is_relative_to(Path(r)) for r in plan['roots']):
            raise ValueError('보고서는 삭제 대상 밖이어야 합니다.')
        if args.test_remove:
            marker=read(root/'.pa2-uninstall-test.json')
            boundary=safe_root(marker['boundary'])
            if not root.is_relative_to(boundary) or root==boundary or any(not Path(p).is_relative_to(boundary) for p in plan['roots']):
                raise ValueError('시험 복사본 경계 이탈')
            if marker['id']!=plan['installation_id'] or not args.report:raise ValueError('시험 승인 누락')
        elif not args.approved:
            text='프로그램과 등록된 프로젝트 데이터를 제거합니다. 복구할 수 없습니다.\n\n'+ '\n'.join(plan['roots'])+f"\n\n삭제 파일: {len(plan['files'])}개\n원본 STEP·소스·미등록 파일은 보존합니다.\n계속하시겠습니까?"
            if message(text,flags=0x34)!=6:return 0
            helper=Path(tempfile.mkdtemp(prefix='PA2-uninstall-'))/'uninst.exe';shutil.copy2(sys.executable,helper)
            subprocess.Popen([str(helper),'--root',str(root),'--approved',plan['approval'],'--parent',str(os.getpid())],
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),close_fds=True)
            return 0
        if args.parent:
            kernel=ctypes.windll.kernel32;kernel.OpenProcess.restype=ctypes.c_void_p
            kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
            handle=kernel.OpenProcess(0x100000,False,args.parent)
            if handle:
                result=kernel.WaitForSingleObject(handle,15000);kernel.CloseHandle(handle)
                if result!=0:raise ValueError('제거 프로그램 종료 대기 실패')
        if not args.approved:raise ValueError('삭제 승인 없음')
        result=execute(root,args.approved)
        if args.report:
            output=Path(args.report).resolve()
            if any(output.is_relative_to(Path(r)) for r in plan['roots']):raise ValueError('보고서는 삭제 대상 밖이어야 합니다.')
            atomic(output,result)
        elif not args.test_remove:
            message('제거 완료. 외부 원본과 미등록 파일은 보존했습니다.' if result['ok'] else '일부 파일을 제거하지 못했습니다. 실행 중인 프로그램을 종료하고 다시 시도하세요.')
        return 0 if result['ok'] else 1
    except Exception as exc:
        if args.report:atomic(Path(args.report),{'ok':False,'error':str(exc)})
        else:message(str(exc),flags=0x10)
        return 1
