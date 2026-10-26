"""Unmatched-only overflow retry; no weaker collision or matching tolerance."""
from dataclasses import replace
import pytest
from pa2.cad.grouping import GroupingService, PartDefinitionData
from pa2.domain.models import PartType
from test_grouping import body, scene


def fixture(copies=1):
    positions=[(0,0,0),(1,0,0),(3,0,0),(0,5,0),(0,0,7),
               (11,0,0),(0,13,0),(0,0,17),(19,5,0)]
    volumes=[1000]+[10]*4+[20]*4
    part=scene('PLT-X.STP',[body(f'p{i}',v,(x+100,y,z)) for i,((x,y,z),v) in enumerate(zip(positions,volumes))])
    assembly=scene('assembly.step',[body(f't{c}-{i}',v,(x+c*1000,y,z))
        for c in range(copies) for i,((x,y,z),v) in enumerate(zip(positions,volumes))])
    return assembly,part


def test_anchor_retry_overflow_preserves_features_and_groups_unique_body_set():
    assembly,part=fixture();service=GroupingService()
    definition=PartDefinitionData('d','h','PLT-X.STP',PartType.PLATE,part.bodies)
    assert service._find_matches(definition,assembly.bodies)==[]  # Existing 65,536 > 50,000 guard.
    result=service.resolve(assembly,[part])
    assert len(result.groups)==1 and not result.unresolved_body_ids
    assert set(result.groups[0].body_ids)=={b.id for b in assembly.bodies}
    assert result.groups[0].part_type==PartType.PLATE
    record=result.anchor_matches[0]
    assert record['raw_combinations']==65536 and record['attempted_nodes']<100
    assert record['search_complete'] and record['distinct_body_sets']==1
    assert record['relative_tolerance']==1e-4 and record['position_tolerance_mm']==.05


def test_anchor_retry_keeps_existing_strict_group_and_id():
    assembly,part=fixture();assembly.bodies.append(body('known',5000,(200,0,0)))
    known=scene('Z.STP',[body('single',5000,(0,0,0))])
    original=GroupingService().resolve(scene('assembly.step',[assembly.bodies[-1]]),[known]).groups[0]
    result=GroupingService().resolve(assembly,[part,known])
    assert next(g for g in result.groups if g.body_ids==['known'])==original
    assert len(result.anchor_matches)==1


def test_anchor_retry_never_takes_a_body_already_claimed_by_legacy_stage():
    assembly,part=fixture();known=scene('Z.STP',[body('single',10,(0,0,0))])
    result=GroupingService().resolve(assembly,[part,known])
    assert sum(g.display_name.startswith('Z') for g in result.groups)==4
    assert not result.anchor_matches and len(result.unresolved_body_ids)==5


def test_anchor_retry_rejects_competing_definitions_regardless_of_order():
    assembly,part=fixture();other=replace(part,source_hash='different',original_name='PLT-Y.STP')
    for parts in ([part,other],[other,part]):
        result=GroupingService().resolve(assembly,parts)
        assert len(result.unresolved_body_ids)==9 and not result.anchor_matches
        assert sum(x['reason']=='anchor-competing-definitions' for x in result.ambiguous)==2


def test_anchor_retry_preserves_old_ambiguous_relaxed_claims():
    assembly,part=fixture();other=scene('NUT-OTHER.STP',[body('p',10.007,(0,0,0))])
    result=GroupingService().resolve(assembly,[part,other])
    assert not result.anchor_matches and len(result.unresolved_body_ids)==9
    assert any(x['reason']=='anchor-competing-definitions' for x in result.ambiguous)


def test_anchor_retry_rejects_multiple_disjoint_occurrences():
    assembly,part=fixture(copies=2)
    result=GroupingService().resolve(assembly,[part])
    assert not result.anchor_matches and len(result.unresolved_body_ids)==18
    assert any(x['reason']=='anchor-multiple-body-sets' and x['ambiguity_proven'] for x in result.ambiguous)


@pytest.mark.parametrize('nodes,seconds',[(1,2.),(50000,0.),(22,2.)])
def test_anchor_retry_never_accepts_partial_search_even_after_one_solution(nodes,seconds):
    assembly,part=fixture();service=GroupingService()
    service.ANCHOR_RETRY_NODE_LIMIT=nodes;service.ANCHOR_RETRY_SECONDS=seconds
    result=service.resolve(assembly,[part])
    assert not result.anchor_matches and len(result.unresolved_body_ids)==9
    info=next(x for x in result.ambiguous if x['reason']=='anchor-search-budget')
    assert not info['search_complete']
    if nodes==22:assert info['distinct_body_sets']==1


def test_anchor_retry_does_not_relax_spacing_tolerance():
    assembly,part=fixture();assembly.bodies[-1]=body('t0-8',20,(19.2,5,0))
    result=GroupingService().resolve(assembly,[part])
    assert not result.anchor_matches and len(result.unresolved_body_ids)==9


def test_anchor_retry_deduplicates_identical_definition_inputs():
    assembly,part=fixture();result=GroupingService().resolve(assembly,[part,part])
    assert len(result.groups)==1 and len(result.anchor_matches)==1


def test_anchor_retry_uses_only_existing_fallback_tolerances_after_strict_fails():
    assembly,part=fixture();assembly.bodies[0]=replace(assembly.bodies[0],centroid=(.002,0,0))
    result=GroupingService(position_tolerance_mm=.001).resolve(assembly,[part])
    assert len(result.groups)==1 and len(result.anchor_matches)==1
    info=result.anchor_matches[0]
    assert info['tolerance_profile']=='existing-unmatched-fallback'
    assert info['relative_tolerance']==.001 and info['position_tolerance_mm']==.005
    assert info['previous_profile_attempts'][0]['distinct_body_sets']==0
    assembly.bodies[0]=replace(assembly.bodies[0],centroid=(.006,0,0))
    assert not GroupingService(position_tolerance_mm=.001).resolve(assembly,[part]).anchor_matches
