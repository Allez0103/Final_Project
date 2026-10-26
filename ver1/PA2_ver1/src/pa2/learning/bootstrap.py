"""Install the evaluated frozen pair once; keep external labels distinguishable."""
import json,shutil,hashlib
from pathlib import Path
from pa2.runtime import resource_root,install_root
from pa2.storage.database import LearningProgress,utcnow
from .registry import ModelRegistry
from .data import recorded_snapshot,atomic_json

def pilot_root():return resource_root()/'assets/pilot'
def pilot_manifest():
    path=pilot_root()/'pilot.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

def external_cases():
    manifest=pilot_manifest()
    if not manifest:return [],[]
    def load(split):
        result=[]
        for name in manifest[split]:
            path=pilot_root()/'cases'/split/(name+'.json')
            relative=path.relative_to(pilot_root()).as_posix()
            if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['files'][relative]:
                raise ValueError('번들 학습 라벨 체크섬 오류: '+name)
            row=json.loads(path.read_text(encoding='utf-8'))
            row.update(external=True,contact_ready=True,contact_graph=manifest['contact_graph'])
            row['external_geometry']=str(pilot_root()/'scenes'/name)
            result.append(row)
        return result
    return load('train'),load('evaluation')

def current_progress(snapshot):
    return {key:snapshot.get(key,[]) for key in ('project_ids','families','state_ids')}

def bootstrap(database):
    from .models import PreferenceModel
    from pa2.run_log import safe_log
    manifest=pilot_manifest()
    if not manifest:return {'status':'NO_BUNDLED_MODELS'}
    registry=ModelRegistry(database)
    with database.session() as session:
        if session.get(LearningProgress,'seed-v28'):return {'status':'ALREADY_INITIALIZED'}
    pair=manifest['pair']
    # Validate all bundles before registering or activating either one.
    for role,bid in pair.items():PreferenceModel(pilot_root()/'models'/bid,role)
    for role,bid in pair.items():
        destination=registry.path('bundles/'+bid)
        if not destination.exists():shutil.copytree(pilot_root()/'models'/bid,destination)
        registry.register(bid,destination)
    active=registry.active_pair()
    with database.session() as session:
        registry._transaction_lock(session)
        if session.get(LearningProgress,'seed-v28'):return {'status':'ALREADY_INITIALIZED'}
        if not any(registry._pair(session).values()):
            registry._set_pair(session,active,pair,'사용자 승인: HVJB 보류 평가·test2 검증 모델 초기 적용')
        session.add(LearningProgress(key='seed-v28',baseline_json={'pair':pair,'pilot':True}))
    snapshot=recorded_snapshot(database)
    with database.session() as session:
        if not session.get(LearningProgress,'common'):
            session.add(LearningProgress(key='common',baseline_json=current_progress(snapshot)))
    safe_log(registry,'event','model_bootstrap',{'pair':registry.active_pair(),'pilot':True})
    return {'status':'INITIALIZED','pair':registry.active_pair()}

def expanded_snapshot(database):
    snapshot=recorded_snapshot(database)
    train,test=external_cases()
    if not train and not test:return snapshot
    excluded_hashes={c['payload']['assembly_asset_hash'] for c in test}
    excluded_families=set((pilot_manifest() or {}).get('evaluation_family_fingerprints',[]))
    local=[c for c in snapshot['cases'] if c['payload']['assembly_asset_hash'] not in excluded_hashes
           and c['family'] not in excluded_families]
    snapshot['project_ids']=sorted({c['project_id'] for c in local})
    snapshot['cases']=local+train+test
    snapshot['families']=sorted({c['family'] for c in snapshot['cases']})
    # Permanent E01--E05 are never used for fitting; local unseen families also
    # get held out so cross-product regressions can prevent global activation.
    local_families=sorted({c['family'] for c in local})
    snapshot['heldout_families']=sorted({c['family'] for c in test}|set(local_families[::5]))
    snapshot['counts'].update(projects=len(snapshot['project_ids']),families=len(snapshot['families']))
    snapshot['external_training_cases']=len(train);snapshot['fixed_evaluation_cases']=len(test)
    return snapshot
