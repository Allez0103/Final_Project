from __future__ import annotations

import math
from functools import lru_cache
from dataclasses import dataclass, field

from pa2.domain.models import Bounds, Plan, Vector3, normalize
from pa2.settings.config import AppSettings


@dataclass(frozen=True, slots=True)
class CameraPose:
    view_direction: Vector3
    mode: str
    view_up: Vector3 | None = None


@dataclass(frozen=True, slots=True)
class StepSegment:
    step_index: int
    camera_start: float
    camera_end: float
    highlight_end: float
    move_end: float


@dataclass(slots=True)
class Timeline:
    segments: list[StepSegment]
    final_end: float
    top_view_roll_deg: int = 0

    @property
    def duration(self) -> float:
        return self.final_end


@dataclass(slots=True)
class SceneFrame:
    time_sec: float
    visible_group_ids: set[str]
    translations: dict[str, Vector3]
    active_group_id: str | None
    highlight_alpha: float
    camera: CameraPose
    process_text: str = ""
    material_text: str = ""
    caution_text: str = ""
    step_index: int = 0
    base_group_id: str = ""


MANUAL_DIRECTIONS: dict[str, Vector3] = {
    "FRONT": (0, 1, 0), "BACK": (0, -1, 0), "RIGHT": (-1, 0, 0),
    "LEFT": (1, 0, 0), "TOP": (0, 0, -1), "BOTTOM": (0, 0, 1),
}


def smoothstep(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3 - 2 * value)


def landscape_top_roll(model_bounds: Bounds | None) -> int:
    """Original assembled XY extents only: no CAD, moving actors or PCA."""
    if model_bounds is None:
        return 0
    x,y,_=model_bounds.size
    return 90 if y>x+max(x,y,1.)*1e-9 else 0


def initial_camera(top_view_roll_deg=0):
    return CameraPose((0,0,-1),'AUTO',(-1,0,0) if top_view_roll_deg==90 else (0,1,0))


def camera_for_step(step, top_view_roll_deg=0) -> CameraPose:
    if step.camera_mode in MANUAL_DIRECTIONS:
        direction = MANUAL_DIRECTIONS[step.camera_mode]
    else:
        direction = normalize(step.assembly_direction)
    up = camera_up(direction)
    # Positive means clockwise rotation of the image, not of the assembly.
    # Apply the fixed assembly-level baseline only to a true top view,
    # including AUTO whose assembly direction is -Z. User roll is additive.
    is_top=abs(direction[0])<1e-9 and abs(direction[1])<1e-9 and direction[2]<-1+1e-9
    angle = math.radians(step.camera_roll_deg+(top_view_roll_deg if is_top else 0))
    sideways = cross(direction, up)
    up = tuple(math.cos(angle)*u - math.sin(angle)*r for u, r in zip(up, sideways))
    return CameraPose(direction, step.camera_mode, normalize(up))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def camera_up(direction):
    seed = (0, 1, 0) if abs(direction[2]) > .95 else (0, 0, 1)
    return normalize(cross(normalize(cross(direction, seed)), direction))


@lru_cache(maxsize=128)
def _orientation(pose):
    """Quaternion of right/up/back camera basis, including roll."""
    import numpy as np
    d = pose.view_direction
    up = pose.view_up or camera_up(d)
    right = normalize(cross(d, up)); up = cross(right, d)
    m = np.array([right, up, tuple(-x for x in d)]).T
    # Symmetric eigenproblem is well-conditioned for exact 180-degree turns.
    k = np.array([
        [m[0,0]-m[1,1]-m[2,2], m[0,1]+m[1,0], m[0,2]+m[2,0], m[2,1]-m[1,2]],
        [m[0,1]+m[1,0], m[1,1]-m[0,0]-m[2,2], m[1,2]+m[2,1], m[0,2]-m[2,0]],
        [m[0,2]+m[2,0], m[1,2]+m[2,1], m[2,2]-m[0,0]-m[1,1], m[1,0]-m[0,1]],
        [m[2,1]-m[1,2], m[0,2]-m[2,0], m[1,0]-m[0,1], m.trace()]], dtype=float)
    _, vectors = np.linalg.eigh(k)
    return tuple(float(v) for v in vectors[:, -1])


def _rotate(q, v):
    xyz, w = q[:3], q[3]
    uv = cross(xyz, v); uuv = cross(xyz, uv)
    return normalize(tuple(v[i]+2*(w*uv[i]+uuv[i]) for i in range(3)))


def interpolate_camera(a, b, fraction, *, ease=True):
    qa, qb = _orientation(a), _orientation(b)
    dot = sum(x*y for x,y in zip(qa,qb))
    if dot < 0: qb = tuple(-v for v in qb); dot = -dot
    f = smoothstep(fraction) if ease else min(1.,max(0.,fraction))
    if dot > .999999:
        q = tuple((1-f)*x+f*y for x,y in zip(qa,qb))
        length = math.sqrt(sum(v*v for v in q)); q = tuple(v/length for v in q)
    else:
        angle = math.acos(min(1.,dot))
        q = tuple((math.sin((1-f)*angle)*x+math.sin(f*angle)*y)/math.sin(angle) for x,y in zip(qa,qb))
    return CameraPose(_rotate(q,(0,0,-1)), b.mode, _rotate(q,(0,1,0)))


def _camera_angle(a: Vector3, b: Vector3) -> float:
    dot = max(-1.0, min(1.0, sum(x*y for x, y in zip(normalize(a), normalize(b)))))
    return math.degrees(math.acos(dot))


def camera_pose_angle(a: CameraPose, b: CameraPose) -> float:
    # Preserve legacy timing for unrolled views; include roll for new settings.
    canonical = all(sum(x*y for x,y in zip(p.view_up or camera_up(p.view_direction),
                    camera_up(p.view_direction))) > 1-1e-9 for p in (a,b))
    if canonical:
        return _camera_angle(a.view_direction,b.view_direction)
    dot = abs(sum(x*y for x,y in zip(_orientation(a),_orientation(b))))
    if dot>1-1e-12:return 0.
    return math.degrees(2*math.acos(min(1.,dot)))


def interpolate_view(a: Vector3, b: Vector3, fraction: float, *, ease=True) -> Vector3:
    a, b = normalize(a), normalize(b)
    f = smoothstep(fraction) if ease else min(1.,max(0.,fraction))
    dot = max(-1., min(1., sum(x*y for x, y in zip(a, b))))
    if dot > 1-1e-9:
        return b
    if dot < -1+1e-9:
        # A deterministic perpendicular handles 180 degrees without the zero
        # vector produced by linear interpolation of opposite directions.
        seed = (0, 0, 1) if abs(a[2]) < .9 else (0, 1, 0)
        perpendicular = normalize((a[1]*seed[2]-a[2]*seed[1],
                                   a[2]*seed[0]-a[0]*seed[2],
                                   a[0]*seed[1]-a[1]*seed[0]))
        return normalize(tuple(math.cos(math.pi*f)*x+math.sin(math.pi*f)*y for x, y in zip(a, perpendicular)))
    angle = math.acos(dot)
    return normalize(tuple((math.sin((1-f)*angle)*x+math.sin(f*angle)*y)/math.sin(angle) for x, y in zip(a, b)))


def build_timeline(plan: Plan, settings: AppSettings, model_bounds: Bounds | None = None) -> Timeline:
    segments: list[StepSegment] = []
    cursor = 0.0
    top_roll=landscape_top_roll(model_bounds)
    previous = initial_camera(top_roll)
    for step in plan.steps:
        current = camera_for_step(step,top_roll)
        angle = camera_pose_angle(previous, current)
        camera_sec = 0.0 if angle < 1e-6 else max(0.3, settings.camera_180_sec * angle / 180.0)
        segment = StepSegment(
            step_index=step.step_index,
            camera_start=cursor,
            camera_end=cursor + camera_sec,
            highlight_end=cursor + camera_sec + settings.highlight_sec,
            move_end=cursor + camera_sec + settings.highlight_sec + settings.assembly_move_sec,
        )
        segments.append(segment)
        cursor = segment.move_end
        previous = current
    return Timeline(segments=segments, final_end=cursor + settings.final_hold_sec,top_view_roll_deg=top_roll)


def scene_at(plan: Plan, time_sec: float, settings: AppSettings, timeline: Timeline | None = None,
             *, model_bounds: Bounds | None = None) -> SceneFrame:
    timeline = timeline or build_timeline(plan, settings,model_bounds)
    t = min(max(0.0, time_sec), timeline.duration)
    # A partial removal prefix reverses onto the still-assembled remainder.
    # Omitted groups are NOT proven removed and must not disappear in preview.
    stationary = set(plan.group_ids) - {step.group_id for step in plan.steps}
    stationary.add(plan.base_group_id)
    visible = set(stationary)
    translations: dict[str, Vector3] = {group_id: (0, 0, 0) for group_id in stationary}
    active = None
    alpha = 0.0
    camera = initial_camera(timeline.top_view_roll_deg)
    process = material = caution = ""
    current_index = 0
    for step, segment in zip(plan.steps, timeline.segments):
        if t >= segment.move_end:
            visible.add(step.group_id)
            translations[step.group_id] = (0, 0, 0)
            camera = camera_for_step(step,timeline.top_view_roll_deg)
            process, material, caution = step.process_text, step.material_text, step.caution_text
            current_index = step.step_index
            continue
        if t < segment.camera_start:
            break
        active = step.group_id
        visible.add(step.group_id)
        previous_camera = camera
        previous_view = camera.view_direction
        camera = camera_for_step(step,timeline.top_view_roll_deg)
        if segment.camera_end > segment.camera_start and t < segment.camera_end:
            fraction = (t-segment.camera_start)/(segment.camera_end-segment.camera_start)
            if settings.camera_mode == 'stepped_45':
                angle = camera_pose_angle(previous_camera, camera)
                eased = smoothstep(fraction)
                reached = math.floor(angle*eased/45)*45
                fraction=reached/max(angle,1e-9)
            camera = interpolate_camera(previous_camera,camera,fraction,
                                        ease=settings.camera_mode!='stepped_45')
        process, material, caution = step.process_text, step.material_text, step.caution_text
        current_index = step.step_index
        distance = step.travel_mm
        direction = step.removal_direction
        if t <= segment.camera_end:
            fraction = 0.0
        elif t <= segment.highlight_end:
            fraction = 0.0
            alpha = 1.0 if int((t-segment.camera_end)*4) % 2 == 0 else 0.0
        else:
            fraction = smoothstep((t - segment.highlight_end) / max(1e-9, segment.move_end - segment.highlight_end))
            alpha = 1.0
        remaining = 1.0 - fraction
        translations[step.group_id] = tuple(direction[i] * distance * remaining for i in range(3))  # type: ignore[assignment]
        break
    return SceneFrame(t, visible, translations, active, alpha, camera, process, material, caution, current_index, plan.base_group_id)

