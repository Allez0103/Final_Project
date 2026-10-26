from __future__ import annotations

import hashlib
import json
import math
import time
from collections import OrderedDict, Counter
from dataclasses import replace
from functools import wraps

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box
from OCP.gp import gp_Vec
from OCP.collections import List_TopoDS_Shape as TopTools_ListOfShape

from pa2.domain.models import AssemblyGroup, Bounds, GeometryDecision, PathCheckResult, PartType, Vector3, normalize

from .shapes import translated
from . import sweep
from .prepare import prepare
from . import boolean_options
from .conservative_proxy import ProxyStore, acceleration_enabled


def _boolean(operation,a,b):
    query=operation()
    arguments=TopTools_ListOfShape(); arguments.Append(a)
    tools=TopTools_ListOfShape(); tools.Append(b)
    query.SetArguments(arguments); query.SetTools(tools)
    query.SetRunParallel(boolean_options.THREADS>1)
    query.SetNonDestructive(True); query.Build()
    return query


def _timed_stage(name):
    def decorate(method):
        @wraps(method)
        def measured(self,*args,**kwargs):
            started=time.perf_counter()
            try:return method(self,*args,**kwargs)
            finally:self.stage_times[name]+=time.perf_counter()-started
        return measured
    return decorate


def state_key(group_ids: set[str]) -> str:
    return hashlib.sha256(json.dumps(sorted(group_ids)).encode("utf-8")).hexdigest()


def exit_distance(moving: Bounds, obstacles: list[Bounds], direction: Vector3, clearance: float) -> float:
    d = normalize(direction)
    corners_m = [(x,y,z) for x in (moving.xmin,moving.xmax) for y in (moving.ymin,moving.ymax) for z in (moving.zmin,moving.zmax)]
    obstacle_union = Bounds.union(obstacles)
    corners_r = [(x,y,z) for x in (obstacle_union.xmin,obstacle_union.xmax) for y in (obstacle_union.ymin,obstacle_union.ymax) for z in (obstacle_union.zmin,obstacle_union.zmax)]
    p_min = min(sum(p[i]*d[i] for i in range(3)) for p in corners_m)
    r_max = max(sum(p[i]*d[i] for i in range(3)) for p in corners_r)
    return max(0.0, r_max - p_min) + clearance


def _aabb_start_contact_moves_apart(moving: Bounds, obstacle: Bounds, direction: Vector3, epsilon: float) -> bool:
    # A proof for axis-aligned extraction: AABBs may touch at t=0, then become separated monotonically.
    axes = (
        (moving.xmin, moving.xmax, obstacle.xmin, obstacle.xmax, direction[0]),
        (moving.ymin, moving.ymax, obstacle.ymin, obstacle.ymax, direction[1]),
        (moving.zmin, moving.zmax, obstacle.zmin, obstacle.zmax, direction[2]),
    )
    nonzero = [i for i, item in enumerate(axes) if abs(item[4]) > 1e-9]
    if len(nonzero) != 1:
        return False
    low, high, other_low, other_high, component = axes[nonzero[0]]
    if component > 0 and abs(low - other_high) <= epsilon:
        return True
    if component < 0 and abs(high - other_low) <= epsilon:
        return True
    return False


class ConservativePathChecker:
    """Continuous BREP checks plus explicitly review-only overlap policies."""

    VERSION = "path-v18-selective-conservative-proxy"

    def __init__(self, geometry_epsilon_mm: float, min_interval_mm: float, candidate_timeout_sec: float, activity=lambda _: None,
                 bolt_initial_overlap_enabled: bool = False, initial_overlap_region_enabled: bool = False,
                 initial_overlap_decrease_enabled: bool = False) -> None:
        self.epsilon = geometry_epsilon_mm
        self.min_interval = min_interval_mm
        self.timeout = candidate_timeout_sec
        self.activity = activity
        self.sweeps = OrderedDict()
        self.face_features = {}
        self.geometry_validity = {}
        self.prepared_shapes = {}
        self.pair_issue = None
        self.pair_details = []
        self.initial_overlap = False
        self.initial_volumes = {}
        self.volume_cache = OrderedDict()
        self.common_retries = []
        self.pair_results = OrderedDict()
        self.pair_bounds = None
        self.bolt_initial_overlap_enabled = bolt_initial_overlap_enabled
        self.initial_overlap_region_enabled = initial_overlap_region_enabled
        self.initial_overlap_decrease_enabled = initial_overlap_decrease_enabled
        self.fastener_axes = {}
        self.relief_shapes = OrderedDict()
        self.exception_pairs = []
        self.directional_overlap_block = False
        self.pair_cache_hits = 0
        self.pair_calculations = 0
        self.acceleration_enabled = acceleration_enabled()
        self.proxies = ProxyStore()
        self.stage_times = Counter()

    def check(
        self,
        moving_group: AssemblyGroup,
        moving_shape: TopoDS_Shape,
        obstacles: list[tuple[AssemblyGroup, TopoDS_Shape]],
        direction: Vector3,
        travel_mm: float,
        remaining_group_ids: set[str],
    ) -> PathCheckResult:
        started = time.perf_counter()
        self.stage_times.clear()
        self.pair_cache_hits = 0
        self.pair_calculations = 0
        self.initial_overlap = False
        self.directional_overlap_block = False
        self.exception_pairs = []
        d = normalize(direction)
        self.pair_details = []
        self.common_retries = []
        blockers: list[str] = []
        unknown: list[str] = []
        moving_group,moving_shape,moving_repair,moving_valid=self._prepare_group(moving_group,moving_shape)
        repairs=[moving_repair] if moving_repair and moving_repair.get("accepted") else []
        if not moving_valid:
            return PathCheckResult(group_id=moving_group.id,state_key=state_key(remaining_group_ids),direction=d,
                travel_mm=travel_mm,decision=GeometryDecision.UNKNOWN,reason_code="PATH_UNKNOWN",obstacle_ids=[],
                elapsed_sec=time.perf_counter()-started,policy_version=self.VERSION,
                evidence={"pair_diagnostics":[{"obstacle_id":moving_group.id,"decision":"UNKNOWN","role":"moving",**(moving_repair or {"code":"INPUT_GEOMETRY_INVALID"})}]})
        for obstacle_group, obstacle_shape in obstacles:
            if time.perf_counter() - started > self.timeout:
                unknown.append(obstacle_group.id)
                break
            obstacle_group,obstacle_shape,obstacle_repair,_=self._prepare_group(obstacle_group,obstacle_shape)
            swept_bounds = Bounds.union([moving_group.bounds, moving_group.bounds.translated(tuple(x*travel_mm for x in d))])
            if not swept_bounds.expanded(self.epsilon).intersects(obstacle_group.bounds):
                continue
            if obstacle_repair and obstacle_repair.get("accepted"):repairs.append(obstacle_repair)
            all_parts = self.initial_overlap_region_enabled and moving_group.geometry_valid and obstacle_group.geometry_valid
            eligible = not self.initial_overlap_region_enabled and self._fastener_pair(moving_group, moving_shape, obstacle_group)
            axial = eligible and abs(sum(x*y for x,y in zip(self.fastener_axes[hash(moving_shape)],d))) >= 1-1e-10
            decision = self._check_pair(moving_group.bounds, moving_shape, obstacle_group.bounds, obstacle_shape, d, travel_mm, started,
                                        allow_initial=all_parts or axial, directional_exception=eligible)
            if self.pair_issue:
                self.pair_details.append({"obstacle_id":obstacle_group.id,"decision":decision.value,**self.pair_issue})
            if (all_parts or axial) and self.initial_volumes.get((hash(moving_shape),hash(obstacle_shape)), 0):
                volume = self.initial_volumes[(hash(moving_shape),hash(obstacle_shape))]
                if volume > self.epsilon**3:
                    self.exception_pairs.append({"obstacle_id":obstacle_group.id,"initial_overlap_mm3":volume,
                        "moving_volume_percent":100*volume/moving_group.volume_mm3 if moving_group.volume_mm3 else None,
                        "pair_decision":decision.value,"allowed_region":"sampled-decreasing-overlap" if all_parts and self.initial_overlap_decrease_enabled else "initial-moving-solid-only"})
            if decision == GeometryDecision.BLOCKED:
                blockers.append(obstacle_group.id)
                break
            elif decision == GeometryDecision.UNKNOWN:
                unknown.append(obstacle_group.id)
        if blockers:
            reason = "BOLT_NON_AXIAL" if self.directional_overlap_block else "INITIAL_OVERLAP" if self.initial_overlap else "PATH_BLOCKED"
            status, obstacle_ids = GeometryDecision.BLOCKED, blockers
        elif unknown:
            status, reason, obstacle_ids = GeometryDecision.UNKNOWN, "PATH_UNKNOWN", unknown
        else:
            reason = ("INITIAL_REGION_ALLOWED" if self.initial_overlap_region_enabled else "FASTENER_INITIAL_OVERLAP_ALLOWED") if self.exception_pairs else "CERTIFIED_CLEAR"
            if self.exception_pairs and self.initial_overlap_region_enabled and self.initial_overlap_decrease_enabled:
                reason = "INITIAL_DECREASE_ALLOWED"
            status, obstacle_ids = GeometryDecision.PASS, []
        return PathCheckResult(
            group_id=moving_group.id,
            state_key=state_key(remaining_group_ids),
            direction=d,
            travel_mm=travel_mm,
            decision=status,
            reason_code=reason,
            obstacle_ids=obstacle_ids,
            elapsed_sec=time.perf_counter()-started,
            policy_version=self.VERSION,
            evidence={"bolt_initial_overlap_enabled":self.bolt_initial_overlap_enabled,
                      "initial_overlap_region_enabled":self.initial_overlap_region_enabled,
                      "initial_overlap_decrease_enabled":self.initial_overlap_decrease_enabled,
                      "initial_decrease_exceptions":list(self.exception_pairs) if self.initial_overlap_region_enabled and self.initial_overlap_decrease_enabled else [],
                      "initial_region_exceptions":list(self.exception_pairs) if self.initial_overlap_region_enabled and not self.initial_overlap_decrease_enabled else [],
                      "fastener_exceptions":list(self.exception_pairs) if not self.initial_overlap_region_enabled else [],
                      "pair_diagnostics":list(self.pair_details),
                      "input_repairs":repairs,
                      "common_retries":list(self.common_retries),
                      "thread_rotation_checked":False},
        )

    @_timed_stage('input_prepare')
    def _prepare_group(self,group,shape):
        key=(hash(shape),self.epsilon)
        if key not in self.prepared_shapes:
            prepared,evidence,valid=prepare(shape,self.epsilon,self.activity)
            self.prepared_shapes[key]=(prepared,evidence,valid)
        prepared,evidence,valid=self.prepared_shapes[key]
        self.geometry_validity[hash(prepared)]=valid
        if evidence and evidence.get("accepted"):
            group=replace(group,bounds=Bounds.union([group.bounds,sweep.bounds(prepared)]))
        return group,prepared,({"group_id":group.id,**evidence} if evidence else None),valid

    def _fastener_pair(self, moving_group, moving_shape, obstacle_group):
        if not self.bolt_initial_overlap_enabled or moving_group.part_type != PartType.BOLT:
            return False
        # Only classified rigid mating parts are eligible; seals, anonymous bodies,
        # other bolts, invalid geometry and arbitrary non-fastener overlaps stay strict.
        if obstacle_group.part_type not in {PartType.BODY,PartType.BLOCK,PartType.PLATE,PartType.NUT,
                PartType.BUSBAR,PartType.RELAY,PartType.COVER,PartType.HV_CONNECTOR,PartType.LV_CONNECTOR}:
            return False
        if not moving_group.geometry_valid or not obstacle_group.geometry_valid:
            return False
        key=hash(moving_shape)
        if key not in self.fastener_axes:
            evidence=[]
            explorer=TopExp_Explorer(moving_shape,TopAbs_FACE)
            while explorer.More():
                self.activity("FASTENER_AXIS")
                face=TopoDS.Face(explorer.Current())
                surface=BRepAdaptor_Surface(face,True)
                if surface.GetType()==GeomAbs_Cylinder:
                    props=GProp_GProps()
                    BRepGProp.SurfaceProperties_s(face,props)
                    axis=surface.Cylinder().Axis().Direction()
                    evidence.append((abs(float(props.Mass())),(axis.X(),axis.Y(),axis.Z())))
                explorer.Next()
            self.fastener_axes[key]=max(evidence,key=lambda item:item[0])[1] if evidence else None
        return self.fastener_axes[key] is not None

    @_timed_stage('distance')
    def _distance(self, moving: TopoDS_Shape, obstacle: TopoDS_Shape, d: Vector3, position: float) -> float | None:
        try:
            if self.pair_bounds is not None:
                a,b=self.pair_bounds
                a=a.translated(tuple(x*position for x in d))
                lower=math.sqrt(sum(max(0,lo1-hi2,lo2-hi1)**2 for lo1,hi1,lo2,hi2 in (
                    (a.xmin,a.xmax,b.xmin,b.xmax),(a.ymin,a.ymax,b.ymin,b.ymax),
                    (a.zmin,a.zmax,b.zmin,b.zmax))))
                if lower > self.epsilon:
                    return lower  # Conservative lower bound is enough for interval proof.
            self.activity("BREP_DISTANCE")
            query = BRepExtrema_DistShapeShape(translated(moving, tuple(x*position for x in d)), obstacle)
            value = float(query.Value()) if query.IsDone() else None
            return value if value is not None and math.isfinite(value) and value >= 0 else None
        except InterruptedError:
            raise
        except Exception:
            return None

    @_timed_stage('common_validation_volume')
    def _common_volume(self, moving: TopoDS_Shape, obstacle: TopoDS_Shape, d: Vector3, position: float) -> float | None:
        key=(hash(moving),hash(obstacle),tuple(x*position for x in d))
        if key in self.volume_cache:
            saved_moving,saved_obstacle,value=self.volume_cache[key]
            # Hold the shape handles and compare full identity. A bare hash may
            # be reused after an evicted swept shape is freed by OCCT.
            if saved_moving.IsEqual(moving) and saved_obstacle.IsEqual(obstacle):
                self.activity('BREP_COMMON_CACHE_HIT')
                self.volume_cache.move_to_end(key)
                return value
        try:
            self.activity("BREP_COMMON")
            common = _boolean(BRepAlgoAPI_Common,translated(moving, tuple(x*position for x in d)) if position else moving,obstacle)
            if not common.IsDone():
                return None
            self.activity("BREP_COMMON_VALIDATION")
            result=common.Shape()
            if not BRepCheck_Analyzer(result).IsValid():
                # Retry in reverse argument order, then apply the same bounded
                # parameter repair policy as inputs. No tolerance relaxation or
                # unvalidated mass from an invalid result can establish PASS.
                self.activity('BREP_COMMON_RETRY')
                retry=_boolean(BRepAlgoAPI_Common,obstacle,translated(moving,tuple(x*position for x in d)) if position else moving)
                if retry.IsDone() and BRepCheck_Analyzer(retry.Shape(),True).IsValid():
                    result=retry.Shape()
                    self.common_retries.append({'position_mm':position,'method':'REVERSE_ARGUMENTS','accepted':True})
                else:
                    repaired,evidence,valid=prepare(result,self.epsilon,self.activity)
                    self.common_retries.append({'position_mm':position,'method':'BOUNDED_PARAMETER_REPAIR','accepted':valid,'details':evidence})
                    if not valid:return None
                    result=repaired
            props = GProp_GProps()
            self.activity("BREP_VOLUME")
            BRepGProp.VolumeProperties_s(result, props)
            value = abs(float(props.Mass()))
            if math.isfinite(value):
                self.volume_cache[key]=(moving,obstacle,value)
                if len(self.volume_cache)>8192:self.volume_cache.popitem(last=False)
                return value
            return None
        except InterruptedError:
            raise
        except Exception:
            return None

    def _check_pair(self, moving_bounds: Bounds, moving: TopoDS_Shape, obstacle_bounds: Bounds, obstacle: TopoDS_Shape, d: Vector3, travel: float, started: float,
                    allow_initial=False, directional_exception=False) -> GeometryDecision:
        # Remaining groups do not change either pair's geometry. Reuse only the
        # identical motion and policy; the caller still checks EVERY remaining
        # obstacle, so removing an UNKNOWN blocker can unlock a later state.
        key=(hash(moving),hash(obstacle),moving_bounds,obstacle_bounds,tuple(d),travel,
             self.epsilon,self.min_interval,allow_initial,directional_exception,self.initial_overlap_region_enabled,self.initial_overlap_decrease_enabled)
        if key in self.pair_results:
            self.pair_cache_hits += 1
            decision,self.initial_overlap,self.directional_overlap_block,self.pair_issue=self.pair_results[key]
            self.pair_results.move_to_end(key)
            return decision
        self.pair_issue=None
        self.pair_calculations += 1
        decision=self._check_pair_uncached(moving_bounds,moving,obstacle_bounds,obstacle,d,travel,started,
                                           allow_initial,directional_exception)
        # Never memoize a candidate's time-budget exhaustion. Native timeout or
        # cancellation raises outside this call and also cannot enter the cache.
        if time.perf_counter()-started < self.timeout:
            self.pair_results[key]=(decision,self.initial_overlap,self.directional_overlap_block,self.pair_issue)
            if len(self.pair_results)>4096:
                self.pair_results.popitem(last=False)
        return decision

    def _check_pair_uncached(self, moving_bounds, moving, obstacle_bounds, obstacle, d, travel, started,
                             allow_initial=False, directional_exception=False):
        self.pair_bounds=(moving_bounds,obstacle_bounds)
        for role,shape in (("moving",moving),("obstacle",obstacle)):
            if hash(shape) not in self.geometry_validity:
                self.activity("BREP_INPUT_VALIDATION")
                self.geometry_validity[hash(shape)]=BRepCheck_Analyzer(shape,True).IsValid()
            if not self.geometry_validity[hash(shape)]:
                self.pair_issue={"code":"INPUT_GEOMETRY_INVALID","role":role}
                return GeometryDecision.UNKNOWN
        if moving_bounds.expanded(self.epsilon).intersects(obstacle_bounds):
            key=(hash(moving),hash(obstacle))
            if key not in self.initial_volumes:
                self.initial_volumes[key]=self._common_volume(moving, obstacle, d, 0.0)
            initial_volume = self.initial_volumes[key]
            if initial_volume is None:
                self.pair_issue={"code":"INITIAL_BOOLEAN_FAILED"}
                return GeometryDecision.UNKNOWN
            if initial_volume > self.epsilon ** 3:
                if allow_initial:
                    if self.initial_overlap_region_enabled and self.initial_overlap_decrease_enabled:
                        return self._decreasing_overlap_extraction(moving,obstacle_bounds,obstacle,d,travel,started,initial_volume)
                    return self._initial_region_extraction(moving,obstacle_bounds,obstacle,d,travel,started)
                self.initial_overlap = True
                self.directional_overlap_block = directional_exception
                return GeometryDecision.BLOCKED
            # Every point in a translated solid's swept volume either starts inside
            # that solid or crosses one of its boundary faces. Extruding ALL faces
            # therefore covers the full continuous path, including sliding contact.
            return self._swept_check(moving, obstacle_bounds, obstacle, d, travel, started)
        # A midpoint overlap is a useful early rejection, but never a PASS proof.
        overlap=self._common_volume(moving,obstacle,d,travel/2)
        if overlap is None:
            return GeometryDecision.UNKNOWN
        if overlap > self.epsilon ** 3:
            return GeometryDecision.BLOCKED
        return self._swept_check(moving,obstacle_bounds,obstacle,d,travel,started)

    def _decreasing_overlap_extraction(self,moving,obstacle_bounds,obstacle,d,travel,started,initial_volume):
        """Review-only sampled nonincrease, followed by a continuous clear tail.

        Not a continuous monotonicity proof: local collision in an initially
        overlapping pair can be masked by loss elsewhere. Keep this limitation
        in evidence and downstream warnings; other pairs retain strict sweeps.
        """
        tolerance=max(self.epsilon**3, initial_volume*1e-6)
        samples=[{"position_mm":0.0,"overlap_mm3":initial_volume}]
        evidence={"code":"INITIAL_DECREASE_SAMPLED", "initial_overlap_mm3":initial_volume,
                  "volume_tolerance_mm3":tolerance,"max_sample_step_mm":0.5,
                  "continuous_monotonicity_proven":False,"same_pair_local_collision_excluded":False,
                  "samples":samples}
        low_water=initial_volume
        position=0.0
        for index in range(256):
            if time.perf_counter()-started>self.timeout:
                self.pair_issue={**evidence,"code":"CANDIDATE_TIME_BUDGET"}
                return GeometryDecision.UNKNOWN
            position=min(travel,(.01,.05,.1,.25,.5)[index] if index<5 else position+.5)
            volume=self._common_volume(moving,obstacle,d,position)
            samples.append({"position_mm":position,"overlap_mm3":volume})
            if volume is None:
                self.pair_issue={**evidence,"code":"DECREASE_BOOLEAN_FAILED"}
                return GeometryDecision.UNKNOWN
            if volume>low_water+tolerance:
                self.pair_issue={**evidence,"code":"OVERLAP_REINCREASE","minimum_previous_mm3":low_water,
                                 "position_mm":position,"overlap_mm3":volume}
                return GeometryDecision.BLOCKED
            low_water=min(low_water,volume)  # Prevent accumulation of tolerated rises.
            if volume<=self.epsilon**3:
                # Zero volume may still mean sliding surface contact. Do not
                # repeatedly wait for a positive intermediate gap: the existing
                # full sweep proves nonpenetration, and checks endpoint clearance.
                original_bounds=self.pair_bounds
                shifted=translated(moving,tuple(v*position for v in d))
                try:
                    self.pair_bounds=(original_bounds[0].translated(tuple(v*position for v in d)),obstacle_bounds)
                    if position<travel:
                        tail=self._swept_check(shifted,obstacle_bounds,obstacle,d,travel-position,started)
                    else:
                        distance=self._distance(shifted,obstacle,d,0)
                        tail=GeometryDecision.PASS if distance is not None and distance>self.epsilon else GeometryDecision.UNKNOWN
                    tail_detail=self.pair_issue
                finally:
                    self.pair_bounds=original_bounds
                self.pair_issue={**evidence,"code":"INITIAL_DECREASE_SAMPLED" if tail==GeometryDecision.PASS else "DECREASE_TAIL_"+tail.value,
                                 "overlap_cleared_at_mm":position,"continuous_tail_decision":tail.value,
                                 "tail_diagnostic":tail_detail}
                return tail
            if position>=travel:
                self.pair_issue={**evidence,"code":"ORIGINAL_ENDPOINT_NOT_SEPARATED"}
                return GeometryDecision.UNKNOWN
        self.pair_issue={**evidence,"code":"DECREASE_SAMPLE_BUDGET"}
        return GeometryDecision.UNKNOWN

    def _initial_region_extraction(self,moving,obstacle_bounds,obstacle,d,travel,started):
        # O' = O \ M(0) removes ONLY the initial interference region from this
        # pair's private calculation shape. Proving the whole sweep disjoint from
        # O' forbids any newly occupied obstacle volume, even in the same part.
        # Source geometry is unchanged and the endpoint is checked against O.
        key=(hash(moving),hash(obstacle),self.initial_overlap_region_enabled)
        try:
            if key not in self.relief_shapes:
                self.activity("INITIAL_REGION_CUT")
                cut=_boolean(BRepAlgoAPI_Cut,obstacle,moving)
                if not cut.IsDone():
                    self.pair_issue={"code":"INITIAL_REGION_CUT_FAILED"}
                    return GeometryDecision.UNKNOWN
                relieved=cut.Shape()
                self.activity("INITIAL_REGION_VALIDATION")
                if relieved.IsNull() or not BRepCheck_Analyzer(relieved).IsValid():
                    self.pair_issue={"code":"INITIAL_REGION_CUT_INVALID"}
                    return GeometryDecision.UNKNOWN
                # Legacy bolt policy excludes containment. Under the all-part
                # policy an empty valid remainder has no new obstacle volume.
                if not TopExp_Explorer(relieved,TopAbs_SOLID).More() and not self.initial_overlap_region_enabled:
                    return GeometryDecision.BLOCKED
                self.relief_shapes[key]=(relieved,sweep.bounds(relieved) if TopExp_Explorer(relieved,TopAbs_SOLID).More() else None)
                if len(self.relief_shapes)>64:self.relief_shapes.popitem(last=False)
            relieved,reduced_bounds=self.relief_shapes[key]
            self.relief_shapes.move_to_end(key)
            decision=self._swept_check(moving,reduced_bounds,relieved,d,travel,started) if reduced_bounds else GeometryDecision.PASS
            if decision != GeometryDecision.PASS:
                return decision
            distance=self._distance(moving,obstacle,d,travel)
            if distance is None or distance<=self.epsilon:self.pair_issue={"code":"ORIGINAL_ENDPOINT_NOT_SEPARATED"}
            return GeometryDecision.PASS if distance is not None and distance>self.epsilon else GeometryDecision.UNKNOWN
        except InterruptedError:
            raise
        except Exception as exc:
            self.pair_issue={"code":"INITIAL_REGION_EXCEPTION","error":f"{type(exc).__name__}: {exc}"}
            return GeometryDecision.UNKNOWN

    @_timed_stage('swept_check_inclusive')
    def _swept_check(self, moving, obstacle_bounds, obstacle, d, travel, started):
        try:
            if hash(moving) not in self.face_features:
                faces=[]
                explorer = TopExp_Explorer(moving, TopAbs_FACE)
                while explorer.More():
                    face=TopoDS.Face(explorer.Current()); adaptor=BRepAdaptor_Surface(face,True)
                    faces.append((face,sweep.bounds(face),adaptor))
                    explorer.Next()
                # An unrelated bad curved face must not hide a proven collision
                # on a planar face, nor invalidate a disjoint face-sweep box.
                self.face_features[hash(moving)]=sorted(faces,key=lambda f:f[2].GetType()!=GeomAbs_Plane)
            uncertain=[]
            for face,face_bounds,adaptor in self.face_features[hash(moving)]:
                if time.perf_counter()-started > self.timeout:
                    self.pair_issue={"code":"CANDIDATE_TIME_BUDGET"}
                    return GeometryDecision.UNKNOWN
                if not sweep.swept_bounds(face_bounds,d,travel).expanded(self.epsilon).intersects(obstacle_bounds):
                    continue
                if adaptor.GetType()==GeomAbs_Plane:
                    normal=adaptor.Plane().Axis().Direction()
                    if abs(normal.X()*d[0]+normal.Y()*d[1]+normal.Z()*d[2])<=1e-12:continue
                elif adaptor.GetType()==GeomAbs_Cylinder:
                    axis=adaptor.Cylinder().Axis().Direction()
                    cross=(axis.Y()*d[2]-axis.Z()*d[1],axis.Z()*d[0]-axis.X()*d[2],axis.X()*d[1]-axis.Y()*d[0])
                    if sum(v*v for v in cross)<=1e-24:continue
                # A boundary-free outside box proves the WHOLE continuous face
                # sweep empty. No path samples, mesh decimation, or tolerance
                # relaxation is involved. Ambiguous boxes use the original path.
                if self.acceleration_enabled and self.proxies.certifies_empty(
                        obstacle, sweep.swept_bounds(face_bounds,d,travel), self.epsilon, self.activity):
                    self.activity('PROXY_FACE_SWEEP_CLEAR')
                    continue
                key=(hash(face),tuple(d),travel)
                if key not in self.sweeps:
                    self.activity('SWEEP_CACHE_MISS')
                    sweep_started=time.perf_counter()
                    self.sweeps[key]=sweep.enclosures(face,adaptor,d,travel,self.activity)
                    self.stage_times['sweep_construction']+=time.perf_counter()-sweep_started
                    # Retain a complex part's faces across obstacle pairs, but
                    # bound both face entries and UV enclosure record count.
                    limit=2048 if self.acceleration_enabled else 256
                    while (len(self.sweeps)>limit or
                           (self.acceleration_enabled and sum(len(v or ()) for v in self.sweeps.values())>4096)):
                        self.sweeps.popitem(last=False)
                else:self.activity('SWEEP_CACHE_HIT')
                records=self.sweeps[key]; self.sweeps.move_to_end(key)
                if records is None:
                    uncertain.append({"code":"SWEEP_CONSTRUCTION_FAILED","surface":str(adaptor.GetType())});continue
                for bounds,solid,exact in records:
                    if not bounds.expanded(self.epsilon).intersects(obstacle_bounds):continue
                    if self.acceleration_enabled and self.proxies.certifies_empty(obstacle,bounds,self.epsilon,self.activity):
                        self.activity('PROXY_ENCLOSURE_CLEAR')
                        continue
                    overlap=self._common_volume(solid,obstacle,d,0)
                    if overlap is None:
                        uncertain.append({"code":"SWEEP_BOOLEAN_FAILED","surface":str(adaptor.GetType())})
                    elif overlap>self.epsilon**3:
                        if exact:return GeometryDecision.BLOCKED
                        uncertain.append({"code":"CONSERVATIVE_PATCH_INTERSECTION","surface":str(adaptor.GetType())})
            if uncertain:
                # Point probes may establish BLOCKED, never PASS. They avoid
                # reporting UNKNOWN for an obvious collision behind a bad sweep.
                for fraction in (.01,.1,.25,.5,.75):
                    if time.perf_counter()-started>self.timeout:break
                    position=travel*fraction
                    if self.pair_bounds and not self.pair_bounds[0].translated(tuple(v*position for v in d)).intersects(obstacle_bounds):continue
                    overlap=self._common_volume(moving,obstacle,d,position)
                    if overlap is not None and overlap>self.epsilon**3:
                        self.pair_issue={"code":"EXACT_COLLISION_WITNESS","position_mm":position,"overlap_mm3":overlap}
                        return GeometryDecision.BLOCKED
                if self.pair_bounds and not self.pair_bounds[0].expanded(self.epsilon).intersects(obstacle_bounds):
                    # A continuous 1-Lipschitz distance bound, not point sampling.
                    # Keep this fallback bounded; touching starts cannot be
                    # certified by positive-distance intervals and are skipped.
                    interval=self._certify_interval(moving,obstacle,d,0,travel,started,
                        deadline=min(started+self.timeout,time.perf_counter()+5))
                    if interval!=GeometryDecision.UNKNOWN:
                        self.pair_issue={"code":"CONTINUOUS_DISTANCE_PROOF" if interval==GeometryDecision.PASS else "EXACT_INTERVAL_COLLISION"}
                        return interval
                self.pair_issue={"code":"SWEEP_UNRESOLVED","details":uncertain[:12]}
                return GeometryDecision.UNKNOWN
            end_distance = self._distance(moving, obstacle, d, travel)
            if end_distance is None or end_distance <= self.epsilon:
                self.pair_issue={"code":"ENDPOINT_NOT_SEPARATED"}
                return GeometryDecision.UNKNOWN
            return GeometryDecision.PASS
        except InterruptedError:
            raise
        except Exception as exc:
            self.pair_issue={"code":"SWEEP_EXCEPTION","error":f"{type(exc).__name__}: {exc}"}
            return GeometryDecision.UNKNOWN

    def _certify_interval(self, moving: TopoDS_Shape, obstacle: TopoDS_Shape, d: Vector3, start: float, end: float, started: float, deadline=None) -> GeometryDecision:
        if time.perf_counter() - started > self.timeout or (deadline is not None and time.perf_counter()>=deadline):
            return GeometryDecision.UNKNOWN
        midpoint = (start + end) / 2
        half = (end - start) / 2
        distance = self._distance(moving, obstacle, d, midpoint)
        if distance is None:
            return GeometryDecision.UNKNOWN
        # Shape distance under a unit-speed rigid translation is 1-Lipschitz.
        if distance > half + self.epsilon:
            return GeometryDecision.PASS
        overlap = self._common_volume(moving, obstacle, d, midpoint)
        if overlap is None:
            return GeometryDecision.UNKNOWN
        if overlap > self.epsilon ** 3:
            return GeometryDecision.BLOCKED
        if end - start <= self.min_interval:
            return GeometryDecision.UNKNOWN
        left = self._certify_interval(moving, obstacle, d, start, midpoint, started,deadline)
        if left == GeometryDecision.BLOCKED:
            return left
        right = self._certify_interval(moving, obstacle, d, midpoint, end, started,deadline)
        if right == GeometryDecision.BLOCKED:
            return right
        return GeometryDecision.PASS if left == right == GeometryDecision.PASS else GeometryDecision.UNKNOWN

