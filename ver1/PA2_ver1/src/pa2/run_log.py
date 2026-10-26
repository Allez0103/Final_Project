"""One atomic generation log per run; append confirmations without replacing draft."""
import copy,json,os,time,uuid,warnings
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from collections import Counter
from .runtime import install_root

def now():return datetime.now(timezone.utc).isoformat()

@contextmanager
def locked(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.with_suffix('.lck').open('a+b') as stream:
        if stream.seek(0,2)==0:stream.write(b'0');stream.flush()
        stream.seek(0);deadline=time.monotonic()+3
        while True:
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic()>deadline:raise OSError('로그 파일이 다른 작업에서 사용 중입니다.')
                time.sleep(.05)
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)

def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('w',encoding='utf-8') as stream:
            json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.flush();os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():temporary.unlink()

class RunLog:
    def __init__(self,database=None):self.database=database;self.root=install_root()/'log'
    def _save_with_accuracy(self,path,data):
        """Keep private details locally; emit only the explicitly allowed summary."""
        from .accuracy_log import performance_summary
        report_id=data.get('accuracy_report_id')
        try:
            parsed=uuid.UUID(report_id) if type(report_id) is str else None
            if parsed is None or parsed.version!=4:raise ValueError('Invalid report ID')
            report_id=parsed.hex
        except (ValueError,AttributeError):
            report_id=uuid.uuid4().hex
        data['accuracy_report_id']=report_id
        # Save the source first: a failed export must not lose the detailed log.
        atomic(path,data)
        destination=self.root/'accuracy_log'
        # Do not follow an existing junction/symlink to an unrelated directory.
        from .uninstaller import no_links
        no_links(destination)
        atomic(destination/f'accuracy_{report_id}.json',performance_summary(data,report_id))
    def export_existing(self):
        """Backfill generation summaries only; do not export learning/events/errors."""
        counts=dict(exported=0,failed=0,skipped=0)
        for path in sorted(self.root.glob('generation_*.json')):
            try:
                with locked(path):
                    data=json.loads(path.read_text(encoding='utf-8'))
                    if type(data) is not dict or data.get('schema_version')!='pa2-generation-log-v1':
                        counts['skipped']+=1;continue
                    self._save_with_accuracy(path,data)
                counts['exported']+=1
            except (OSError,ValueError,TypeError):counts['failed']+=1
        return counts
    def path(self,generation,plan_id=None):
        return self.root/('generation_'+(generation.id if generation else str(plan_id))+'.json')
    def project(self,pid):
        if self.database:
            from .application.project_service import ProjectService
            from dataclasses import asdict
            for p in ProjectService(self.database).list():
                if p.id==pid:return asdict(p)
        return {'id':pid}
    def parts(self,snapshot_id):
        if not self.database:return []
        from .storage.database import AssemblyGroupRecord
        with self.database.session() as session:
            return [dict(group_id=r.id.removeprefix(snapshot_id+':'),name=r.display_name,part_type=r.part_type)
                    for r in session.query(AssemblyGroupRecord).filter_by(snapshot_id=snapshot_id)]
    def generated(self,generation):
        path=self.path(generation)
        with locked(path):
            if path.exists():
                self._save_with_accuracy(path,json.loads(path.read_text(encoding='utf-8')))
                return path
            counters=Counter();stages=Counter();proxy_flags=set();proxy_versions=set()
            for row in generation.path_results_json:
                if row.get('evidence',{}).get('evaluation_source')!='native':continue
                m=row['evidence'].get('calculation_metrics',{})
                counters.update(m.get('activity_counts',{}));stages.update(m.get('timing_seconds_inclusive',{}))
                proxy=m.get('spatial_proxy',{})
                if type(proxy.get('enabled')) is bool:proxy_flags.add(proxy['enabled'])
                if type(proxy.get('version')) is str:proxy_versions.add(proxy['version'])
            self._save_with_accuracy(path,dict(schema_version='pa2-generation-log-v1',generation_id=generation.id,
                project=self.project(generation.project_id),plan_id=generation.plan_id,snapshot_id=generation.snapshot_id,
                parts=self.parts(generation.snapshot_id),
                created_at=now(),generation_mode=generation.generation_mode,settings=generation.settings_json,
                metrics=generation.metrics_json,native_activity_counts=dict(counters),
                algorithm_observations=dict(shape_proxy_enabled=next(iter(proxy_flags)) if len(proxy_flags)==1 else None,
                    shape_proxy_version=next(iter(proxy_versions)) if len(proxy_versions)==1 else None),
                stage_seconds_inclusive=dict(stages),stage_times_overlap=True,
                initial_plan=copy.deepcopy(generation.plan_snapshot_json),initial_available=True,
                accuracy=dict(available=False,reason='사용자 확정 전',physical_accuracy=False),confirmations=[]))
        return path
    def confirmed(self,generation,confirmation,comparison=None):
        plan=confirmation.plan_snapshot_json;path=self.path(generation,confirmation.plan_id)
        if generation:self.generated(generation)
        with locked(path):
            data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(
                schema_version='pa2-generation-log-v1',generation_id=None,project=self.project(confirmation.project_id),
                plan_id=confirmation.plan_id,created_at=now(),initial_available=False,initial_plan=None,confirmations=[],
                parts=self.parts(plan['input_snapshot_id']))
            entries=data['confirmations'];entry=next((r for r in entries if r['confirmation_id']==confirmation.id),None)
            if entry is None:
                entry=dict(version=len(entries)+1,confirmation_id=confirmation.id,confirmed_at=confirmation.created_at.isoformat(),
                           plan=copy.deepcopy(plan),comparison={'available':False,'reason':'최초 초안 또는 비교 정보 없음'})
                entries.append(entry)
            if comparison is not None:entry['comparison']=copy.deepcopy(comparison)
            data['accuracy']=dict(available=entry['comparison'].get('available',False),
                kind='user_confirmation_similarity_not_physical_accuracy',physical_accuracy=False,
                comparison=entry['comparison'])
            data['updated_at']=now();self._save_with_accuracy(path,data)
        return path
    def cycle(self,cycle):
        atomic(self.root/f'learning_{cycle.id}.json',dict(schema_version='pa2-learning-log-v1',
            cycle_id=cycle.id,status=cycle.status,phase=cycle.phase,updated_at=now(),
            counts=cycle.counts_json,settings=cycle.settings_json,baseline=cycle.baseline_models_json,
            results=cycle.result_json,error=cycle.error_detail))
    def event(self,kind,value):
        atomic(self.root/f'event_{uuid.uuid4()}.json',dict(schema_version='pa2-event-log-v1',kind=kind,at=now(),details=value))
    def attempt(self,project_id,mode,status,seconds,details):
        token=str(uuid.uuid4());path=self.root/f'generation_{token}.json'
        self._save_with_accuracy(path,dict(schema_version='pa2-generation-log-v1',attempt_id=token,project=self.project(project_id),
            created_at=now(),generation_mode=mode,status=status,metrics={'generation_wall_sec':seconds},
            initial_available=False,initial_plan=None,confirmations=[],accuracy={'available':False,'physical_accuracy':False},details=details))
        return path

def safe_log(owner,method,*args):
    owner.log_warning=None
    try:return getattr(RunLog(owner.database),method)(*args)
    except Exception as exc:
        owner.log_warning='LOG_WRITE_FAILED: '+str(exc)
        warnings.warn(owner.log_warning,RuntimeWarning)
        return None
