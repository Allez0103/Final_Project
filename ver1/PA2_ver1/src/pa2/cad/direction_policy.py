"""Geometry hints only; no hint establishes collision clearance."""
import math
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
from OCP.TopAbs import TopAbs_REVERSED
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Ax1, gp_Dir
from .path_check import _boolean
from .shapes import translated
from .conservative_proxy import acceleration_enabled


def _fastener_hint(dispatcher, gid, faces, epsilon, kind):
    """Read analytic face properties once. No contact, Boolean or path queries."""
    cache = getattr(dispatcher, 'fastener_direction_hints', None)
    if cache is None:
        cache = dispatcher.fastener_direction_hints = {}
    key = (gid, kind)
    if key in cache:
        return dict(cache[key])
    cylinders, features = [], []
    for _, raw in faces:
        face = TopoDS.Face(raw)
        surface = BRepAdaptor_Surface(face, True)
        if surface.GetType() not in (GeomAbs_Cylinder, GeomAbs_Plane):
            continue
        dispatcher.activity('FASTENER_FACE_PROPERTIES')
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        if surface.GetType() == GeomAbs_Cylinder:
            cylinder = surface.Cylinder()
            d = cylinder.Axis().Direction()
            length = abs(surface.LastVParameter()-surface.FirstVParameter())
            if math.isfinite(length) and length > epsilon:
                cylinders.append((length, abs(props.Mass()), cylinder.Radius(),
                                  (d.X(), d.Y(), d.Z()), props.CentreOfMass()))
        features.append((surface, props))
    hint = {'axis': None, 'method': 'exposure_no_axis', 'head_direction': None}
    if cylinders:
        # The long shank, rather than a large washer/head cylinder, defines the axis.
        length, _, radius, axis, center = max(cylinders, key=lambda x:(x[0], x[1]))
        hint.update(axis=axis, method='longest_cylinder_axis',
                    shaft_center=(center.X(), center.Y(), center.Z()),
                    shaft_radius_mm=radius, shaft_length_mm=length)
        if kind != 'NUT':
            rotation_axis = gp_Ax1(center, gp_Dir(*axis))
            weighted, weight, absolute = 0., 0., 0.
            for surface, props in features:
                if surface.GetType() == GeomAbs_Cylinder:
                    d = surface.Cylinder().Axis().Direction()
                    if abs(sum(a*b for a,b in zip(axis,(d.X(),d.Y(),d.Z())))) < 1-1e-6:
                        continue
                    if surface.Cylinder().Radius() <= radius*1.15:
                        continue
                else:
                    d = surface.Plane().Axis().Direction()
                    if abs(sum(a*b for a,b in zip(axis,(d.X(),d.Y(),d.Z())))) < 1-1e-6:
                        continue
                # A shank end disk has mean squared radius r²/2. Wider axial
                # faces and coaxial head cylinders provide the head-side vote.
                area = abs(float(props.Mass()))
                excess = float(props.MomentOfInertia(rotation_axis))-.65*radius**2*area
                if excess <= epsilon**4:
                    continue
                point = props.CentreOfMass()
                offset = sum(a*b for a,b in zip(axis,
                    (point.X()-center.X(),point.Y()-center.Y(),point.Z()-center.Z())))
                weighted += excess*offset
                absolute += excess*abs(offset)
                weight += excess
            if (weight and abs(weighted)/weight > max(epsilon, .05*length)
                    and abs(weighted) > .7*absolute):
                sign = 1 if weighted > 0 else -1
                hint.update(head_direction=tuple(sign*x for x in axis),
                            head_center=tuple(a+weighted/weight*b for a,b in zip(
                                hint['shaft_center'],axis)), head_method='wide_axial_faces')
    cache[key] = dict(hint)
    return hint


def policy_hint(dispatcher, gid, neighbors, epsilon, gap, fastener=False, fastener_kind=None):
    faces = dispatcher.face_list(dispatcher.shape(gid))
    if fastener:
        return _fastener_hint(dispatcher, gid, faces, epsilon, fastener_kind)
    # Volume checks are cached in the worker and are separate from path counts.
    for other in neighbors:
        a, b = dispatcher.shape(gid), dispatcher.shape(other)
        key = (hash(a), hash(b))
        cache = getattr(dispatcher, 'direction_overlaps', None)
        if cache is None:
            cache = dispatcher.direction_overlaps = {}
        if key not in cache:
            dispatcher.activity('DIRECTION_INITIAL_COMMON')
            common = _boolean(BRepAlgoAPI_Common, a, b)
            if not common.IsDone():
                return {'method': 'exposure_overlap_unresolved'}
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(common.Shape(), props)
            cache[key] = abs(float(props.Mass()))
        if cache[key] > epsilon**3:
            return {'method': 'exposure_initial_overlap', 'overlap_with': other}
    def planes(identifier):
        cache = getattr(dispatcher, 'direction_planes', None)
        if cache is None:
            cache = dispatcher.direction_planes = {}
        if acceleration_enabled() and identifier in cache:
            return cache[identifier]
        result=[]
        for bounds, raw in dispatcher.face_list(dispatcher.shape(identifier)):
            face=TopoDS.Face(raw); surface=BRepAdaptor_Surface(face,True)
            if surface.GetType()!=GeomAbs_Plane:continue
            plane=surface.Plane(); d=plane.Axis().Direction()
            sign=-1 if face.Orientation()==TopAbs_REVERSED else 1
            result.append((bounds,face,tuple(sign*x for x in (d.X(),d.Y(),d.Z())),plane.Location()))
        if acceleration_enabled():cache[identifier]=result
        return result
    largest = (0., None, None)
    pair_cache = getattr(dispatcher, 'direction_contact_pairs', None)
    if pair_cache is None:
        pair_cache = dispatcher.direction_contact_pairs = {}
    for other in neighbors:
        key=(gid,other,epsilon,gap)
        if acceleration_enabled() and key in pair_cache:
            dispatcher.activity('DIRECTION_CONTACT_PAIR_CACHE_HIT')
            candidate=pair_cache[key]
            if candidate[0]>largest[0]:largest=candidate
            continue
        pair_largest=(0., None, None)
        for ab, af, an, ap in planes(gid):
            for bb, bf, bn, bp in planes(other):
                if dispatcher.bounds_distance(ab,bb)>gap:continue
                if sum(x*y for x,y in zip(an,bn)) > -1+1e-8:continue
                separation=sum(x*y for x,y in zip(an,(bp.X()-ap.X(),bp.Y()-ap.Y(),bp.Z()-ap.Z())))
                if abs(separation)>gap:continue
                dispatcher.activity('DIRECTION_CONTACT_AREA')
                common=_boolean(BRepAlgoAPI_Common,translated(af,tuple(separation*x for x in an)),bf)
                if not common.IsDone():continue
                props=GProp_GProps(); BRepGProp.SurfaceProperties_s(common.Shape(),props)
                area=abs(float(props.Mass()))
                if area>pair_largest[0]:pair_largest=(area,tuple(-x for x in an),other)
        if acceleration_enabled():pair_cache[key]=pair_largest
        if pair_largest[0]>largest[0]:largest=pair_largest
    area,normal,other=largest
    return {'method':'largest_planar_contact' if normal else 'exposure_no_planar_contact',
            'normal':normal,'area_mm2':area,'contact_with':other}
