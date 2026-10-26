from __future__ import annotations

import os
import hashlib
from pathlib import Path
from typing import Iterable

import vtk
from vtkmodules.util.numpy_support import vtk_to_numpy

from pa2.cad.importer import CadScene, tessellate_shape
from pa2.domain.models import AssemblyGroup, Bounds, PartType

from .scene import SceneFrame, camera_up
from .orbit import OrbitCamera


def _color_for(value: str) -> tuple[float, float, float]:
    digest = hashlib.sha256(value.encode('utf-8')).digest()
    return tuple(0.35 + channel / 255 * 0.5 for channel in digest[:3])


SELECTION_RED = (1.0, 0.0, 0.0)


class VtkScene:
    def __init__(self, render_window: vtk.vtkRenderWindow | None = None, *, offscreen: bool = False) -> None:
        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(0.96, 0.97, 0.99)
        self.render_window = render_window or vtk.vtkRenderWindow()
        self.render_window.AddRenderer(self.renderer)
        self._selection_renderer=vtk.vtkRenderer();self._selection_renderer.SetLayer(1)
        self._selection_renderer.InteractiveOff();self._selection_renderer.SetPreserveDepthBuffer(False)
        self._selection_renderer.SetActiveCamera(self.renderer.GetActiveCamera())
        self.render_window.SetNumberOfLayers(2);self.render_window.AddRenderer(self._selection_renderer)
        if offscreen:
            self.render_window.SetOffScreenRendering(1)
        self.actors: dict[str, vtk.vtkActor] = {}
        self.base_colors = {}
        self._selection_properties = None
        self.group_bounds: dict[str, Bounds] = {}
        self.group_types = {}
        self._selection_positions = {}
        self._selection_guides = []
        self._selection_overlay_ids = []
        self.base_center = (0.0, 0.0, 0.0)
        self.camera_distance = 100.0
        self.camera_base_id = None
        self.pan_mode = False
        self._thumbnail_window = None
        self._orbit_timer = None
        self._orbit = None
        self._viewer_text = []

    def clear(self) -> None:
        self.clear_selection()
        self.renderer.RemoveAllViewProps()
        for actor in self._viewer_text:self.renderer.AddViewProp(actor)
        self.actors.clear()
        self.base_colors.clear()
        self.group_bounds.clear()
        self.group_types.clear()
        self.camera_base_id = None

    def load(self, scene: CadScene, groups: list[AssemblyGroup], deflection_mm: float = 0.2) -> None:
        self.clear()
        body_map = {getattr(b, 'id', None): b for b in scene.bodies}
        for group in groups:
            append = vtk.vtkAppendPolyData()
            for body_id in group.body_ids:
                points, triangles = tessellate_shape(scene.shapes[body_id], deflection_mm)
                poly = vtk.vtkPolyData()
                vtk_points = vtk.vtkPoints()
                for point in points:
                    vtk_points.InsertNextPoint(*point)
                cells = vtk.vtkCellArray()
                for triangle in triangles:
                    cells.InsertNextCell(3)
                    for index in triangle:
                        cells.InsertCellPoint(index)
                poly.SetPoints(vtk_points)
                poly.SetPolys(cells)
                append.AddInputData(poly)
            append.Update()
            normals = vtk.vtkPolyDataNormals()
            normals.SetInputConnection(append.GetOutputPort())
            normals.ConsistencyOn()
            normals.AutoOrientNormalsOn()
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(normals.GetOutputPort())
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            weights = {}
            for body_id in group.body_ids:
                body = body_map.get(body_id)
                color = getattr(body, 'color_rgb', None)
                if color is not None:
                    color = tuple(color)
                    weights[color] = weights.get(color, 0.) + (getattr(body, 'area_mm2', None) or 1.)
            color = max(weights, key=lambda c: (weights[c], c)) if weights else _color_for(group.id)
            self.base_colors[group.id] = color
            actor.GetProperty().SetColor(*color)
            actor.GetProperty().SetInterpolationToPhong()
            self.renderer.AddActor(actor)
            self.actors[group.id] = actor
            self.group_bounds[group.id] = group.bounds
            self.group_types[group.id] = group.part_type
        if groups:
            union = Bounds.union(group.bounds for group in groups)
            self.base_center = union.center
            self.camera_distance = max(union.diagonal * 1.6, 100.0)
        self.fit()

    def fit(self) -> None:
        self._stop_navigation()
        self.renderer.ResetCamera()
        self.renderer.ResetCameraClippingRange()
        self.render_window.Render()

    def zoom(self, factor):
        self._stop_navigation()
        self.renderer.GetActiveCamera().Dolly(factor)
        self.renderer.ResetCameraClippingRange(); self.render_window.Render()

    def set_view(self, name):
        self._stop_navigation()
        directions={'등각':(1,-1,1),'상면':(0,0,1),'하면':(0,0,-1),
                    '정면':(0,-1,0),'후면':(0,1,0),'좌측':(-1,0,0),'우측':(1,0,0)}
        vector=directions.get(name,(1,-1,1)); length=sum(v*v for v in vector)**.5
        camera=self.renderer.GetActiveCamera(); center=camera.GetFocalPoint(); distance=camera.GetDistance()
        camera.SetPosition(*(c+v/length*distance for c,v in zip(center,vector)))
        camera.SetViewUp(0,1,0) if abs(vector[2])==1 and not vector[0] and not vector[1] else camera.SetViewUp(0,0,1)
        self.renderer.ResetCameraClippingRange(); self.render_window.Render()

    def clear_selection(self):
        self._selection_renderer.RemoveAllViewProps()
        self._selection_overlay_ids.clear()
        for gid,position in self._selection_positions.items():
            if gid in self.actors:self.actors[gid].SetPosition(*position)
        self._selection_positions.clear()
        for guide in self._selection_guides:self.renderer.RemoveActor(guide)
        self._selection_guides.clear()
        if self._selection_properties is not None:
            for gid, prop in self._selection_properties.items():
                if gid in self.actors:self.actors[gid].GetProperty().DeepCopy(prop)
            self._selection_properties = None

    def clear_highlight(self, *, render=True):
        self.clear_selection()
        if render:self.render_window.Render()

    def capture_selection_state(self):
        """Snapshot display-only effects for reversible per-step preview."""
        actors = {}
        for gid, actor in self.actors.items():
            prop = vtk.vtkProperty();prop.DeepCopy(actor.GetProperty())
            actors[gid] = (actor.GetVisibility(), actor.GetPosition(), prop)
        return dict(actors=actors, properties=self._selection_properties,
            positions=dict(self._selection_positions), guides=list(self._selection_guides),
            overlays=list(self._selection_overlay_ids))

    def restore_selection_state(self, state):
        self.clear_selection()
        for gid, (visible, position, prop) in state['actors'].items():
            actor = self.actors.get(gid)
            if actor:
                actor.SetVisibility(visible);actor.SetPosition(*position)
                actor.GetProperty().DeepCopy(prop)
        self._selection_properties = state['properties']
        self._selection_positions = dict(state['positions'])
        self._selection_guides = list(state['guides'])
        self._selection_overlay_ids = list(state['overlays'])
        for guide in self._selection_guides:
            self.renderer.AddActor(guide);self._selection_renderer.AddActor(guide)
        for overlay, _ in self._selection_overlay_ids:self._selection_renderer.AddActor(overlay)
        self.render_window.Render()

    def _show_selection_overlay(self,actor,gid):
        # Draw selected surfaces at their true display position above the
        # context, so an internal part remains locatable inside a closed case.
        overlay=vtk.vtkActor();overlay.SetMapper(actor.GetMapper());overlay.SetProperty(actor.GetProperty())
        overlay.SetUserMatrix(actor.GetMatrix())
        self._selection_renderer.AddActor(overlay)
        self._selection_overlay_ids.append((overlay,gid))

    def pick_group(self,point):
        picker=vtk.vtkCellPicker();picker.SetTolerance(.005)
        if self._selection_overlay_ids:
            picker.Pick(*point,0,self._selection_renderer)
            actor=picker.GetActor()
            gid=next((gid for item,gid in self._selection_overlay_ids if item==actor),None)
            if gid is not None:return gid
        picker.Pick(*point,0,self.renderer);actor=picker.GetActor()
        return next((gid for gid,item in self.actors.items() if item==actor),None)

    def highlight(self, ids):
        self.clear_selection()
        ids=set(ids) & self.actors.keys()
        if not ids:
            self.render_window.Render();return
        self._selection_properties = {}
        for gid, actor in self.actors.items():
            prop=vtk.vtkProperty();prop.DeepCopy(actor.GetProperty())
            self._selection_properties[gid]=prop
        locating=any(gid in ids and actor.GetVisibility() for gid,actor in self.actors.items())
        union=Bounds.union(self.group_bounds.values()) if self.group_bounds else None
        for gid,actor in self.actors.items():
            active=gid in ids;actor.GetProperty().EdgeVisibilityOff()
            if active:
                actor.GetProperty().SetColor(*SELECTION_RED);actor.GetProperty().SetOpacity(1.)
            elif locating:
                actor.GetProperty().SetColor(.65,.65,.65)
                actor.GetProperty().SetOpacity(.25 if len(ids)==1 else .10)
            bounds=self.group_bounds.get(gid)
            small=bounds and union and (self.group_types.get(gid) in (PartType.BOLT,PartType.NUT)
                                        or bounds.diagonal<union.diagonal*.06)
            if active and small and actor.GetVisibility():
                original=actor.GetPosition();self._selection_positions[gid]=original
                away=tuple(a-b for a,b in zip(bounds.center,union.center));length=sum(v*v for v in away)**.5
                direction=tuple(v/length for v in away) if length>1e-9 else (0.,0.,1.)
                distance=min(bounds.diagonal*.18,union.diagonal*.012)
                offset=tuple(v*distance for v in direction);actor.SetPosition(*(a+b for a,b in zip(original,offset)))
                start=tuple(a+b for a,b in zip(bounds.center,original));end=tuple(a+b for a,b in zip(start,offset))
                line=vtk.vtkLineSource();line.SetPoint1(*start);line.SetPoint2(*end)
                mapper=vtk.vtkPolyDataMapper();mapper.SetInputConnection(line.GetOutputPort())
                guide=vtk.vtkActor();guide.SetMapper(mapper);guide.PickableOff()
                guide.GetProperty().SetColor(*SELECTION_RED);guide.GetProperty().SetLineWidth(1.5)
                self.renderer.AddActor(guide);self._selection_guides.append(guide)
                self._selection_renderer.AddActor(guide)
            if active and actor.GetVisibility():self._show_selection_overlay(actor,gid)
        self.render_window.Render()

    def configure_interaction(self, interactor, on_pick, timer_parent=None):
        from PySide6.QtCore import QTimer
        self._stop_navigation()
        style=vtk.vtkInteractorStyleUser(); interactor.SetInteractorStyle(style)
        self.renderer.SetBackground(1,1,1)
        self.renderer.GetActiveCamera().SetViewAngle(35)
        self._configure_viewer_text()
        self._orbit=OrbitCamera(self.renderer.GetActiveCamera())
        self._orbit_timer=QTimer(timer_parent)
        self._orbit_timer.setInterval(0)
        self._orbit_timer.setSingleShot(True)
        drag={'button':None,'origin':None,'last':None,'moved':False,'pan':False}
        def limits():
            if self.group_bounds:
                bounds=Bounds.union(self.group_bounds.values())
                size=max(bounds.xmax-bounds.xmin,bounds.ymax-bounds.ymin,bounds.zmax-bounds.zmin,.001)
                self._orbit.min_distance=size*.02; self._orbit.max_distance=size*30
        def render():
            self.renderer.ResetCameraClippingRange(); self.render_window.Render()
        self._orbit_timer.timeout.connect(render)
        def request_render():
            # Coalesce paints without restarting the timer on every pointer event.
            if not self._orbit_timer.isActive():self._orbit_timer.start()
        def press(_obj,event):
            point=interactor.GetEventPosition()
            button=event.replace('ButtonPressEvent','')
            drag.update(button=button,origin=point,last=point,moved=False,
                        pan=button!='Left' or self.pan_mode or bool(interactor.GetControlKey() or interactor.GetShiftKey()))
        def move(_obj,_event):
            if drag['button'] is None:return
            point=interactor.GetEventPosition(); origin=drag['origin']; previous=drag['last']
            if sum((a-b)**2 for a,b in zip(point,origin))>9:drag['moved']=True
            # Don't orbit/pan on a selection click or on tiny pointer jitter.
            if not drag['moved']:return
            dx=point[0]-previous[0]; dy=previous[1]-point[1]
            height=self.render_window.GetSize()[1]
            (self._orbit.pan if drag['pan'] else self._orbit.rotate)(dx,dy,height)
            self._orbit.step()
            drag['last']=point
            request_render()
        def release(_obj,event):
            point=interactor.GetEventPosition()
            if drag['button']=='Left' and event=='LeftButtonReleaseEvent' and not drag['moved'] and drag['origin'] and sum((a-b)**2 for a,b in zip(point,drag['origin']))<=9:
                gid=self.pick_group(point)
                if gid:on_pick(gid,bool(interactor.GetControlKey() or interactor.GetShiftKey()))
            drag['button']=None
        def wheel(_obj,event):
            limits(); self._orbit.zoom(1 if event=='MouseWheelForwardEvent' else -1)
            request_render()
        for button in ('Left','Middle','Right'):
            style.AddObserver(button+'ButtonPressEvent',press)
            style.AddObserver(button+'ButtonReleaseEvent',release)
        style.AddObserver('MouseMoveEvent',move)
        style.AddObserver('MouseWheelForwardEvent',wheel); style.AddObserver('MouseWheelBackwardEvent',wheel)
        self._interaction_style=style

    def _configure_viewer_text(self):
        if self._viewer_text:return
        font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/malgun.ttf'
        for text,x,y,centered in (
            ('드래그 회전 · 휠 확대 · 우클릭 이동 · Ctrl+클릭 다중 선택',.5,.025,True),):
            actor=vtk.vtkTextActor();actor.SetInput(text)
            actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport();actor.SetPosition(x,y)
            prop=actor.GetTextProperty();prop.SetFontSize(11);prop.SetColor(.40,.46,.54)
            prop.BoldOff();prop.ShadowOff();prop.SetVerticalJustificationToBottom()
            if font.is_file():prop.SetFontFamily(vtk.VTK_FONT_FILE);prop.SetFontFile(str(font))
            prop.SetJustificationToCentered() if centered else prop.SetJustificationToLeft()
            self.renderer.AddViewProp(actor);self._viewer_text.append(actor)

    def _stop_navigation(self):
        if self._orbit_timer:self._orbit_timer.stop()
        if self._orbit:self._orbit.reset_motion()

    def thumbnail(self, group_id):
        if self._thumbnail_window is None:
            self._thumbnail_renderer=vtk.vtkRenderer(); self._thumbnail_renderer.SetBackground(.95,.96,.98)
            self._thumbnail_window=vtk.vtkRenderWindow(); self._thumbnail_window.SetOffScreenRendering(1)
            self._thumbnail_window.SetSize(272,164); self._thumbnail_window.AddRenderer(self._thumbnail_renderer)
        renderer=self._thumbnail_renderer; renderer.RemoveAllViewProps()
        actor=vtk.vtkActor(); actor.SetMapper(self.actors[group_id].GetMapper())
        actor.GetProperty().SetColor(*self.base_colors.get(group_id,_color_for(group_id))); renderer.AddActor(actor)
        camera=renderer.GetActiveCamera(); camera.SetPosition(1,-1,1); camera.SetFocalPoint(0,0,0); camera.SetViewUp(0,0,1)
        renderer.ResetCamera(); self._thumbnail_window.Render()
        capture=vtk.vtkWindowToImageFilter(); capture.SetInput(self._thumbnail_window); capture.SetInputBufferTypeToRGB(); capture.ReadFrontBufferOff(); capture.Update()
        pixels=vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars()).reshape(164,272,3)
        return pixels[::-1].copy()

    def apply(self, frame: SceneFrame, width: int | None = None, height: int | None = None) -> None:
        self.clear_selection()
        self._stop_navigation()
        for group_id, actor in self.actors.items():
            actor.SetVisibility(group_id in frame.visible_group_ids)
            actor.SetPosition(*frame.translations.get(group_id, (0, 0, 0)))
            actor.GetProperty().EdgeVisibilityOff()
            # Shared preview/export policy: keep original colors and opacity,
            # blink before movement, solid red while moving. Edit-only overlays
            # and small-part display offsets never leak into animation/video.
            color=self.base_colors.get(group_id,_color_for(group_id))
            alpha=frame.highlight_alpha if group_id==frame.active_group_id else 0.0
            actor.GetProperty().SetColor(*(c*(1-alpha)+h*alpha for c,h in zip(color,SELECTION_RED)))
            actor.GetProperty().SetOpacity(1.)
        direction = frame.camera.view_direction
        if self.group_bounds:
            if frame.base_group_id in self.group_bounds and self.camera_base_id!=frame.base_group_id:
                self.base_center=self.group_bounds[frame.base_group_id].center
                union=Bounds.union(self.group_bounds.values())
                radius=sum(max(abs(lo-c),abs(hi-c))**2 for lo,hi,c in zip(
                    (union.xmin,union.ymin,union.zmin),(union.xmax,union.ymax,union.zmax),self.base_center))**.5
                self.camera_distance=max(radius*3.2,100.0)
                self.camera_base_id=frame.base_group_id
            center=self.base_center
            distance=self.camera_distance
            camera = self.renderer.GetActiveCamera()
            camera.SetFocalPoint(*center)
            camera.SetPosition(*(center[i] - direction[i] * distance for i in range(3)))
            camera.SetViewUp(*(frame.camera.view_up or camera_up(direction)))
            self.renderer.ResetCameraClippingRange()
        if width and height:
            self.render_window.SetSize(width, height)
        self.render_window.Render()

    def rgb_array(self):
        capture = vtk.vtkWindowToImageFilter()
        capture.SetInput(self.render_window)
        capture.SetInputBufferTypeToRGB()
        capture.ReadFrontBufferOff()
        capture.Update()
        image = capture.GetOutput()
        width, height, _ = image.GetDimensions()
        array = vtk_to_numpy(image.GetPointData().GetScalars()).reshape(height, width, 3)
        return array[::-1].copy()

