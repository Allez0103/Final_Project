"""Recognition tests only: do not call contacts, collision/path checks or ML."""
from pathlib import Path
import math

import pytest
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

from pa2.cad.grouping import GroupingService
from pa2.cad.importer import CadScene, _bounds, _properties
from pa2.cad.rotation_signature import equivalent, signature
from pa2.domain.models import AtomicBody


def placed(shape, angle, offset):
    rotation=gp_Trsf();rotation.SetRotation(gp_Ax1(gp_Pnt(0,0,0),gp_Dir(0,0,1)),math.radians(angle))
    translation=gp_Trsf();translation.SetTranslation(gp_Vec(*offset))
    translation.Multiply(rotation)
    return BRepBuilderAPI_Transform(shape,translation,True).Shape()


def scene(name, shapes):
    bodies=[]
    for i,(bid,shape) in enumerate(shapes.items()):
        volume,area,center=_properties(shape)
        bodies.append(AtomicBody(bid,name,'diagnostic/'+name,i,'/'+bid,bid,_bounds(shape),volume,area,center,True))
    return CadScene(Path(name),name,'diagnostic/'+name,'mm',bodies,shapes)


@pytest.mark.parametrize('angle',[30,150,330])
def test_signature_is_rigid_motion_invariant_without_mutating_shape(angle):
    original=BRepPrimAPI_MakeBox(52,58,30).Shape()
    before=_bounds(original)
    target=placed(original,angle,(170,-250,900))
    assert sorted(before.size)!=pytest.approx(sorted(_bounds(target).size))
    assert equivalent(signature(original),signature(target),1e-4)
    assert _bounds(original)==before


def test_multiple_rotated_instances_of_one_definition_are_not_ambiguous():
    shape=BRepPrimAPI_MakeBox(52,58,30).Shape()
    source=scene('BLK-EXAMPLE.step',{'source':shape})
    assembly=scene('assembly.step',{'a':placed(shape,30,(100,200,0)),
        'b':placed(shape,150,(-300,500,0))})
    result=GroupingService().resolve(assembly,[source])
    assert not result.unresolved_body_ids and not result.ambiguous
    assert len(result.rotation_matches)==2 and len({g.id for g in result.groups})==2
    assert all(g.part_type.value=='BLOCK' for g in result.groups)


def test_competing_rotation_definitions_stay_unmatched_regardless_of_order():
    shape=BRepPrimAPI_MakeBox(52,58,30).Shape()
    a=scene('A.step',{'pa':shape});b=scene('B.step',{'pb':shape})
    assembly=scene('assembly.step',{'target':placed(shape,30,(100,200,0))})
    for sources in ([a,b],[b,a]):
        result=GroupingService().resolve(assembly,sources)
        assert result.unresolved_body_ids==['target'] and not result.rotation_matches
        assert len(result.ambiguous)==2
        assert all(r['reason']=='rotation-competing-definitions' for r in result.ambiguous)


def test_rotation_retry_never_takes_an_already_strictly_matched_body():
    shape=BRepPrimAPI_MakeBox(52,58,30).Shape()
    target=placed(shape,30,(100,200,0))
    strict=scene('Z.step',{'strict':target});other=scene('A.step',{'rotated':shape})
    result=GroupingService().resolve(scene('assembly.step',{'target':target}),[other,strict])
    assert result.groups[0].display_name=='Z' and not result.rotation_matches


def test_exact_native_definition_name_can_resolve_a_geometry_qualified_tie(monkeypatch):
    import pa2.cad.step_name_hints as metadata
    shape=BRepPrimAPI_MakeBox(52,58,30).Shape()
    sources=[scene('A.step',{'pa':shape}),scene('B.step',{'pb':shape})]
    target=scene('assembly.step',{'target':placed(shape,30,(100,200,0))})
    monkeypatch.setattr(metadata,'definition_hints',lambda *_:{'target':{'B'}})
    result=GroupingService().resolve(target,sources)
    assert not result.unresolved_body_ids and not result.ambiguous
    assert result.groups[0].display_name=='B'
    assert result.rotation_matches[0]['native_step_name_tie_break']
    monkeypatch.setattr(metadata,'definition_hints',lambda *_:{'target':{'A','B'}})
    assert GroupingService().resolve(target,sources).unresolved_body_ids==['target']


def test_native_name_never_replaces_missing_shape_evidence(monkeypatch):
    import pa2.cad.step_name_hints as metadata
    shape=BRepPrimAPI_MakeBox(52,58,30).Shape()
    def forbidden(*_):raise AssertionError('No geometry-qualified tie')
    monkeypatch.setattr(metadata,'definition_hints',forbidden)
    target=scene('assembly.step',{'target':placed(BRepPrimAPI_MakeBox(40,20,10).Shape(),30,(100,200,0))})
    assert GroupingService().resolve(target,[scene('A.step',{'p':shape})]).unresolved_body_ids==['target']


def test_multibody_rotation_preserves_rigid_centroid_distances():
    a=BRepPrimAPI_MakeBox(7,11,3).Shape()
    b=placed(BRepPrimAPI_MakeBox(5,8,4).Shape(),0,(30,0,0))
    source=scene('AIR-MODULE.step',{'pa':a,'pb':b})
    assembly=scene('assembly.step',{'a':placed(a,30,(100,200,0)),
        'b':placed(b,30,(100,200,0))})
    result=GroupingService(position_tolerance_mm=.001).resolve(assembly,[source])
    assert len(result.groups)==1 and not result.unresolved_body_ids
    assert len(result.rotation_matches)==1 and set(result.groups[0].body_ids)=={'a','b'}
    wrong=scene('assembly.step',{'a':assembly.shapes['a'],'b':placed(b,30,(100.1,200,0))})
    assert GroupingService(position_tolerance_mm=.001).resolve(wrong,[source]).unresolved_body_ids==['a','b']


def test_signature_failure_is_not_a_guess(monkeypatch):
    import pa2.cad.rotation_signature as module
    shape=BRepPrimAPI_MakeBox(52,58,30).Shape()
    def fail(_):raise RuntimeError('feature unavailable')
    monkeypatch.setattr(module,'signature',fail)
    result=GroupingService().resolve(scene('assembly.step',{'a':placed(shape,30,(100,200,0))}),
                                    [scene('part.step',{'p':shape})])
    assert result.unresolved_body_ids==['a'] and not result.rotation_matches


def test_different_inertia_cannot_match_on_volume_and_area_only(monkeypatch):
    import pa2.cad.rotation_signature as module
    shape=BRepPrimAPI_MakeBox(52,58,30).Shape()
    source=scene('part.step',{'p':shape})
    target=scene('assembly.step',{'a':placed(shape,30,(100,200,0))})
    first=module.RotationSignature((1,2,3),(('plane',4),),(('line',5),))
    second=module.RotationSignature((1,2,4),(('plane',4),),(('line',5),))
    values=iter((first,second));monkeypatch.setattr(module,'signature',lambda _:next(values))
    result=GroupingService().resolve(target,[source])
    assert result.unresolved_body_ids==['a']
