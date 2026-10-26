from pa2.cad.grouping import GroupingService
from pa2.cad.importer import CadScene
from pa2.domain.models import AtomicBody, Bounds


def body(identifier, volume, center):
    x, y, z = center
    return AtomicBody(identifier, "h", "assets/h/source.step", 0, f"/{identifier}", identifier, Bounds(x,y,z,x+1,y+1,z+1), volume, 6.0, center, True)


def scene(name, bodies):
    return CadScene(__import__("pathlib").Path(name), name, "assets/x/source.step", "mm", bodies, {})


def test_single_solid_definition_creates_repeated_occurrences():
    assembly = scene("assembly.step", [body("a", 10, (0,0,0)), body("b", 10, (20,0,0)), body("c", 30, (0,0,0))])
    part = scene("BLT-X.STP", [body("p", 10, (100,0,0))])
    result = GroupingService().resolve(assembly, [part])
    matched = [group for group in result.groups if group.part_definition_id]
    assert len(matched) == 2
    assert len({member for group in result.groups for member in group.body_ids}) == 3


def test_multi_solid_definition_preserves_rigid_relative_distance():
    assembly = scene("assembly.step", [body("a", 10, (0,0,0)), body("b", 20, (5,0,0)), body("noise", 20, (50,0,0))])
    part = scene("AIR-X.STP", [body("p1", 10, (100,0,0)), body("p2", 20, (105,0,0))])
    result = GroupingService(position_tolerance_mm=0.01).resolve(assembly, [part])
    grouped = next(group for group in result.groups if set(group.body_ids) == {"a","b"})
    assert grouped.display_name == "AIR-X"
    result.assert_partition(["a","b","noise"])


def test_managed_copy_keeps_original_part_name_and_classification():
    assembly=scene("source.step",[body("a",10,(0,0,0))])
    part=scene("source.step",[body("p",10,(100,0,0))])
    part.original_name="BLT-WASM520A.STP"
    result=GroupingService().resolve(assembly,[part])
    assert result.groups[0].part_type.value=="BOLT"
    assert result.groups[0].display_name=="BLT-WASM520A"


def test_unmatched_two_body_part_uses_unique_fallback():
    assembly = scene("assembly.step", [body("a", 10.007, (0,0,0)), body("b", 20, (5.00253,0,0))])
    part = scene("AIR-X.STP", [body("p1", 10, (100,0,0)), body("p2", 20, (105,0,0))])
    service = GroupingService(position_tolerance_mm=0.001)
    result = service.resolve(assembly, [part])
    assert len(result.groups) == 1
    assert set(result.groups[0].body_ids) == {"a", "b"}
    assert result.fallback_matches[0]["position_tolerance_mm"] == 0.005
    assert service.position_tolerance_mm == 0.001
    assert service.volume_relative_tolerance == 1e-4


def test_fallback_does_not_take_a_later_strict_match():
    assembly = scene("assembly.step", [body("a", 10.007, (0,0,0))])
    relaxed = scene("A.STP", [body("p", 10, (100,0,0))])
    strict = scene("Z.STP", [body("p", 10.007, (100,0,0))])
    result = GroupingService().resolve(assembly, [relaxed, strict])
    assert result.groups[0].display_name == "Z"
    assert not result.fallback_matches


def test_fallback_rejects_multiple_candidate_occurrences():
    assembly = scene("assembly.step", [body("a", 10.007, (0,0,0)), body("b", 10.007, (20,0,0))])
    part = scene("AIR-X.STP", [body("p", 10, (100,0,0))])
    result = GroupingService().resolve(assembly, [part])
    assert result.unresolved_body_ids == ["a", "b"]
    assert not result.fallback_matches
    assert result.ambiguous[0]["reason"] == "fallback-multiple-candidates"


def test_fallback_rejects_competing_definitions_without_order_bias():
    assembly = scene("assembly.step", [body("a", 10.007, (0,0,0))])
    parts = [scene("A.STP", [body("p", 10, (100,0,0))]), scene("B.STP", [body("p", 10.001, (100,0,0))])]
    for order in (parts, parts[::-1]):
        result = GroupingService().resolve(assembly, order)
        assert result.unresolved_body_ids == ["a"]
        assert not result.fallback_matches
        assert len(result.ambiguous) == 2


def test_fallback_rejects_overlap_with_an_ambiguous_definition():
    assembly = scene("assembly.step", [body("a", 10.007, (0,0,0)), body("b", 20.014, (5,0,0)),
                                       body("c", 20.014, (-5,0,0))])
    single = scene("S.STP", [body("p", 10, (100,0,0))])
    multi = scene("M.STP", [body("p1", 10, (100,0,0)), body("p2", 20, (105,0,0))])
    result = GroupingService().resolve(assembly, [single, multi])
    assert result.unresolved_body_ids == ["a", "b", "c"]
    assert not result.fallback_matches


def test_fallback_preserves_strict_occurrence_id_and_adds_new_id():
    assembly = scene("assembly.step", [body("a", 10, (0,0,0)), body("b", 10.007, (20,0,0))])
    part = scene("AIR-X.STP", [body("p", 10, (100,0,0))])
    result = GroupingService().resolve(assembly, [part])
    assert len({g.id for g in result.groups}) == 2
    assert result.groups[0].body_ids == ["a"]
    assert result.groups[0].display_name == "AIR-X"
    assert result.groups[1].display_name == "AIR-X #2"
    assert len(result.fallback_matches) == 1


def test_fallback_limits_do_not_allow_large_geometry_or_spacing_changes():
    part = scene("AIR-X.STP", [body("p1", 10, (100,0,0)), body("p2", 20, (105,0,0))])
    for volume, distance in [(10.02, 5), (10.007, 5.006)]:
        assembly = scene("assembly.step", [body("a", volume, (0,0,0)), body("b", 20, (distance,0,0))])
        result = GroupingService(position_tolerance_mm=0.001).resolve(assembly, [part])
        assert result.unresolved_body_ids == ["a", "b"]

