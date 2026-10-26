from __future__ import annotations

import math
from collections import Counter, OrderedDict

from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepGProp import BRepGProp
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Plane
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.TopAbs import TopAbs_SOLID, TopAbs_VERTEX, TopAbs_FACE, TopAbs_IN, TopAbs_ON, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box
from pa2.domain.models import Bounds


def _bounds(shape):
    # Conservative control-polygon bounds are sufficient for broad phase.
    # AddOptimal can spend minutes solving spline extrema merely to prune pairs.
    box=Bnd_Box()
    BRepBndLib.Add_s(shape,box,False)
    low,high=box.CornerMin(),box.CornerMax()
    return Bounds(low.X(),low.Y(),low.Z(),high.X(),high.Y(),high.Z())

from .directions import direction_candidates
from .path_check import ConservativePathChecker, _boolean
from .shapes import translated
from .brep_io import read_shape


class CadDispatcher:
    def __init__(self, files, activity):
        self.files = files
        self.activity = activity
        self.shapes = {}
        self.solids = {}
        self.faces = {}
        self.checkers = OrderedDict()
        self.initial_volumes = {}
        self.volume_cache = OrderedDict()
        self.pair_results = OrderedDict()
        self.sweep_cache = OrderedDict()
        self.relief_cache = OrderedDict()
        self.path_faces = {}
        self.path_validity = {}
        self.prepared_paths = {}
        self.support_faces = {}
        from .conservative_proxy import ProxyStore
        self.path_proxies = ProxyStore()

    def planar_faces(self, identifier):
        if identifier not in self.support_faces:
            faces=[]
            for bounds,raw in self.face_list(self.shape(identifier)):
                self.activity("SUPPORT_PLANE_FEATURES")
                face=TopoDS.Face(raw)
                surface=BRepAdaptor_Surface(face,True)
                if surface.GetType()!=GeomAbs_Plane:
                    continue
                plane=surface.Plane()
                direction=plane.Axis().Direction()
                sign=-1 if face.Orientation()==TopAbs_REVERSED else 1
                normal=(sign*direction.X(),sign*direction.Y(),sign*direction.Z())
                if abs(normal[2])<1e-6:
                    continue
                point=plane.Location()
                faces.append((bounds,face,normal,(point.X(),point.Y(),point.Z())))
            self.support_faces[identifier]=faces
        return self.support_faces[identifier]

    def supports(self,upper,lower,gap,epsilon):
        for ub,uf,un,up in self.planar_faces(upper):
            if un[2]>=-1e-6:
                continue
            for lb,lf,ln,lp in self.planar_faces(lower):
                if ln[2]<=1e-6 or sum(x*y for x,y in zip(un,ln)) > -1+1e-8:
                    continue
                separation=sum(ln[i]*(up[i]-lp[i]) for i in range(3))
                if separation < -epsilon or separation > gap:
                    continue
                if self.bounds_distance(ub,lb) > gap:
                    continue
                self.activity("SUPPORT_FACE_COMMON")
                common=_boolean(BRepAlgoAPI_Common,translated(uf,tuple(-separation*x for x in ln)),lf)
                if not common.IsDone():
                    continue
                self.activity("SUPPORT_FACE_VALIDATION")
                if not BRepCheck_Analyzer(common.Shape()).IsValid():
                    continue
                props=GProp_GProps()
                self.activity("SUPPORT_FACE_AREA")
                BRepGProp.SurfaceProperties_s(common.Shape(),props)
                if abs(float(props.Mass()))>epsilon**2:
                    return True
        return False

    def contact_witness(self, a, b, tolerance):
        # An exact BREP vertex classified inside/on the other solid establishes
        # contact without solving every face-face extremum. Failure to find one
        # never establishes separation: the exact distance solver is the fallback.
        for source, target in ((a,b),(b,a)):
            self.activity("BREP_CONTACT_CLASSIFIER")
            classifier=BRepClass3d_SolidClassifier(target)
            bounds=_bounds(target).expanded(tolerance)
            explorer=TopExp_Explorer(source,TopAbs_VERTEX)
            seen=set()
            checked=0
            while explorer.More() and checked < 128:
                point=BRep_Tool.Pnt_s(TopoDS.Vertex(explorer.Current()))
                coordinates=(point.X(),point.Y(),point.Z())
                if (coordinates not in seen and bounds.xmin<=point.X()<=bounds.xmax
                        and bounds.ymin<=point.Y()<=bounds.ymax and bounds.zmin<=point.Z()<=bounds.zmax):
                    seen.add(coordinates)
                    self.activity("BREP_CONTACT_POINT")
                    classifier.Perform(point,tolerance)
                    checked+=1
                    if classifier.State() in (TopAbs_IN,TopAbs_ON):
                        return True
                explorer.Next()
        return False

    @staticmethod
    def bounds_distance(a,b):
        return math.sqrt(sum(max(0, lo1-hi2, lo2-hi1)**2 for lo1,hi1,lo2,hi2 in (
            (a.xmin,a.xmax,b.xmin,b.xmax),(a.ymin,a.ymax,b.ymin,b.ymax),
            (a.zmin,a.zmax,b.zmin,b.zmax))))

    def face_list(self,shape):
        key=hash(shape)
        if key not in self.faces:
            faces=[]
            explorer=TopExp_Explorer(shape,TopAbs_FACE)
            while explorer.More():
                self.activity("BREP_FACE_BOUNDS")
                face=explorer.Current()
                faces.append((_bounds(face),face))
                explorer.Next()
            self.faces[key]=faces
        return self.faces[key]

    def threshold_distance(self,a,b,threshold):
        if self.contact_witness(a,b,min(1e-7,threshold/10)):
            return 0.0
        # Connected solid containment is decided by a vertex classification above.
        # Vertex-free topology uses the general solid solver instead.
        if not TopExp_Explorer(a,TopAbs_VERTEX).More() or not TopExp_Explorer(b,TopAbs_VERTEX).More():
            self.activity("BREP_DISTANCE")
            query=BRepExtrema_DistShapeShape(a,b)
            if not query.IsDone():
                raise ValueError("BREP 거리 판정 실패")
            return float(query.Value())
        candidates=[]
        for ba,fa in self.face_list(a):
            for bb,fb in self.face_list(b):
                lower=self.bounds_distance(ba,bb)
                if lower<=threshold:
                    candidates.append((lower,fa,fb))
        best=math.inf
        for lower,fa,fb in sorted(candidates,key=lambda row:row[0]):
            self.activity("BREP_FACE_DISTANCE")
            query=BRepExtrema_DistShapeShape(fa,fb)
            if not query.IsDone():
                raise ValueError("BREP 면 거리 판정 실패")
            value=float(query.Value())
            if not math.isfinite(value) or value<0:
                raise ValueError("유효하지 않은 BREP 거리")
            best=min(best,value)
            if best<=threshold:
                return best
        # Only the threshold decision is needed when there is no contact edge.
        return best if math.isfinite(best) else math.nextafter(threshold,math.inf)

    def shape(self, identifier):
        if identifier not in self.shapes:
            self.activity("BREP_READ")
            shape = read_shape(self.files[identifier])
            self.shapes[identifier] = shape
        return self.shapes[identifier]

    def execute(self, operation, payload):
        if operation == 'direction_policy':
            from .direction_policy import policy_hint
            return policy_hint(self, **payload)
        if operation == "overlap":
            a,b=payload
            checker=ConservativePathChecker(.001,.001,120,activity=self.activity)
            return checker._common_volume(self.shape(a),self.shape(b),(1,0,0),0)
        if operation == "support":
            a,b=payload["groups"]
            edges=[]
            for upper,lower in ((a,b),(b,a)):
                if self.supports(upper,lower,payload["gap"],payload["epsilon"]):
                    edges.append((upper,lower))
            return edges
        if operation == "distance":
            identifiers = payload["groups"] if isinstance(payload, dict) else payload
            threshold = payload.get("gap", math.inf) if isinstance(payload, dict) else math.inf
            for identifier in identifiers:
                if identifier not in self.solids:
                    shape = self.shape(identifier)
                    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
                    pieces = []
                    while explorer.More():
                        self.activity("BREP_SOLID_BOUNDS")
                        solid = explorer.Current()
                        pieces.append((_bounds(solid),solid))
                        explorer.Next()
                    self.solids[identifier] = pieces or [(_bounds(shape),shape)]
            pairs = []
            for a_bounds,a in self.solids[identifiers[0]]:
                for b_bounds,b in self.solids[identifiers[1]]:
                    lower = self.bounds_distance(a_bounds,b_bounds)
                    pairs.append((lower,a,b))
            best = math.inf
            for lower,a,b in sorted(pairs,key=lambda item:item[0]):
                if lower > threshold or lower >= best:
                    # All omitted solid pairs have a certified distance above gap.
                    break
                if math.isfinite(threshold):
                    value=self.threshold_distance(a,b,threshold)
                else:
                    self.activity("BREP_DISTANCE")
                    query = BRepExtrema_DistShapeShape(a,b)
                    if not query.IsDone():
                        raise ValueError("BREP 거리 판정 실패")
                    value=float(query.Value())
                if not math.isfinite(value) or value < 0:
                    raise ValueError("유효하지 않은 BREP 거리")
                best=min(best,value)
                if best <= threshold and math.isfinite(threshold):
                    return best  # Exact solid-pair contact witness; one edge per group pair.
            return best if math.isfinite(best) else min(item[0] for item in pairs)
        if operation == "directions":
            shape = self.shape(payload["group_id"])
            self.activity("DIRECTION_FEATURES")
            return direction_candidates(shape, payload["max_directions"], payload["merge_angle_deg"])
        if operation == "path":
            from .boolean_options import configure
            configure(payload.get('cad_boolean_threads',1))
            moving = payload["moving"]
            moving_shape = self.shape(moving.id)
            obstacles = [(group, self.shape(group.id)) for group in payload["obstacles"]]
            key = (moving.id, tuple(payload["direction"]), payload["travel"], payload["epsilon"], payload["min_interval"], payload.get("bolt_initial_overlap_enabled",False), payload.get("initial_overlap_region_enabled",False), payload.get("initial_overlap_decrease_enabled",False))
            checker = self.checkers.get(key)
            if checker is None:
                checker = ConservativePathChecker(payload["epsilon"], payload["min_interval"], payload["timeout"], activity=self.activity,
                    bolt_initial_overlap_enabled=payload.get("bolt_initial_overlap_enabled",False),
                    initial_overlap_region_enabled=payload.get("initial_overlap_region_enabled",False),
                    initial_overlap_decrease_enabled=payload.get("initial_overlap_decrease_enabled",False))
                checker.initial_volumes = self.initial_volumes
                checker.volume_cache = self.volume_cache
                checker.pair_results = self.pair_results
                checker.sweeps = self.sweep_cache
                checker.relief_shapes = self.relief_cache
                checker.face_features = self.path_faces
                checker.geometry_validity = self.path_validity
                checker.prepared_shapes = self.prepared_paths
                checker.proxies = self.path_proxies
                self.checkers[key] = checker
                # Bound cached swept BREP memory across backtracking.
                if len(self.checkers) > 4:
                    self.checkers.popitem(last=False)
            activities = Counter()
            def counted_activity(stage):
                activities[stage] += 1
                self.activity(stage)
            checker.activity = counted_activity
            result = checker.check(moving, moving_shape, obstacles, payload["direction"], payload["travel"], payload["remaining"])
            result.evidence["calculation_metrics"] = {
                "pair_calculations": checker.pair_calculations,
                "pair_cache_hits": checker.pair_cache_hits,
                "activity_counts": dict(activities),
                "timing_seconds_inclusive": dict(checker.stage_times),
                "spatial_proxy": {"version": checker.proxies.VERSION,
                                  "enabled": checker.acceleration_enabled,
                                  "cumulative_stats": dict(checker.proxies.stats),
                                  "profiles": list(checker.proxies.profiles)},
            }
            return result
        raise ValueError(f"알 수 없는 CAD 작업: {operation}")
