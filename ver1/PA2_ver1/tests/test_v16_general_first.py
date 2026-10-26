from dataclasses import replace
from pa2.domain.models import ContactEdge, PartType, GeometryStatus
from pa2.planning.engine import Planner
from pa2.settings.config import AppSettings
from test_target_search import group, PASS
from test_two_stage import HintWorker


def test_shared_fastener_inserted_once_before_first_connected_part_without_second_search():
    groups=[group('base',0),group('a',10),group('b',20),group('bolt',30,PartType.BOLT),group('nut',31,PartType.NUT)]
    contacts=[ContactEdge('a','bolt',0),ContactEdge('b','bolt',0),ContactEdge('nut','bolt',0)]
    worker=HintWorker(lambda *_:(PASS,[]))
    result=Planner(replace(AppSettings(),support_enabled=False))._generate('p',1,'s',groups,contacts,{},'base',worker=worker)
    generals=[gid for gid in result.removal_order if gid in ('a','b')]
    assert set(result.removal_order[:2])=={'bolt','nut'}
    assert result.removal_order[2:]==generals
    assert len(worker.calls)==2
    assert all(not ids & {'bolt','nut'} for ids,_,_,_ in worker.calls)
    assert not result.metrics['virtual_candidate_records']
    assert result.metrics['draft_complete']
    assert len(set(result.removal_order))==4


def test_exception_fastener_precedes_exception():
    groups=[group('base',0),group('lv',10),group('bolt',12,PartType.BOLT)]
    result=Planner(replace(AppSettings(),support_enabled=False))._generate('p',1,'s',groups,[ContactEdge('lv','bolt',0)],{},'base',worker=HintWorker(lambda *_:(PASS,[])),collision_exception_ids=['lv'])
    assert result.removal_order==['bolt','lv']
    assert result.assembly_plan.steps[0].geometry_status==GeometryStatus.USER_COLLISION_EXCEPTION
