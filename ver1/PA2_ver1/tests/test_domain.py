import pytest

from pa2.domain.models import GeometryStatus, Plan, PlanningStatus, PlanStep, normalize


def step(group_id="moving"):
    return PlanStep(group_id, 1, (0, 0, 2), (0, 0, -4), 10.0)


def test_normalize_and_inverse_contract():
    item = step(); item.validate()
    assert item.removal_direction == (0, 0, 1)
    assert item.assembly_direction == (0, 0, -1)
    assert item.disassembly_end_transform[11] == 10


def test_plan_requires_each_non_base_group_exactly_once():
    plan = Plan("p", "project", 1, "base", ["base", "moving"], [step()], PlanningStatus.COMPLETE)
    plan.validate()
    plan.steps.append(step())
    with pytest.raises(ValueError, match="두 번"):
        plan.validate()


def test_direction_rejects_zero_and_non_inverse():
    with pytest.raises(ValueError): normalize((0, 0, 0))
    item = step(); item.assembly_direction = (1, 0, 0)
    with pytest.raises(ValueError, match="역방향"):
        item.validate()

