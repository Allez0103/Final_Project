import json,uuid,time
from pathlib import Path
from types import SimpleNamespace
from dataclasses import asdict
import pytest
from pa2.storage.database import Database,LearningProgress,LearningCycle,ConfirmationRecord
from pa2.storage.layout import DataLayout
from pa2.application.project_service import ProjectService
from pa2.application.plan_service import PlanService
from pa2.domain.models import Plan,PlanStep,PlanningStatus,AssemblyGroup,Bounds,PartType
from pa2.settings.config import AppSettings


def db(tmp_path):
    value=Database(DataLayout(tmp_path/'data'));value.initialize();return value

def plan_case(database):
    p=ProjectService(database).create('테스트','KD','HVJB')
    plan=Plan(str(uuid.uuid4()),p.id,1,'base',['base','a','b'],
        [PlanStep('a',1,(0,0,1),(0,0,-1),10),PlanStep('b',2,(1,0,0),(-1,0,0),20)],PlanningStatus.REVIEW_REQUIRED)
    groups=[AssemblyGroup(g,g,[g],PartType.UNKNOWN,Bounds(i*2,0,0,i*2+1,1,1),1,None,True) for i,g in enumerate(plan.group_ids)]
    return plan,groups

def test_generation_log_keeps_original_and_confirmation_versions(tmp_path,monkeypatch):
    monkeypatch.setenv('PA2_INSTALL_ROOT',str(tmp_path/'install'))
    database=db(tmp_path);plans=PlanService(database);plan,groups=plan_case(database)
    result=SimpleNamespace(assembly_plan=plan,metrics={'elapsed_sec':2,'native_path_calls':3},path_results=[])
    plans.save_generated(result,AppSettings())
    path=next((tmp_path/'install/log').glob('generation_*.json'));initial=json.loads(path.read_text(encoding='utf-8'))
    assert not initial['accuracy']['available'] and len(initial['initial_plan']['steps'])==2
    plan.steps.reverse()
    for i,s in enumerate(plan.steps,1):s.step_index=i
    plan.steps[0].removal_direction=(0,1,0);plan.steps[0].assembly_direction=(0,-1,0);plan.user_modified=True
    for _ in range(2):
        cid=plans.confirm(plan);plans.analyze_confirmation(cid,groups)
        plans.analyze_confirmation(cid,groups) # Re-analysis must not add a version.
    data=json.loads(path.read_text(encoding='utf-8'))
    assert data['initial_plan']==initial['initial_plan']
    assert len(data['confirmations'])==2
    assert data['accuracy']['available'] and not data['accuracy']['physical_accuracy']
    assert data['confirmations'][-1]['comparison']['all']['pair_order_ratio']==0
    assert data['confirmations'][-1]['plan']['steps'][0]['removal_direction']==[0,1,0]
    assert len(list(path.parent.glob('generation_*.json')))==1
    clone=PlanService(database);assert clone.load_original(plan.id).steps[0].group_id=='a'

def test_log_failure_does_not_undo_project_save(tmp_path,monkeypatch):
    block=tmp_path/'not-directory';block.write_text('keep',encoding='utf-8')
    monkeypatch.setenv('PA2_INSTALL_ROOT',str(block));database=db(tmp_path);plans=PlanService(database);plan,_=plan_case(database)
    with pytest.warns(RuntimeWarning,match='LOG_WRITE_FAILED'):
        plans.save_generated(SimpleNamespace(assembly_plan=plan,metrics={},path_results=[]),AppSettings())
    assert plans.load_current_draft(plan.project_id) and plans.log_warning

def test_legacy_confirmation_does_not_fabricate_initial_draft(tmp_path,monkeypatch):
    monkeypatch.setenv('PA2_INSTALL_ROOT',str(tmp_path/'install'));database=db(tmp_path);plans=PlanService(database);plan,_=plan_case(database)
    plans.confirm(plan)
    data=json.loads(next((tmp_path/'install/log').glob('generation_*.json')).read_text(encoding='utf-8'))
    assert data['initial_plan'] is None and not data['initial_available']

@pytest.mark.parametrize('count,expected',[(0,False),(9,False),(10,True),(11,True)])
def test_retrain_ten_projects_not_families_or_24_hours(count,expected):
    from pa2.learning.pipeline import due
    from pa2.storage.database import utcnow
    snapshot={'project_ids':['p'+str(i) for i in range(count)],'counts':{'families':1,'states':1}}
    assert due(snapshot,{'project_ids':[]},utcnow(),AppSettings())[0] is expected
    snapshot['project_ids']=['same']*10
    assert not due(snapshot,{'project_ids':[]},None,AppSettings())[0]

def test_failed_cycle_does_not_consume_new_projects(tmp_path,monkeypatch):
    from pa2.learning.pipeline import LearningPipeline
    monkeypatch.setenv('PA2_INSTALL_ROOT',str(tmp_path/'install'));database=db(tmp_path)
    cycle=LearningCycle(id=str(uuid.uuid4()),status='RUNNING',phase='start',snapshot_path='x',counts_json={},settings_json={},baseline_models_json={},result_json={})
    with database.session() as session:session.add(cycle);session.add(LearningProgress(key='common',baseline_json={'project_ids':['old']}))
    pipeline=LearningPipeline(database,AppSettings());pipeline.cycle=cycle;pipeline.data_snapshot={'project_ids':['old','new']}
    pipeline.checkpoint('fit failed',{},status='FAILED')
    with database.session() as session:assert session.get(LearningProgress,'common').baseline_json['project_ids']==['old']
    pipeline.checkpoint('no improvement',{},status='REJECTED')
    with database.session() as session:assert session.get(LearningProgress,'common').baseline_json['project_ids']==['old','new']

def test_bootstrap_is_once_only_common_models_and_rollback(tmp_path,monkeypatch):
    from pa2.learning.bootstrap import bootstrap
    from pa2.learning.registry import ModelRegistry
    from pa2.learning.models import LearnedTwoStageProvider
    from pa2.planning.two_stage import TwoStagePriorityProvider
    monkeypatch.setenv('PA2_INSTALL_ROOT',str(tmp_path/'install'));database=db(tmp_path)
    assert bootstrap(database)['status']=='INITIALIZED'
    registry=ModelRegistry(database);pair=registry.active_pair();assert all(pair.values())
    _,groups=plan_case(database)
    assert isinstance(registry.provider(groups,[],'base','ANOTHER_PRODUCT'),LearnedTwoStageProvider)
    (registry.path('bundles/'+pair['ranking'])/'model.txt').write_text('corrupt copy',encoding='utf-8')
    assert type(registry.provider(groups,[],'base','HVJB')) is TwoStagePriorityProvider
    assert not any(registry.active_pair().values())
    assert bootstrap(database)['status']=='ALREADY_INITIALIZED'
    assert not any(registry.active_pair().values())

def test_fixed_eval_never_in_fit_and_ties_preserved():
    from pa2.learning.bootstrap import external_cases
    from pa2.learning.data import choice_groups
    train,test=external_cases();assert len(train)==55 and len(test)==5
    assert not {c['family'] for c in train}&{c['family'] for c in test}
    assert all(c['origin'].startswith('external_synthetic') for c in train)
    queries=[q for c in train for q in choice_groups(c,'ranking')]
    assert any(sum(q['labels'])>1 for q in queries)

def removal_copy(tmp_path):
    from pa2.uninstaller import inventory,register_data
    install=tmp_path/'copy';install.mkdir();(install/'_internal').mkdir()
    for name in ('PA2.exe','uninst.exe','_internal/dependency.dll'):(install/name).write_bytes(b'owned')
    (install/'source.py').write_text('user source',encoding='utf-8')
    data=tmp_path/'app-data';(data/'projects/p1').mkdir(parents=True);(data/'projects/p1/asset.step').write_bytes(b'asset COPY')
    (data/'notes.txt').write_text('unknown: preserve',encoding='utf-8')
    external=tmp_path/'original.step';external.write_bytes(b'original')
    inventory(install);register_data(install,data)
    return install,data,external

def test_uninstall_exact_scope_and_preserve_external_source(tmp_path):
    from pa2.uninstaller import build_plan,execute
    install,data,external=removal_copy(tmp_path);plan=build_plan(install)
    assert str(external) not in plan['files'] and str(install/'source.py') not in plan['files']
    assert execute(install,plan['approval'])['ok']
    assert not (install/'PA2.exe').exists() and not (data/'projects/p1/asset.step').exists()
    assert external.read_bytes()==b'original' and (install/'source.py').exists() and (data/'notes.txt').exists()

def test_uninstall_tampered_paths_and_approval_rejected(tmp_path):
    from pa2.uninstaller import build_plan,execute,MANIFEST,atomic
    install,data,external=removal_copy(tmp_path)
    with pytest.raises(ValueError):execute(install,'bad')
    m=json.loads((install/MANIFEST).read_text());m['files']['../original.step']='x';atomic(install/MANIFEST,m)
    with pytest.raises(ValueError):build_plan(install)
    assert external.exists() and (install/'PA2.exe').exists()

def test_uninstall_shared_data_and_modified_runtime_preserved(tmp_path):
    from pa2.uninstaller import build_plan,execute,OWNED,atomic
    install,data,external=removal_copy(tmp_path)
    (install/'_internal/dependency.dll').write_bytes(b'user modification')
    plan=build_plan(install);assert str(install/'_internal/dependency.dll') in plan['preserved']
    marker=json.loads((data/OWNED).read_text());marker['owners']['other']='another-install';atomic(data/OWNED,marker)
    with pytest.raises(ValueError,match='공유'):build_plan(install)

def test_uninstall_junction_guard(tmp_path):
    from pa2.uninstaller import build_plan
    import subprocess,os
    if os.name!='nt':pytest.skip('Windows junction')
    install,data,external=removal_copy(tmp_path);outside=tmp_path/'outside';outside.mkdir();(outside/'sentinel').write_bytes(b'keep')
    # Creating/removing a link is confined to this explicit pytest copy.
    result=subprocess.run(['cmd','/c','mklink','/J',str(data/'cache'),str(outside)],capture_output=True)
    if result.returncode:pytest.skip('junction creation unavailable')
    with pytest.raises(ValueError,match='정션'):build_plan(install)
    assert (outside/'sentinel').read_bytes()==b'keep'
    os.rmdir(data/'cache')  # Remove the verified junction itself, never its target.

def test_uninstall_reparse_attribute_guard(tmp_path,monkeypatch):
    import stat
    from pa2.uninstaller import no_links
    target=tmp_path/'link';target.mkdir();real=Path.lstat
    def altered(path,*args,**kwargs):
        value=real(path,*args,**kwargs)
        if path==target:return SimpleNamespace(st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,st_mode=value.st_mode)
        return value
    monkeypatch.setattr(Path,'lstat',altered)
    with pytest.raises(ValueError,match='정션'):no_links(target)

def test_uninstall_locked_file_preserves_ownership_for_retry(tmp_path,monkeypatch):
    from pa2.uninstaller import execute,build_plan,OWNED,MANIFEST
    install,data,_=removal_copy(tmp_path);plan=build_plan(install);real=Path.unlink
    def protected(path,*args,**kwargs):
        if path==data/'projects/p1/asset.step':raise PermissionError('locked fixture')
        return real(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',protected)
    assert not execute(install,plan['approval'])['ok']
    assert (install/MANIFEST).exists() and (data/OWNED).exists()
    assert build_plan(install)['files']

def test_automatic_promotion_gate_and_exact_pair_rollback(tmp_path,monkeypatch):
    """Positive activation fixture, not a claim of newly measured improvement."""
    import shutil
    from PySide6.QtWidgets import QApplication
    from pa2.learning.bootstrap import bootstrap
    from pa2.learning.registry import ModelRegistry
    from pa2.learning.idle import IdleLearningController
    from pa2.learning.pipeline import promotion_gate
    monkeypatch.setenv('PA2_INSTALL_ROOT',str(tmp_path/'install'))
    monkeypatch.delenv('PA2_DISABLE_BACKGROUND_LEARNING',raising=False)
    database=db(tmp_path);bootstrap(database);registry=ModelRegistry(database);before=registry.active_pair();after={}
    for role,bid in before.items():
        after[role]=str(uuid.uuid4());directory=registry.path('bundles/'+after[role]);shutil.copytree(registry.path('bundles/'+bid),directory)
        registry.register(after[role],directory)
    row=dict(id='gate-fixture',family='test',repeat=0,pair=.9,direction=.9,steps=5,verified=5,unresolved=0,unknown=0,timeouts=0,errors=0,seconds=10,calls=10,candidates=10)
    passed,detail=promotion_gate([row],[dict(row,seconds=8,calls=8)],AppSettings());assert passed
    assert not promotion_gate([row],[dict(row,steps=4,seconds=8,calls=8)],AppSettings())[0]
    settings=AppSettings();cycle=LearningCycle(id=str(uuid.uuid4()),status='READY',phase='fixture',snapshot_path='fixture',counts_json={},
        settings_json=asdict(settings),baseline_models_json=before,
        result_json={'approved_pair':after,'gates':{'both':{'passed':True,'models':after,'metrics':detail}}})
    with database.session() as session:session.add(cycle)
    app=QApplication.instance() or QApplication([]);controller=IdleLearningController(database,lambda:settings,lambda:False)
    controller.timer.stop();controller._signature=tuple(sorted(asdict(settings).items()))
    controller.last_input=time.monotonic()-settings.learning_idle_sec-1;controller.next_attempt=0;controller.tick()
    assert registry.active_pair()==after and controller.process is None
    with database.session() as session:assert session.get(LearningCycle,cycle.id).status=='APPLIED'
    assert registry.rollback()==before;controller.close()

def test_uninstall_approval_stable_across_hash_seeds(tmp_path):
    import subprocess,sys,os
    install,data,_=removal_copy(tmp_path)
    for name in ('cache/a/x','cache/b/x','learning/c/x','learning/d/x'):
        p=data/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'owned')
    script='import sys;sys.path[:0]='+repr(sys.path)+';from pa2.uninstaller import build_plan;print(build_plan('+repr(str(install))+')["approval"])'
    values=[subprocess.check_output([sys.executable,'-B','-c',script],env=dict(os.environ,PYTHONHASHSEED=seed)).strip() for seed in ('1','23','500')]
    assert len(set(values))==1
