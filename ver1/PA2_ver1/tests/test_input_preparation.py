from types import SimpleNamespace
import importlib

import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from pa2.domain.models import Bounds

module=importlib.import_module('pa2.cad.prepare')


def test_valid_input_is_not_copied_or_repaired():
    shape=BRepPrimAPI_MakeBox(1,1,1).Shape()
    result,evidence,valid=module.prepare(shape,.001,lambda _:None)
    assert result is shape and evidence is None and valid


@pytest.mark.parametrize('change,accepted',[
    ({},True),
    ({'tolerance':.004974,'volume':1.00000142},True),
    ({'tolerance':.0101},False),
    ({'volume':1.00002},False),
    ({'box':Bounds(.002,0,0,1,1,1)},False),
    ({'counts':[2,2,3]},False),
    ({'valid':False},False),
])
def test_repair_is_accepted_only_inside_all_limits(monkeypatch,change,accepted):
    original=object();copy=object();events=[]
    box=Bounds(0,0,0,1,1,1)
    monkeypatch.setattr(module,'BRepCheck_Analyzer',lambda s,geometry:SimpleNamespace(
        IsValid=lambda:not geometry or (s is copy and change.get('valid',True))))
    monkeypatch.setattr(module,'BRepBuilderAPI_Copy',lambda *args:SimpleNamespace(Shape=lambda:copy))
    monkeypatch.setattr(module,'BRepLib',SimpleNamespace(SameParameter_s=lambda s,*args:events.append(s)))
    monkeypatch.setattr(module,'_properties',lambda s:(1,.0008,box,[1,2,3]) if s is original else
        (change.get('volume',1.000000001),change.get('tolerance',.0009),change.get('box',box),change.get('counts',[1,2,3])))
    result,evidence,valid=module.prepare(original,.001,events.append)
    assert valid is accepted and evidence['accepted'] is accepted
    assert result is (copy if accepted else original)
    assert copy in events and original not in events
    assert evidence['repair_max_tolerance_mm']==.01
    assert evidence['repair_max_relative_volume_change']==1e-5
    assert evidence['epsilon_mm']==.001


def test_topologically_invalid_input_is_not_repaired(monkeypatch):
    original=object()
    monkeypatch.setattr(module,'BRepCheck_Analyzer',lambda *args:SimpleNamespace(IsValid=lambda:False))
    monkeypatch.setattr(module,'BRepBuilderAPI_Copy',lambda *args:pytest.fail('must not repair invalid topology'))
    result,evidence,valid=module.prepare(original,.001,lambda _:None)
    assert result is original and not valid and not evidence['accepted']


def test_repair_cancellation_propagates(monkeypatch):
    monkeypatch.setattr(module,'BRepCheck_Analyzer',lambda s,geometry:SimpleNamespace(IsValid=lambda:not geometry))
    monkeypatch.setattr(module,'_properties',lambda s:(1,0,Bounds(0,0,0,1,1,1),[1]))
    monkeypatch.setattr(module,'BRepBuilderAPI_Copy',lambda *args:SimpleNamespace(Shape=lambda:object()))
    def activity(stage):
        if stage=='BREP_PARAMETER_REPAIR':raise InterruptedError()
    with pytest.raises(InterruptedError):module.prepare(object(),.001,activity)


def test_repaired_path_forces_review_and_preserves_evidence():
    from dataclasses import replace
    from pa2.domain.models import AssemblyGroup,PartType,PathCheckResult,GeometryDecision,GeometryStatus
    from pa2.planning.engine import Planner
    from pa2.settings.config import AppSettings
    groups=[AssemblyGroup(name,name,[name],PartType.UNKNOWN,Bounds(x,0,0,x+1,1,1),1,None,True)
            for name,x in [('base',-2),('moving',0)]]
    class Worker:
        def call(self,operation,payload,**kwargs):
            if operation=='direction_policy':return {'method':'exposure'}
            if operation=='directions':return [(1,0,0)]
            assert operation=='path'
            return PathCheckResult('moving','state',(1,0,0),3,GeometryDecision.PASS,'CERTIFIED_CLEAR',[],0,
                evidence={'input_repairs':[{'group_id':'moving','accepted':True,'code':'INPUT_PARAMETER_REPAIRED'}]})
    result=Planner(replace(AppSettings(),support_enabled=False))._generate(
        'p',1,'s',groups,[],{},'base',worker=Worker())
    assert result.status.value=='REVIEW_REQUIRED'
    assert result.metrics['path_complete'] and result.metrics['input_repaired_steps']==1
    assert result.metrics['input_repaired_groups']==['moving']
    step=result.assembly_plan.steps[0]
    assert step.geometry_status==GeometryStatus.GEOMETRY_REPAIRED
    assert step.caution_text==''
