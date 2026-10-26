from dataclasses import replace

import pytest

from pa2.domain.models import Bounds, ContactEdge, PartType, Plan, PlanStep, PlanningStatus
from pa2.planning.engine import Planner
from pa2.planning.priority import ExteriorPriorityProvider
from pa2.settings.config import AppSettings
from test_target_search import group, Worker, PASS, BLOCKED, UNKNOWN


def run(rule, directions=((0, 0, 1),), contacts=None):
    groups = [group('base', 0), group('target', 10), group('a', 20, PartType.BOLT), group('b', 30, PartType.NUT)]
    worker = Worker(rule, directions)
    settings = replace(AppSettings(), support_enabled=False, backtrack_depth=100, backtrack_count=1000)
    result = Planner(settings)._generate('p', 1, 's', groups,
        contacts if contacts is not None else [ContactEdge('target', 'a', 0), ContactEdge('target', 'b', 0)],
        {}, 'base', worker=worker,priority_provider=ExteriorPriorityProvider())
    return result, worker


def test_virtual_success_requires_actual_fasteners_and_target_recheck():
    result, worker = run(lambda gid, ids: (BLOCKED, [x for x in ('a', 'b') if x in ids])
                         if gid == 'target' and {'a', 'b'} & ids else (PASS, []))
    assert result.removal_order[-1] == 'target'
    assert set(result.removal_order[:-1]) == {'a', 'b'}
    assert result.metrics['virtual_target_passes'] > 0
    assert result.metrics['virtual_paths'][0]['evidence']['virtual_probe']
    assert all(not r.evidence['virtual_probe'] for r in result.path_results)
    # Virtual target PASS is not sufficient: an actual full-state path exists.
    assert any(r.group_id == 'target' and r.decision == PASS for r in result.path_results)


def test_virtual_pass_cannot_teleport_a_blocked_bolt():
    def rule(gid, ids):
        if gid == 'a': return BLOCKED, ['base']
        if gid == 'target' and 'a' in ids: return BLOCKED, ['a']
        return PASS, []
    result, _ = run(rule)
    assert 'a' not in result.removal_order and 'target' not in result.removal_order
    assert 'b' in result.removal_order


def test_virtual_unknown_is_not_a_passing_hint():
    result, _ = run(lambda gid, ids: (UNKNOWN, []) if gid == 'target' else (BLOCKED, ['base']))
    assert not result.removal_order
    assert result.metrics['virtual_target_passes'] == 0


def test_deferred_direction_remains_eligible():
    class DirectionWorker(Worker):
        def call(self, operation, payload, **kwargs):
            if operation == 'path':
                self.rule = lambda gid, ids: (PASS, []) if payload['direction'] == (0, 0, -1) else (BLOCKED, ['base'])
            return super().call(operation, payload, **kwargs)
    groups = [group('base', 0), group('target', 10)]
    # First two equal-exposure directions fail; third must still be tested.
    worker = DirectionWorker(None, ((0, 0, 1), (0, 1, 0), (0, 0, -1)))
    result = Planner(replace(AppSettings(), support_enabled=False))._generate(
        'p', 1, 's', groups, [], {}, 'base', worker=worker,priority_provider=ExteriorPriorityProvider())
    assert result.removal_order == ['target']


def test_free_orphan_fastener_precedes_deferred_full_target_sweep():
    class DirectionWorker(Worker):
        def call(self, operation, payload, **kwargs):
            if operation == 'path':
                self.rule = lambda gid, ids: (PASS, []) if gid == 'bolt' or payload['direction'] == (0,0,-1) else (BLOCKED, ['base'])
            return super().call(operation, payload, **kwargs)
    worker=DirectionWorker(None,((0,0,1),(0,1,0),(0,0,-1)))
    result=Planner(replace(AppSettings(),support_enabled=False))._generate('p',1,'s',
        [group('base',0),group('target',10),group('bolt',20,PartType.BOLT)],[],{},'base',worker=worker,priority_provider=ExteriorPriorityProvider())
    assert result.removal_order==['bolt','target']
    assert [q[1] for q in worker.calls[:3]]==['target','target','bolt']


def test_exposure_recomputes_when_cover_is_removed_and_base_blocks():
    target = replace(group('target', 0), bounds=Bounds(1, 1, 1, 2, 2, 2))
    cover = replace(group('cover', 0), bounds=Bounds(0, 0, 0, 3, 3, 3))
    score = ExteriorPriorityProvider.direction_score
    assert score(target, [cover], (0, 0, 1))[0] > score(target, [], (0, 0, 1))[0]
    groups = {'base': cover, 'target': target}
    assert ExteriorPriorityProvider().rank(groups, set(groups), 'base', []) == ['target']


def test_partial_video_validation_preserves_strict_confirmation_contract():
    plan = Plan('p', 'project', 1, 'base', ['base', 'a', 'b'],
                [PlanStep('a', 1, (0, 0, 1), (0, 0, -1), 10)], PlanningStatus.REVIEW_REQUIRED)
    with pytest.raises(ValueError): plan.validate()
    plan.validate(allow_partial=True)
    plan.steps.append(replace(plan.steps[0], group_id='foreign'))
    with pytest.raises(ValueError): plan.validate(allow_partial=True)
