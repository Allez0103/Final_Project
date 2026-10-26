from dataclasses import replace
import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt
from pa2.domain.models import ContactEdge, GeometryStatus, GeometryDecision
from pa2.planning.engine import Planner
from pa2.settings.config import AppSettings
from pa2.cad.native_worker import CadDispatcher
from pa2.cad.brep_io import write_shape
from test_target_search import group, Worker, PASS, BLOCKED, PartType


class HintWorker(Worker):
    def call(self, operation, payload, **kwargs):
        if operation=='direction_policy':
            return {'method':'axis','axis':(0,0,1)} if payload['fastener'] else {'method':'exposure'}
        return super().call(operation,payload,**kwargs)


def run(groups,rule,contacts=(),**kwargs):
    worker=HintWorker(rule)
    result=Planner(replace(AppSettings(),support_enabled=False,backtrack_depth=100))._generate(
        'p',1,'s',[group('base',0),*groups],list(contacts),{},'base',worker=worker,**kwargs)
    return result,worker


def test_all_fasteners_omitted_in_single_search_then_contact_insertion():
    def rule(gid,ids):
        return (BLOCKED,['bolt']) if gid=='target' and 'bolt' in ids else (PASS,[])
    r,w=run([group('target',10),group('bolt',20,PartType.BOLT)],rule,contacts=[ContactEdge('target','bolt',0)])
    assert r.metrics['skeleton_order']==['target']
    assert r.removal_order==['bolt','target']
    virtual=r.metrics['virtual_paths']
    assert not virtual
    assert len(w.calls)==1
    assert all('bolt' not in ids for ids,gid,_,_ in w.calls if gid=='target' and len(ids)==2)
    assert [s.group_id for s in r.assembly_plan.steps]==['target','bolt']


def test_fastener_path_is_skipped_even_if_old_checker_would_block_it():
    from pa2.planning.two_stage import TwoStagePriorityProvider
    class TargetFirst(TwoStagePriorityProvider):
        def rank(self,*args):
            return sorted(super().rank(*args),key=lambda gid:gid!='target')
    def rule(gid,ids):
        if gid=='target' and 'bolt' in ids:return BLOCKED,['bolt']
        if gid=='bolt' and 'cover' in ids:return BLOCKED,['cover']
        return PASS,[]
    r,w=run([group('target',10),group('cover',20),group('bolt',30,PartType.BOLT)],rule,
            priority_provider=TargetFirst(),contacts=[ContactEdge('target','bolt',0)])
    assert r.metrics['skeleton_order']==['target','cover']
    assert r.removal_order==['bolt','target','cover']
    assert all(gid!='bolt' for _,gid,_,_ in w.calls)
    assigned=next(p for p in r.path_results if p.group_id=='bolt')
    assert assigned.decision==GeometryDecision.NOT_TESTED
    assert assigned.evidence['target_group_id']=='target'


def test_bundle_removes_all_related_fasteners_before_target_retry():
    from pa2.cad.path_check import state_key
    groups=[group('base',0),group('target',10),group('a',20,PartType.BOLT),group('b',30,PartType.NUT)]
    def rule(gid,ids):
        return (BLOCKED,sorted({'a','b'} & ids)) if gid=='target' and {'a','b'} & ids else (PASS,[])
    worker=HintWorker(rule)
    r=Planner(replace(AppSettings(),support_enabled=False,backtrack_depth=100))._generate(
        'p',1,'s',groups,[ContactEdge('target','a',0),ContactEdge('target','b',0)],{},'base',worker=worker)
    assert r.removal_order[-1]=='target'
    assert set(r.removal_order[:-1])=={'a','b'}
    assert not any(gid=='target' and len(ids & {'a','b'})==1 for ids,gid,_,_ in worker.calls)


def test_exception_has_no_cad_path_call_and_is_first_even_invalid():
    r,w=run([replace(group('lv',5),geometry_valid=False),group('target',10)],
            lambda gid,ids:(BLOCKED,['lv']) if 'lv' in ids else (PASS,[]),collision_exception_ids=['lv'])
    assert r.removal_order==['lv','target']
    assert all(gid!='lv' and 'lv' not in ids for ids,gid,_,_ in w.calls)
    assert r.path_results[0].decision==GeometryDecision.NOT_TESTED
    assert r.assembly_plan.steps[-1].geometry_status==GeometryStatus.USER_COLLISION_EXCEPTION
    assert r.status.value=='REVIEW_REQUIRED'
    assert r.metrics['collision_exception_steps']==1


def test_exception_cannot_be_base_or_foreign():
    for ids in (['base'],['foreign']):
        with pytest.raises(ValueError):run([group('lv',5)],lambda *_:(PASS,[]),collision_exception_ids=ids)


def test_fastener_axis_is_assigned_without_path_calls():
    r,w=run([group('bolt',20,PartType.BOLT)],lambda *_:(PASS,[]))
    assert not w.calls
    assert abs(r.assembly_plan.steps[0].removal_direction[2])==1
    assert r.assembly_plan.steps[0].geometry_status==GeometryStatus.FASTENER_ASSIGNED
    assert r.metrics['tested_candidates']==0
    assert not r.metrics['path_complete']


def test_preset_and_exception_survive_reopen_edit_and_confirmation(tmp_path):
    from pa2.storage.database import Database
    from pa2.storage.layout import DataLayout
    from pa2.application.project_service import ProjectService
    from pa2.application.plan_service import PlanService
    db=Database(DataLayout(tmp_path/'data')); db.initialize()
    project=ProjectService(db).create('test','KD1','HVJB'); service=PlanService(db)
    service.save_preset(project.id,'s','base',['lv'])
    assert service.load_preset(project.id,'s')['exception_ids']==['lv']
    assert service.load_preset(project.id,'new-snapshot') is None
    r,_=run([group('lv',5),group('target',10)],lambda *_:(PASS,[]),collision_exception_ids=['lv'])
    plan=r.assembly_plan; plan.project_id=project.id; plan.user_modified=True
    service.confirm(plan)
    loaded=service.load_current_draft(project.id)
    assert loaded.steps[-1].geometry_status==GeometryStatus.USER_COLLISION_EXCEPTION
    assert loaded.steps[-1].caution_text==''
    assert loaded.steps[-1].material_text=='lv'


def test_blocked_general_is_in_full_editable_draft_without_fake_pass():
    r,_=run([group('blocked',10),group('free',20)],
        lambda gid,ids:(BLOCKED,['base']) if gid=='blocked' else (PASS,[]))
    assert set(r.removal_order)=={'blocked','free'}
    r.assembly_plan.validate()
    step=next(s for s in r.assembly_plan.steps if s.group_id=='blocked')
    assert step.geometry_status==GeometryStatus.DRAFT_UNRESOLVED
    assert step.caution_text==''
    assert r.metrics['unresolved_general_ids']==['blocked']
    assert r.metrics['verified_path_steps']==1
    assert r.metrics['draft_complete'] and not r.metrics['path_complete']
    assert not any(p.group_id=='blocked' and p.decision==GeometryDecision.PASS for p in r.path_results)


def test_dead_end_backtracks_before_draft_completion():
    def rule(gid,ids):
        return (GeometryDecision.UNKNOWN,[]) if gid=='b' and 'a' not in ids else (PASS,[])
    from pa2.planning.two_stage import TwoStagePriorityProvider
    class AFirst(TwoStagePriorityProvider):
        def rank(self,*args):return sorted(super().rank(*args),key=lambda x:x!='a')
    r,_=run([group('a',10),group('b',20)],rule,priority_provider=AFirst())
    assert r.removal_order==['b','a']
    assert not r.metrics['unresolved_general_ids']
    assert r.metrics['backtracks']>0


def test_virtual_base_collision_reused_when_unrelated_exit_length_changes():
    from test_target_search import Worker
    class TargetFirst:
        name='projection-cache-regression'
        def rank(self,groups,remaining,base,contacts):
            return [g for g in ('target','far') if g in remaining]
    worker=Worker(lambda gid,ids:(BLOCKED,['base']) if gid=='target' else (PASS,[]),directions=((-1,0,0),))
    r=Planner(replace(AppSettings(),support_enabled=False,backtrack_depth=100))._generate(
        'p',1,'s',[group('base',0),group('target',10),group('far',-100)],[],{},'base',
        priority_provider=TargetFirst(),worker=worker)
    calls=[q for q in worker.calls if q[1]=='target']
    assert len(calls)==1
    witnesses=[q for q in r.path_results if q.evidence.get('witness_full_exit_projection_proof')]
    assert witnesses and any(q.travel_mm<q.evidence['witness_source_travel_mm'] for q in witnesses)


def test_blocked_general_is_not_rechecked_in_a_second_fastener_search():
    r,w=run([group('blocked',10)],lambda *_:(BLOCKED,['base']))
    assert r.metrics['virtual_native_path_calls']==0
    assert r.metrics['actual_native_path_calls']==6
    assert len(w.calls)==6
    assert r.metrics['unresolved_general_ids']==['blocked']


def test_single_search_uses_full_budget_then_completes_editable_draft():
    import time
    def unresolved(*_):
        time.sleep(.1)
        return GeometryDecision.UNKNOWN,[]
    worker=HintWorker(unresolved)
    r=Planner(replace(AppSettings(),support_enabled=False,generation_timeout_sec=1))._generate(
        'p',1,'s',[group('base',0),group('a',10),group('b',20),group('c',30)],[],{},'base',worker=worker)
    assert r.metrics['skeleton_budget_exhausted']
    assert r.metrics['actual_native_path_calls']>0
    assert r.metrics['virtual_native_path_calls']==0
    assert r.metrics['draft_complete']


def test_contact_normal_and_overlap_fallback_from_real_geometry(tmp_path):
    files={}
    for gid,z in [('base',0),('top',1),('overlap',.5)]:
        path=tmp_path/f'{gid}.binbrep'
        write_shape(BRepPrimAPI_MakeBox(gp_Pnt(0,0,z),2,2,1).Shape(),path)
        files[gid]=str(path)
    worker=CadDispatcher(files,lambda _:None)
    q=worker.execute('direction_policy',{'gid':'top','neighbors':['base'],'epsilon':.001,'gap':.05})
    assert q['method']=='largest_planar_contact' and q['normal']==(0.,0.,1.)
    assert q['area_mm2']==pytest.approx(4.)
    q=worker.execute('direction_policy',{'gid':'overlap','neighbors':['base'],'epsilon':.001,'gap':.05})
    assert q['method']=='exposure_initial_overlap'
