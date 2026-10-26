from collections import Counter
from dataclasses import replace

from pa2.cad.path_check import state_key
from pa2.domain.models import AssemblyGroup, Bounds, ContactEdge, GeometryDecision, PartType, PathCheckResult
from pa2.planning.engine import Planner
from pa2.planning.priority import TargetFastenerPriorityProvider
from pa2.settings.config import AppSettings


def group(gid, x, kind=PartType.BLOCK):
    bounds = Bounds(x, 0, 0, x+1, 1, 1)
    return AssemblyGroup(gid, gid, [gid], kind, bounds, 1, bounds.center, True)


class Worker:
    def __init__(self, rule, directions=((0, 0, 1),)):
        self.rule = rule
        self.directions = directions
        self.calls = []

    def call(self, operation, payload, **kwargs):
        if operation == "directions":
            return self.directions
        assert operation == "path"
        gid = payload["moving"].id
        remaining = payload["remaining"]
        self.calls.append((frozenset(remaining), gid, tuple(payload["direction"]), payload["travel"]))
        decision, blockers = self.rule(gid, remaining)
        return PathCheckResult(gid, state_key(remaining), payload["direction"], payload["travel"],
                               decision, "CERTIFIED_CLEAR" if decision == GeometryDecision.PASS else
                               "PATH_BLOCKED" if decision == GeometryDecision.BLOCKED else "PATH_UNKNOWN",
                               list(blockers), elapsed_sec=7, evidence={})


PASS = GeometryDecision.PASS
BLOCKED = GeometryDecision.BLOCKED
UNKNOWN = GeometryDecision.UNKNOWN


def run(groups, rule, contacts=(), directions=((0, 0, 1),), **options):
    worker = Worker(rule, directions)
    settings = replace(AppSettings(), support_enabled=False, backtrack_depth=100,
                       backtrack_count=1000, **options)
    result = Planner(settings)._generate("p", 1, "s", [group("base", 0), *groups],
                                        list(contacts), {}, "base", priority_provider=TargetFastenerPriorityProvider(), worker=worker)
    return result, worker


def test_distance_target_priority_and_fastener_fallback():
    groups = {g.id: g for g in [group("base", 0), group("near", 2), group("far", 10),
                               group("bolt", 100, PartType.BOLT)]}
    ranked = TargetFastenerPriorityProvider().rank(groups, set(groups), "base", [])
    assert ranked == ["far", "near", "bolt"]
    result, _ = run(list(groups.values())[1:], lambda *_: (PASS, []))
    assert result.removal_order == ["far", "near", "bolt"]


def test_blocking_fastener_before_contact_and_target_retry_after_each_removal():
    groups = [group("target", 10), group("contact", 20, PartType.NUT), group("blocker", 1, PartType.BOLT)]
    def rule(gid, remaining):
        if gid == "target" and "blocker" in remaining:
            return BLOCKED, ["blocker"]
        return PASS, []
    result, worker = run(groups, rule, [ContactEdge("target", "contact", 0)])
    assert result.removal_order == ["blocker", "target", "contact"]
    assert [call[1] for call in worker.calls[:3]] == ["target", "blocker", "target"]


def test_failed_fastener_does_not_prevent_other_related_fastener_attempt():
    groups = [group("target", 10), group("bad", 20, PartType.BOLT), group("good", 1, PartType.NUT)]
    def rule(gid, remaining):
        if gid == "bad":
            return BLOCKED, ["base"]
        if gid == "target" and "good" in remaining:
            return BLOCKED, ["bad", "good"]
        return PASS, []
    result, worker = run(groups, rule)
    assert result.removal_order == ["good", "target"]
    assert [call[1] for call in worker.calls[:4]] == ["target", "bad", "good", "target"]


def test_multiple_fasteners_retry_target_between_removals():
    groups = [group("target", 10), group("b1", 3, PartType.BOLT), group("b2", 2, PartType.BOLT)]
    def rule(gid, remaining):
        obstacles = sorted(remaining & {"b1", "b2"})
        return (BLOCKED, obstacles) if gid == "target" and obstacles else (PASS, [])
    result, worker = run(groups, rule)
    assert result.removal_order == ["b1", "b2", "target"]
    assert [call[1] for call in worker.calls] == ["target", "b1", "target", "b2", "target"]


def test_failed_target_and_fastener_allow_another_target():
    groups = [group("far", 10), group("near", 2), group("bolt", 4, PartType.BOLT)]
    def rule(gid, remaining):
        if gid == "far":
            return BLOCKED, ["bolt"] if "bolt" in remaining else ["base"]
        if gid == "bolt":
            return BLOCKED, ["base"]
        return PASS, []
    result, worker = run(groups, rule)
    assert result.removal_order == ["near"]
    assert [call[1] for call in worker.calls[:3]] == ["far", "bolt", "near"]


def test_diamond_states_and_passing_directions_are_not_reexpanded():
    groups = [group("a", 3), group("b", 2), group("dead", 1)]
    result, worker = run(groups, lambda gid, _: (BLOCKED, ["base"]) if gid == "dead" else (PASS, []),
                         directions=((0, 0, 1), (0, 0, -1)))
    keys = [(r.state_key, r.group_id, tuple(r.direction), r.travel_mm) for r in result.path_results]
    assert len(keys) == len(set(keys))
    assert len(worker.calls) == len(set(worker.calls))
    assert result.metrics["closed_state_skips"] > 0
    assert len(result.removal_order) == 2
    assert all(call[2] == (0, 0, 1) for call in worker.calls if call[1] in {"a", "b"})


def test_blocked_witness_reuse_has_zero_current_cost():
    result, worker = run([group("dead", 20), group("free", 2)],
                         lambda gid, _: (BLOCKED, ["base"]) if gid == "dead" else (PASS, []))
    reused = [r for r in result.path_results if r.evidence["evaluation_source"] == "blocked_witness"]
    assert reused and all(r.elapsed_sec == 0 for r in reused)
    assert result.metrics["native_path_calls"] == len(worker.calls)
    assert result.metrics["tested_candidates"] == len(worker.calls) + len(reused)


def test_unknown_is_not_reused_across_states():
    result, worker = run([group("unknown", 20), group("free", 2)],
                         lambda gid, _: (UNKNOWN, []) if gid == "unknown" else (PASS, []))
    assert Counter(c[1] for c in worker.calls)["unknown"] == 2
    assert result.metrics["blocked_witness_cache_hits"] == 0


def test_duplicate_motion_keeps_one_record_and_does_not_replay_old_duration():
    worker = Worker(lambda *_: (BLOCKED, ["base"]), ((0, 0, 1), (0, 0, 1)))
    messages = []
    result = Planner(replace(AppSettings(), support_enabled=False))._generate(
        "p", 1, "s", [group("base", 0), group("dead", 2)], [], {}, "base",
        priority_provider=TargetFastenerPriorityProvider(), worker=worker,
        progress=lambda stage, message: messages.append(message))
    assert len(result.path_results) == result.metrics["native_path_calls"] == 1
    assert result.metrics["exact_path_cache_hits"] == 1
    assert messages[-1].endswith("0.0초")
    assert result.path_results[0].elapsed_sec == 7  # Original computation evidence remains intact.


def test_changed_travel_reuses_witness_when_both_paths_fully_exit_blocker():
    groups = [group("dead", 20), replace(group("free", 2), bounds=Bounds(2, 0, 0, 3, 1, 10))]
    result, worker = run(groups, lambda gid, _: (BLOCKED, ["base"]) if gid == "dead" else (PASS, []))
    calls = [c for c in worker.calls if c[1] == "dead"]
    assert len(calls) == 1
    reused=[p for p in result.path_results if p.evidence.get('witness_full_exit_projection_proof')]
    assert reused and reused[0].travel_mm!=reused[0].evidence['witness_source_travel_mm']


def test_short_witness_without_full_exit_cannot_be_reused_after_travel_change():
    class ShortWorker(Worker):
        def call(self,operation,payload,**kwargs):
            result=super().call(operation,payload,**kwargs)
            if operation=='path' and result.group_id=='dead':result.travel_mm=.01
            return result
    worker=ShortWorker(lambda gid,_:(BLOCKED,['base']) if gid=='dead' else (PASS,[]))
    groups=[group('base',0),group('dead',20),replace(group('free',2),bounds=Bounds(2,0,0,3,1,10))]
    result=Planner(replace(AppSettings(),support_enabled=False))._generate(
        'p',1,'s',groups,[],{},'base',priority_provider=TargetFastenerPriorityProvider(),worker=worker)
    assert sum(gid=='dead' for _,gid,_,_ in worker.calls)==2
    assert result.metrics['blocked_witness_cache_hits']==0


def test_removed_blocker_invalidates_witness():
    def rule(gid, remaining):
        return (BLOCKED, ["obstacle"]) if gid == "target" and "obstacle" in remaining else (PASS, [])
    result, worker = run([group("target", 10), group("obstacle", 2)], rule)
    assert result.removal_order == ["obstacle", "target"]
    assert Counter(c[1] for c in worker.calls)["target"] == 2


def test_depth_cutoff_does_not_close_partially_explored_state():
    from pa2.planning.engine import _Choice, _SearchContext
    from pa2.planning.search import RemainingSetSearch
    import time
    groups = {g.id: g for g in [group("base", 0), group("a", 3), group("b", 2), group("dead", 1)]}
    context = _SearchContext(time.perf_counter(), time.monotonic()+10)
    def evaluate(remaining, gid):
        return (None if gid == "dead" else _Choice(gid, (0, 0, 1), 1, 0)), set(), True
    search = RemainingSetSearch(groups, [], "base", TargetFastenerPriorityProvider(),
                               replace(AppSettings(), backtrack_depth=0), context, evaluate, lambda: False)
    search.run(set(groups))
    assert frozenset(groups) not in search.closed
    assert frozenset({"base", "b", "dead"}) not in search.closed
    assert frozenset({"base", "dead"}) in search.closed


def test_cancelled_evaluation_is_not_cached_or_closed():
    from pa2.planning.engine import _SearchContext
    from pa2.planning.search import RemainingSetSearch
    import time
    groups = {g.id: g for g in [group("base", 0), group("a", 3)]}
    context = _SearchContext(time.perf_counter(), time.monotonic()+10)
    search = RemainingSetSearch(groups, [], "base", TargetFastenerPriorityProvider(), AppSettings(),
                               context, lambda *_: (None, set(), False), lambda: False)
    assert not search.run(set(groups))
    assert not search.evaluations and not search.closed
