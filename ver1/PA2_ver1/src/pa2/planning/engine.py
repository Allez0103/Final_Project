from __future__ import annotations

import time
import uuid
from copy import deepcopy
from collections import Counter
from dataclasses import asdict, dataclass, field

from OCP.TopoDS import TopoDS_Shape

from pa2.cad.directions import GLOBALS
from pa2.cad.path_check import ConservativePathChecker, exit_distance, state_key
from pa2.cad.isolated import NativeCadSession
from pa2.jobs.isolated import NativeCallError, NativeTimeout
from pa2.cad.support import support_check
from pa2.domain.models import (
    AssemblyGroup,
    ContactEdge,
    GeometryDecision,
    GeometryStatus,
    Plan,
    PlanningResult,
    PlanningStatus,
    PlanStep,
    PathCheckResult,
    PartType,
)
from pa2.settings.config import AppSettings

from .priority import DefaultPriorityProvider, PriorityProvider, TargetFastenerPriorityProvider, ExteriorPriorityProvider
from .search import RemainingSetSearch, ExteriorVirtualSearch
from .two_stage import TwoStagePriorityProvider, TwoStageSearch
from .priority import is_fastener
from .attachments import fastener_attachments
from .fastener_direction import assigned_direction


@dataclass(slots=True)
class _Choice:
    group_id: str
    direction: tuple[float, float, float]
    travel_mm: float
    path_result_index: int


@dataclass(slots=True)
class _SearchContext:
    started: float
    deadline: float
    backtracks: int = 0
    max_depth_seen: int = 0
    cancelled: bool = False
    path_results: list = field(default_factory=list)
    choices: list[_Choice] = field(default_factory=list)
    best_choices: list[_Choice] = field(default_factory=list)
    tested_candidates: int = 0
    virtual_path_results: list = field(default_factory=list)
    skeleton_steps: int = 0
    skeleton_total: int = 0


class Planner:
    VERSION = "planner-v18-fastener-head-direction"

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    @staticmethod
    def choose_base(groups: list[AssemblyGroup], requested: str | None = None) -> str:
        valid = [group for group in groups if group.geometry_valid and group.volume_mm3 is not None]
        if not valid:
            raise ValueError("계산 가능한 유효 솔리드 그룹이 없습니다.")
        if requested is not None:
            match = next((group for group in valid if group.id == requested), None)
            if match is None:
                raise ValueError("선택한 기준 부품이 현재 유효 그룹에 없습니다.")
            return requested
        valid.sort(key=lambda group: (-(group.volume_mm3 or 0), group.id))
        return valid[0].id

    def generate(
        self, project_id, project_revision, snapshot_id, groups, contacts, shapes_by_body,
        base_group_id=None, priority_provider=None, cancel_check=lambda: False,
        progress=lambda *_: None, jobs_dir=None,
        collision_exception_ids=(),
    ) -> PlanningResult:
        with NativeCadSession(groups, shapes_by_body, native_timeout=self.settings.native_operation_timeout_sec,
                              cancel_check=cancel_check, jobs_dir=jobs_dir) as worker:
            return self._generate(project_id, project_revision, snapshot_id, groups, contacts,
                                  shapes_by_body, base_group_id, priority_provider, cancel_check, worker, progress,
                                  collision_exception_ids)

    def _generate(
        self,
        project_id: str,
        project_revision: int,
        snapshot_id: str,
        groups: list[AssemblyGroup],
        contacts: list[ContactEdge],
        shapes_by_body: dict[str, TopoDS_Shape],
        base_group_id: str | None = None,
        priority_provider: PriorityProvider | None = None,
        cancel_check=lambda: False,
        worker=None,
        progress=lambda *_: None,
        collision_exception_ids=(),
    ) -> PlanningResult:
        started = time.perf_counter()
        exceptions = list(dict.fromkeys(collision_exception_ids))
        if set(exceptions) - {g.id for g in groups}:
            raise ValueError("예외 부품이 현재 모델에 없습니다.")
        if base_group_id in exceptions:
            raise ValueError("기준 부품은 간섭 예외 부품으로 지정할 수 없습니다.")
        base_id = self.choose_base([g for g in groups if g.id not in exceptions], base_group_id)
        provider = priority_provider or TwoStagePriorityProvider()
        group_map = {group.id: group for group in groups}
        attachments = {gid: value for gid, value in fastener_attachments(group_map, contacts, base_id).items()
                       if gid not in exceptions}
        resolved = self.settings.resolved_for_diagonal(group_map[base_id].bounds.union(group.bounds for group in groups).diagonal)
        context = _SearchContext(started=started, deadline=time.monotonic() + self.settings.generation_timeout_sec)
        initial = set(group_map)
        directions = {}
        path_cache = {}
        virtual_cache = {}
        blocked_witnesses = {}
        calculation_stats = Counter()
        direction_hints = {}
        def ordered_v13(remaining, group_id):
            group = group_map[group_id]
            obstacles = [group_map[x] for x in sorted(remaining-{group_id})]
            # Only contacting neighbors still present affect this state's hint.
            neighbors = sorted({e.group_b if e.group_a == group_id else e.group_a
                for e in contacts if group_id in (e.group_a,e.group_b)} & (remaining-{group_id}))
            hint_key = (group_id, tuple(neighbors))
            if hint_key not in direction_hints:
                t = time.monotonic()
                calculation_stats['direction_hint_calls'] += 1
                try:
                    direction_hints[hint_key] = worker.call('direction_policy', {
                        'gid':group_id,'neighbors':neighbors,'epsilon':resolved['geometry_epsilon_mm'],
                        'gap':self.settings.contact_gap_mm,'fastener':is_fastener(group)},
                        deadline=min(context.deadline,t+self.settings.candidate_timeout_sec))
                except NativeCallError as exc:
                    direction_hints[hint_key] = {'method':'exposure_hint_failed','error':str(exc)}
                calculation_stats['direction_hint_elapsed_sec'] += time.monotonic()-t
            hint = direction_hints[hint_key]
            exposure = ExteriorPriorityProvider().ordered_directions(group, obstacles, GLOBALS)
            axis = hint.get('axis')
            if is_fastener(group) and axis:
                axial = ExteriorPriorityProvider().ordered_directions(group, obstacles,
                    [tuple(axis),tuple(-v for v in axis)])
                return axial+[d for d in exposure if all(abs(sum(x*y for x,y in zip(d,a)))<1-1e-8 for a in axial)]
            normal=hint.get('normal')
            if normal and hint.get('method')=='largest_planar_contact':
                exposure = sorted(exposure,key=lambda d:-sum(x*y for x,y in zip(d,normal)))
            # A learned provider only reorders these existing six axes. The
            # collision policy and first-PASS early exit below are unchanged.
            if hasattr(provider, 'rank_directions') and not is_fastener(group):
                return provider.rank_directions(remaining, group_id, exposure)
            return exposure

        # Explicit user exceptions are untested steps, not fabricated PASSes.
        # They leave the obstacle set before all automatic planning operations.
        for gid in exceptions:
            if cancel_check():
                context.cancelled=True
                break
            group=group_map[gid]
            obstacles=[group_map[x] for x in sorted(initial-{gid})]
            direction=ExteriorPriorityProvider().ordered_directions(group,obstacles,GLOBALS)[0]
            travel=exit_distance(group.bounds,[g.bounds for g in obstacles],direction,resolved['exit_clearance_mm'])
            index=len(context.path_results)
            context.path_results.append(PathCheckResult(gid,state_key(initial),direction,travel,
                GeometryDecision.NOT_TESTED,'USER_COLLISION_EXCEPTION',policy_version=self.VERSION,
                evidence={'user_collision_exception':True,'evaluation_source':'user_exception',
                          'review_required':True,'support_status':'NOT_TESTED',
                          'direction_method':'highest_exposure_six_axes','virtual_probe':False}))
            context.choices.append(_Choice(gid,direction,travel,index))
            initial.remove(gid)
        context.best_choices=list(context.choices)
        support_edges = None
        support_unknown = 0
        if self.settings.support_enabled and contacts:
            support_edges=[]
            try:
                for index,edge in enumerate(contacts):
                    if edge.group_a in exceptions or edge.group_b in exceptions or (isinstance(provider, TwoStagePriorityProvider) and (edge.group_a in attachments or edge.group_b in attachments)):
                        continue
                    if time.monotonic()>=context.deadline:
                        break
                    progress("support",f"지지 접촉 확인 {index+1}/{len(contacts)}")
                    try:
                        support_edges.extend(worker.call("support",{"groups":(edge.group_a,edge.group_b),
                            "gap":self.settings.contact_gap_mm,"epsilon":resolved["geometry_epsilon_mm"]},deadline=context.deadline))
                    except NativeCallError:
                        support_unknown+=1
            except InterruptedError:
                context.cancelled=True
        floor_z=min(group.bounds.zmin for group in groups)

        def evaluate(remaining: set[str], group_id: str, phase='all', preferred=(), virtual=False):
            blockers = set()
            group = group_map[group_id]
            if time.monotonic() >= context.deadline:
                return None, blockers, False
            obstacles = [group_map[other] for other in sorted(remaining - {group_id})]
            obstacle_bounds = [item.bounds for item in obstacles]
            if isinstance(provider,TwoStagePriorityProvider):
                ordered = ordered_v13(remaining, group_id)
            elif group_id not in directions:
                try:
                    directions[group_id] = worker.call("directions", {"group_id": group_id,
                        "max_directions": self.settings.max_directions,
                        "merge_angle_deg": self.settings.direction_merge_angle_deg}, deadline=context.deadline)
                except NativeCallError:
                    directions[group_id] = GLOBALS
            if not isinstance(provider,TwoStagePriorityProvider):
                ordered = directions[group_id]
            if isinstance(provider, ExteriorPriorityProvider) and not isinstance(provider,TwoStagePriorityProvider):
                ordered = provider.ordered_directions(group, obstacles, ordered, preferred)
                if phase == 'quick':
                    ordered = ordered[:2]
            cache = virtual_cache if virtual else path_cache
            records = context.virtual_path_results if virtual else context.path_results
            for direction in ordered:
                if cancel_check():
                    context.cancelled = True
                    return None, blockers, False
                if time.monotonic() >= context.deadline:
                    return None, blockers, False
                travel = exit_distance(group.bounds, obstacle_bounds, direction, resolved["exit_clearance_mm"])
                if virtual:
                    progress('skeleton', f"일반 부품 초안(체결물 제외) · {context.skeleton_steps}/{context.skeleton_total}개 · {group.display_name} · 가상 후보 {len(context.virtual_path_results)+1}")
                else:
                    progress("planning", f"분해 경로 확인 · {len(context.best_choices)}/{len(groups)-1}개 · {group.display_name} · 후보 {context.tested_candidates+1}")
                key = (state_key(remaining), group_id, tuple(direction), travel)
                motion_key = (group_id, tuple(direction))
                calculation_stats["candidate_lookups"] += 1
                exact_reuse = key in cache
                def applicable_witness(item):
                    if not item.obstacle_ids or not set(item.obstacle_ids)<=remaining:return False
                    # Both paths extend beyond every witness obstacle's entire
                    # projection. Every possible collision with those unchanged
                    # obstacles lies before either endpoint, even if travel
                    # changed after removing an unrelated part.
                    required=exit_distance(group.bounds,[group_map[x].bounds for x in item.obstacle_ids],
                                           direction,resolved['geometry_epsilon_mm']*4)
                    return min(travel,item.travel_mm)>=required
                witness = next((item for item in blocked_witnesses.get(motion_key, [])
                                if applicable_witness(item)), None)
                if key in cache:
                    # Reuse the same diagnostic index, never append a duplicate
                    # state+motion record or count its old duration again.
                    index = cache[key]
                    result = records[index]
                    calculation_stats["exact_path_cache_hits"] += 1
                elif witness is not None:
                    result = deepcopy(witness)
                    result.state_key = key[0]
                    result.travel_mm = travel
                    result.elapsed_sec = 0.0
                    result.evidence["evaluation_source"] = "blocked_witness"
                    result.evidence["witness_source_state"] = witness.state_key
                    result.evidence['witness_source_travel_mm']=witness.travel_mm
                    result.evidence['witness_full_exit_projection_proof']=True
                    result.evidence["original_calculation_elapsed_sec"] = witness.elapsed_sec
                    # Details for removed obstacles are historical evidence,
                    # not newly inspected pairs in the current state.
                    result.evidence["witness_obstacle_ids"] = list(witness.obstacle_ids)
                    result.evidence["calculation_metrics"] = {"pair_calculations": 0, "pair_cache_hits": 0, "activity_counts": {}}
                    calculation_stats["blocked_witness_cache_hits"] += 1
                else:
                    candidate_started = time.monotonic()
                    calculation_stats["native_path_calls"] += 1
                    calculation_stats["virtual_native_path_calls" if virtual else "actual_native_path_calls"] += 1
                    try:
                        result = worker.call("path", {"moving": group, "obstacles": obstacles,
                            "direction": direction, "travel": travel, "remaining": remaining,
                            "epsilon": resolved["geometry_epsilon_mm"],
                            "min_interval": resolved["path_min_interval_mm"],
                            "bolt_initial_overlap_enabled":self.settings.bolt_initial_overlap_enabled,
                            "initial_overlap_region_enabled":self.settings.initial_overlap_region_enabled,
                            "initial_overlap_decrease_enabled":self.settings.initial_overlap_decrease_enabled,
                            "cad_boolean_threads":self.settings.cad_boolean_threads,
                            "timeout": self.settings.candidate_timeout_sec},
                            deadline=min(context.deadline, candidate_started+self.settings.candidate_timeout_sec))
                    except NativeCallError as exc:
                        result = PathCheckResult(group_id=group_id, state_key=key[0], direction=direction,
                            travel_mm=travel, decision=GeometryDecision.UNKNOWN,
                            reason_code="TIME_BUDGET_EXCEEDED" if isinstance(exc,NativeTimeout) else "PATH_UNKNOWN",
                            obstacle_ids=[], elapsed_sec=time.monotonic()-candidate_started,
                            policy_version=ConservativePathChecker.VERSION,
                            evidence={"native_error":str(exc),"native_error_type":type(exc).__name__})
                    calculation_stats["native_path_elapsed_sec"] += time.monotonic()-candidate_started
                    result.evidence["evaluation_source"] = "native"
                    native_metrics = result.evidence.get("calculation_metrics", {})
                    calculation_stats["pair_calculations"] += native_metrics.get("pair_calculations", 0)
                    calculation_stats["pair_cache_hits"] += native_metrics.get("pair_cache_hits", 0)
                    calculation_stats["brep_common_calls"] += native_metrics.get("activity_counts", {}).get("BREP_COMMON", 0)
                    calculation_stats['brep_common_cache_hits'] += native_metrics.get('activity_counts',{}).get('BREP_COMMON_CACHE_HIT',0)
                    calculation_stats['brep_common_retries'] += native_metrics.get('activity_counts',{}).get('BREP_COMMON_RETRY',0)
                    if "native_error" in result.evidence:
                        calculation_stats["native_calls_without_counters"] += 1
                    if result.decision == GeometryDecision.BLOCKED and result.obstacle_ids:
                        blocked_witnesses.setdefault(motion_key, []).append(deepcopy(result))
                if key not in cache:
                    index = len(records)
                    cache[key] = index
                    result.evidence['virtual_probe'] = virtual
                    if isinstance(provider,TwoStagePriorityProvider):
                        result.evidence['direction_order_policy']='axis-first/contact-normal-or-exposure-six-v13'
                        if virtual:
                            result.evidence['omitted_fastener_ids']=sorted(x for x in initial if is_fastener(group_map[x]) and x!=base_id)
                    records.append(result)
                    if isinstance(provider,TwoStagePriorityProvider):
                        result.evidence['omitted_fastener_ids']=sorted(attachments)
                        result.evidence['general_first_single_search']=True
                    if not virtual:
                        context.tested_candidates += 1
                labels={GeometryDecision.PASS:"경로 확인",GeometryDecision.BLOCKED:"간섭 확인",GeometryDecision.UNKNOWN:"미판정"}
                lookup_elapsed = 0.0 if exact_reuse else result.elapsed_sec
                record_label=f'가상 후보 {len(context.virtual_path_results)}' if virtual else f'실제 후보 {context.tested_candidates}'
                progress('skeleton' if virtual else 'planning', f"{record_label} · 신규 요청 {calculation_stats['native_path_calls']} · 차단 재사용 {calculation_stats['blocked_witness_cache_hits']} · {labels[result.decision]} · {result.reason_code} · {lookup_elapsed:.1f}초")
                if result.decision == GeometryDecision.BLOCKED:
                    blockers.update(result.obstacle_ids)
                if result.reason_code == "INITIAL_OVERLAP":
                    # Every direction shares the same overlapping start state.
                    break
                if result.decision != GeometryDecision.PASS:
                    continue
                if virtual:
                    # A feasibility hint only. No support claim or retained
                    # sequence step may be made from this hypothetical state.
                    return _Choice(group_id, direction, travel, index), blockers, True
                new_remaining = remaining - {group_id}
                support_status, support_evidence = support_check(
                    [group_map[item] for item in new_remaining], base_id, self.settings.contact_gap_mm, self.settings.support_enabled,
                    support_edges=support_edges,floor_z=floor_z,
                )
                if support_status != GeometryDecision.PASS:
                    result.evidence["support_status"]=support_status.value
                    result.evidence["support"]=support_evidence
                    result.evidence["path_reason"]=result.reason_code
                    unsupported=list(support_evidence.get("unsupported", []))
                    progress("planning",f"지지 경로 미확인 · {len(unsupported)}개 부품")
                    if self.settings.allow_support_unknown_draft and support_status==GeometryDecision.UNKNOWN:
                        result.reason_code="PATH_CLEAR_SUPPORT_UNVERIFIED"
                        result.evidence["review_required"]=True
                    else:
                        result.decision = GeometryDecision.UNKNOWN
                        result.reason_code = "SUPPORT_UNKNOWN"
                        result.obstacle_ids = unsupported
                        break  # Support does not depend on removal direction.
                # All passing directions remove the same group and lead to
                # the same remaining set; exploring that child once suffices.
                return _Choice(group_id, direction, travel, index), blockers, True
            return None, blockers, True

        search_type = TwoStageSearch if isinstance(provider,TwoStagePriorityProvider) else ExteriorVirtualSearch if isinstance(provider, ExteriorPriorityProvider) else RemainingSetSearch
        search = search_type(group_map, contacts, base_id, provider,
                                   self.settings, context, evaluate, cancel_check)
        def fastener_hint(gid):
            key=(gid, ())
            if key not in direction_hints and time.monotonic()<context.deadline:
                t=time.monotonic()
                calculation_stats['direction_hint_calls']+=1
                try:
                    direction_hints[key]=worker.call('direction_policy',{
                        'gid':gid,'neighbors':[],'epsilon':resolved['geometry_epsilon_mm'],
                        'gap':self.settings.contact_gap_mm,'fastener':True,
                        'fastener_kind':group_map[gid].part_type.value},
                        deadline=min(context.deadline,t+self.settings.candidate_timeout_sec))
                except NativeCallError as exc:
                    direction_hints[key]={'method':'axis_hint_failed','error':str(exc)}
                calculation_stats['direction_hint_elapsed_sec']+=time.monotonic()-t
            return direction_hints.get(key,{})

        def assigned_fastener(remaining, gid, target_id):
            group=group_map[gid]
            target=group_map[target_id]
            obstacles=[group_map[x] for x in sorted(remaining-{gid})]
            hint=fastener_hint(gid)
            axis=hint.get('axis')
            connected=[]
            if group.part_type==PartType.NUT:
                neighbors={e.group_b if e.group_a==gid else e.group_a for e in contacts
                           if gid in (e.group_a,e.group_b)}
                connected=[(group_map[x],fastener_hint(x)) for x in sorted(neighbors)
                           if group_map[x].part_type==PartType.BOLT]
            direction,method,linked_bolt=assigned_direction(group,target,hint,connected)
            travel=exit_distance(group.bounds,[g.bounds for g in obstacles],direction,resolved['exit_clearance_mm'])
            index=len(context.path_results)
            context.path_results.append(PathCheckResult(gid,state_key(remaining),direction,travel,
                GeometryDecision.NOT_TESTED,'FASTENER_AXIS_ASSIGNED',policy_version=self.VERSION,
                evidence={'evaluation_source':'fastener_assignment','path_check_skipped':True,
                          'target_group_id':target_id,'axis':axis,'virtual_probe':False,
                          'direction_method':method,'linked_bolt_id':linked_bolt,
                          'head_direction':hint.get('head_direction'),
                          'head_center':hint.get('head_center')}))
            return _Choice(gid,direction,travel,index)
        if isinstance(search,TwoStageSearch):search.assign_fastener=assigned_fastener
        # Cache the inexpensive face hints before general-part search can consume
        # its time budget. Insertion then needs no native calls, even at timeout.
        if isinstance(search,TwoStageSearch):
            for gid in sorted(attachments):
                if cancel_check():
                    break
                fastener_hint(gid)
        try:
            complete = search.run(initial)
        except InterruptedError:
            context.cancelled = True
            complete = False
        checked_prefix_count=len(context.best_choices)
        unresolved_ids=[]
        if isinstance(search,TwoStageSearch) and not complete and not context.cancelled:
            # Preserve the accepted prefix. Complete only the editable draft;
            # no synthetic PASS or support claim is made for these additions.
            remaining=set(group_map)-set(attachments)-{c.group_id for c in context.best_choices}
            while remaining!={base_id}:
                if cancel_check():
                    context.cancelled=True
                    break
                ranked=provider.rank(group_map,remaining,base_id,contacts)
                gid=next((x for x in ranked if not is_fastener(group_map[x])),ranked[0])
                if is_fastener(group_map[gid]):
                    choice=assigned_fastener(remaining,gid,base_id)
                else:
                    related=[]  # Fasteners are inserted only after the general draft is complete.
                    for fastener in related:
                        context.best_choices.append(assigned_fastener(remaining,fastener,gid))
                        remaining.remove(fastener)
                    group=group_map[gid]
                    obstacles=[group_map[x] for x in sorted(remaining-{gid})]
                    direction=ExteriorPriorityProvider().ordered_directions(group,obstacles,GLOBALS)[0]
                    travel=exit_distance(group.bounds,[g.bounds for g in obstacles],direction,resolved['exit_clearance_mm'])
                    previous=[i for i,r in enumerate(context.path_results) if r.group_id==gid and r.decision in (GeometryDecision.BLOCKED,GeometryDecision.UNKNOWN)]
                    index=len(context.path_results)
                    context.path_results.append(PathCheckResult(gid,state_key(remaining),direction,travel,
                        GeometryDecision.NOT_TESTED,'DRAFT_UNRESOLVED',policy_version=self.VERSION,
                        evidence={'evaluation_source':'draft_completion','review_required':True,
                                  'prior_result_indices':previous,'virtual_probe':False,
                                  'budget_exhausted':time.monotonic()>=context.deadline}))
                    choice=_Choice(gid,direction,travel,index)
                    unresolved_ids.append(gid)
                context.best_choices.append(choice)
                remaining.remove(gid)
        if isinstance(search, TwoStageSearch) and not context.cancelled:
            general_choices = list(context.best_choices)
            positions = {c.group_id: i for i, c in enumerate(general_choices)}
            owners = {gid: min((target for target in relation['targets'] if target in positions),
                              key=positions.get, default=base_id)
                      for gid, relation in attachments.items()}
            interleaved = []
            remaining = set(group_map)
            for choice in general_choices:
                for gid in sorted(g for g in attachments if owners[g] == choice.group_id):
                    assigned = assigned_fastener(remaining, gid, choice.group_id)
                    context.path_results[assigned.path_result_index].evidence['attachment'] = attachments[gid]
                    interleaved.append(assigned)
                    remaining.remove(gid)
                interleaved.append(choice)
                remaining.discard(choice.group_id)
            for gid in sorted(g for g in attachments if g in remaining):
                assigned = assigned_fastener(remaining, gid, base_id)
                context.path_results[assigned.path_result_index].evidence['attachment'] = attachments[gid]
                interleaved.append(assigned)
                remaining.remove(gid)
            context.best_choices = interleaved
        if context.cancelled:
            status, reason = PlanningStatus.CANCELLED, "사용자가 탐색을 취소했습니다."
        elif complete:
            status, reason = PlanningStatus.COMPLETE, "모든 이동 그룹의 보수적 경로와 지지 조건을 확인했습니다."
            if any(context.path_results[c.path_result_index].evidence.get("fastener_exceptions") for c in context.best_choices):
                reason="볼트 초기 체결 겹침 예외 정책으로 전체 경로와 지지 조건을 확인했습니다. 나사 풀림 회전은 검증하지 않았습니다."
        elif time.monotonic() >= context.deadline or context.backtracks >= self.settings.backtrack_count:
            status, reason = PlanningStatus.NO_SOLUTION_WITHIN_BUDGET, "설정된 탐색 예산 안에서 전체 경로를 증명하지 못했습니다."
        else:
            status, reason = PlanningStatus.PARTIAL, "일부 경로가 BLOCKED 또는 UNKNOWN이어서 부분 결과만 생성했습니다."
            if not context.best_choices:
                reason="검사를 완료했지만 경로·지지 조건을 만족하는 제거 단계를 확인하지 못했습니다. 순서 생성 진단에서 원인을 확인하세요."

        review_choices=[c for c in context.best_choices if context.path_results[c.path_result_index].evidence.get("review_required") and context.path_results[c.path_result_index].reason_code!='DRAFT_UNRESOLVED' and not context.path_results[c.path_result_index].evidence.get('user_collision_exception')]
        region_choices=[c for c in context.best_choices if context.path_results[c.path_result_index].evidence.get("initial_region_exceptions")]
        decrease_choices=[c for c in context.best_choices if context.path_results[c.path_result_index].evidence.get("initial_decrease_exceptions")]
        repair_choices=[c for c in context.best_choices if context.path_results[c.path_result_index].evidence.get("input_repairs")]
        if (review_choices or region_choices or decrease_choices or repair_choices) and not context.cancelled:
            status=PlanningStatus.REVIEW_REQUIRED
            coverage="전체" if complete else "부분"
            reason=f"{coverage} 검토용 초안 {len(context.best_choices)}/{max(0,len(groups)-1)}단계입니다. 초기 영역 예외 {len(region_choices)}단계, 지지 미검증 {len(review_choices)}단계로 검토가 필요합니다."
            if decrease_choices:reason+=f" 초기 겹침 감소 예외 {len(decrease_choices)}단계(위치별 검사; 동일 상대의 국소 새 간섭 배제 불가)."
            if repair_choices:reason+=f" 계산용 형상 파라미터 보정 관련 {len(repair_choices)}단계."
            if not complete:
                reason+=" 충돌·경로 미판정 또는 탐색 예산으로 제외된 부품은 진단에서 확인하세요."
        if exceptions and not context.cancelled:
            status=PlanningStatus.REVIEW_REQUIRED
            reason+=f" 사용자 지정 간섭·지지 미검증 예외 {len(exceptions)}개를 분해 선두에 배치했습니다."
        assigned_choices=[c for c in context.best_choices if context.path_results[c.path_result_index].reason_code=='FASTENER_AXIS_ASSIGNED']
        if (unresolved_ids or assigned_choices) and not context.cancelled:
            status=PlanningStatus.REVIEW_REQUIRED
            reason=f"편집용 초안 {len(context.best_choices)}/{max(0,len(groups)-1)}단계 생성. 볼트·너트 축방향 배치 {len(assigned_choices)}개, 해결되지 않은 일반 부품 {len(unresolved_ids)}개."
            if exceptions:reason+=f" 사용자 지정 예외 {len(exceptions)}개를 분해 선두에 배치했습니다."

        run_id = str(uuid.uuid4())
        assembly_choices = list(reversed(context.best_choices))
        steps = [
            PlanStep(
                group_id=choice.group_id,
                step_index=index,
                removal_direction=choice.direction,
                assembly_direction=tuple(-x for x in choice.direction),  # type: ignore[arg-type]
                travel_mm=choice.travel_mm,
                process_text=f"{group_map[choice.group_id].display_name} 조립",
                material_text=group_map[choice.group_id].display_name,
                geometry_status=GeometryStatus.SUPPORT_UNVERIFIED if context.path_results[choice.path_result_index].evidence.get("review_required") else GeometryStatus.INITIAL_REGION_EXCEPTION if context.path_results[choice.path_result_index].evidence.get("initial_region_exceptions") else GeometryStatus.GEOMETRY_REPAIRED if context.path_results[choice.path_result_index].evidence.get("input_repairs") else GeometryStatus.FASTENER_EXCEPTION if context.path_results[choice.path_result_index].evidence.get("fastener_exceptions") else GeometryStatus.AUTO_CHECKED,
                caution_text="",
                source_run_id=run_id,
            )
            for index, choice in enumerate(assembly_choices, start=1)
        ]
        for step,choice in zip(steps,assembly_choices):
            if context.path_results[choice.path_result_index].evidence.get('user_collision_exception'):
                step.geometry_status=GeometryStatus.USER_COLLISION_EXCEPTION
            if context.path_results[choice.path_result_index].evidence.get("initial_decrease_exceptions"):
                if step.geometry_status!=GeometryStatus.SUPPORT_UNVERIFIED:
                    step.geometry_status=GeometryStatus.INITIAL_DECREASE_EXCEPTION
            # Video caution is user-authored text. Automatic evidence belongs
            # to diagnostics and statuses, never to this editable text field.
            step.caution_text=""
            record=context.path_results[choice.path_result_index]
            if record.reason_code=='FASTENER_AXIS_ASSIGNED':
                step.geometry_status=GeometryStatus.FASTENER_ASSIGNED
            elif record.reason_code=='DRAFT_UNRESOLVED':
                step.geometry_status=GeometryStatus.DRAFT_UNRESOLVED
        plan = Plan(
            id=str(uuid.uuid4()),
            project_id=project_id,
            revision=1,
            base_group_id=base_id,
            group_ids=sorted(group_map),
            steps=steps,
            status=status,
            source_algorithm=provider.name,
            input_snapshot_id=snapshot_id,
            settings_version=self.settings.version,
        )
        return PlanningResult(
            status=status,
            removal_order=[choice.group_id for choice in context.best_choices],
            assembly_plan=plan,
            path_results=context.path_results,
            reason=reason,
            metrics={
                "learning_models": provider.model_metrics() if hasattr(provider, 'model_metrics') else None,
                "elapsed_sec": time.perf_counter()-started,
                "tested_candidates": context.tested_candidates,
                "collision_exception_ids":exceptions,
                "collision_exception_steps":sum(context.path_results[c.path_result_index].evidence.get('user_collision_exception',False) for c in context.best_choices),
                "direction_hint_calls":calculation_stats['direction_hint_calls'],
                "direction_hint_elapsed_sec":calculation_stats['direction_hint_elapsed_sec'],
                "direction_hints":[dict(group_id=k[0],remaining_contact_ids=list(k[1]),**v) for k,v in direction_hints.items()],
                "skeleton_order":getattr(search,'skeleton',[]),
                "skeleton_draft_order":getattr(provider,'skeleton',[]),
                "skeleton_remaining":getattr(search,'skeleton_remaining',[]),
                "skeleton_elapsed_sec":getattr(search,'skeleton_elapsed_sec',0.),
                "skeleton_budget_fraction":getattr(search,'skeleton_budget_fraction',None),
                "skeleton_budget_exhausted":getattr(search,'skeleton_budget_exhausted',False),
                "candidate_count_definition": "unique general-part remaining-state + group + direction + travel records; includes witness reuse; excludes fastener assignment",
                "fastener_insertion_only": isinstance(search, TwoStageSearch),
                "fastener_attachments": attachments,
                "fastener_without_moving_target_ids": sorted(gid for gid, relation in attachments.items() if not relation['targets']),
                "native_path_calls": calculation_stats["native_path_calls"],
                "actual_native_path_calls": calculation_stats["actual_native_path_calls"],
                "virtual_native_path_calls": calculation_stats["virtual_native_path_calls"],
                "virtual_candidate_records": len(context.virtual_path_results),
                "virtual_paths": [asdict(r) for r in context.virtual_path_results],
                "virtual_target_probes": search.stats['virtual_target_probes'],
                "virtual_target_passes": search.stats['virtual_target_passes'],
                "native_path_elapsed_sec": calculation_stats["native_path_elapsed_sec"],
                "blocked_witness_cache_hits": calculation_stats["blocked_witness_cache_hits"],
                "exact_path_cache_hits": calculation_stats["exact_path_cache_hits"],
                "candidate_lookups": calculation_stats["candidate_lookups"],
                "pair_calculations": calculation_stats["pair_calculations"],
                "pair_cache_hits": calculation_stats["pair_cache_hits"],
                "brep_common_calls": calculation_stats["brep_common_calls"],
                'brep_common_cache_hits':calculation_stats['brep_common_cache_hits'],
                'brep_common_retries':calculation_stats['brep_common_retries'],
                "native_calls_without_counters": calculation_stats["native_calls_without_counters"],
                "native_counter_note": "pair/COMMON counters cover returned native calls only; killed calls cannot report partial counters",
                "unique_states": len(search.visited),
                "closed_states": len(search.closed),
                "state_visits": search.stats["state_visits"],
                "closed_state_skips": search.stats["closed_state_skips"],
                "group_evaluation_cache_hits": search.stats["group_evaluation_cache_hits"],
                "duplicate_group_skips": search.stats["duplicate_group_skips"],
                "related_fastener_attempts": search.stats["related_fastener_attempts"],
                "preferred_target_retries": search.stats["preferred_target_retries"],
                "backtracks": context.backtracks,
                "max_depth": context.max_depth_seen,
                "completed_groups": len(context.best_choices),
                "total_moving_groups": max(0, len(groups)-1),
                "unknown_count": sum(item.decision == GeometryDecision.UNKNOWN for item in context.path_results),
                "blocked_count": sum(item.decision == GeometryDecision.BLOCKED for item in context.path_results),
                "initial_overlap_count": sum(item.reason_code == "INITIAL_OVERLAP" for item in context.path_results),
                "native_timeout_count": sum(item.reason_code == "TIME_BUDGET_EXCEEDED" for item in context.path_results),
                "support_edges": len(support_edges) if support_edges is not None else 0,
                "support_unknown_pairs": support_unknown,
                "bolt_initial_overlap_enabled":self.settings.bolt_initial_overlap_enabled,
                "initial_overlap_region_enabled":self.settings.initial_overlap_region_enabled,
                "initial_overlap_decrease_enabled":self.settings.initial_overlap_decrease_enabled,
                "initial_decrease_exception_steps":len(decrease_choices),
                "initial_decrease_exception_candidates":sum(bool(item.evidence.get("initial_decrease_exceptions")) for item in context.path_results),
                "initial_region_exception_candidates":sum(bool(item.evidence.get("initial_region_exceptions")) for item in context.path_results),
                "initial_region_exception_steps":len(region_choices),
                "fastener_exception_candidates":sum(bool(item.evidence.get("fastener_exceptions")) for item in context.path_results),
                "fastener_exception_steps":sum(bool(context.path_results[c.path_result_index].evidence.get("fastener_exceptions")) for c in context.best_choices),
                "support_unverified_steps":len(review_choices),
                "allow_support_unknown_draft":self.settings.allow_support_unknown_draft,
                "search_complete":complete,
                "draft_complete":len(context.best_choices)==len(groups)-1,
                "checked_prefix_steps":checked_prefix_count,
                "unresolved_general_ids":unresolved_ids,
                "unresolved_general_steps":len(unresolved_ids),
                "fastener_assigned_steps":len(assigned_choices),
                "verified_path_steps":sum(context.path_results[c.path_result_index].decision==GeometryDecision.PASS for c in context.best_choices),
                "path_complete":complete and all(context.path_results[c.path_result_index].decision==GeometryDecision.PASS for c in context.best_choices),
                "input_repaired_steps":len(repair_choices),
                "input_repaired_groups":sorted({repair["group_id"] for item in context.path_results for repair in item.evidence.get("input_repairs",[])}),
                "unknown_pair_codes":dict(Counter(detail["code"] for item in context.path_results
                    for detail in item.evidence.get("pair_diagnostics",[]) if detail.get("decision")=="UNKNOWN")),
            },
        )


__all__ = ["DefaultPriorityProvider", "Planner"]

