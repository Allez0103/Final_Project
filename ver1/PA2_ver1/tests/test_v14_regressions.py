from dataclasses import replace
from pathlib import Path

import pytest
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_OUT
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pln, gp_Pnt, gp_Dir

from pa2.cad.sweep import valid_prism
from pa2.domain.models import Plan, PlanStep, PlanningStatus, Bounds
from pa2.rendering.scene import scene_at, build_timeline
from pa2.settings.config import AppSettings


@pytest.mark.parametrize('reverse',[False,True])
@pytest.mark.parametrize('direction',[(0,0,1),(0,0,-1)])
def test_prism_infinite_point_is_outside_for_both_face_orientations(reverse,direction):
    face=BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0,0,0),gp_Dir(0,0,1)),0,1,0,1).Face()
    if reverse:face=TopoDS.Face(face.Reversed())
    solid=valid_prism(face,direction,3)
    assert solid is not None
    classifier=BRepClass3d_SolidClassifier(solid); classifier.PerformInfinitePoint(1e-7)
    assert classifier.State()==TopAbs_OUT
    props=GProp_GProps(); BRepGProp.VolumeProperties_s(solid,props)
    assert props.Mass()==pytest.approx(3)


def test_blink_keeps_part_visible_and_holds_highlight_through_motion():
    plan=Plan('p','project',1,'base',['base','part'],[PlanStep('part',1,(0,0,1),(0,0,-1),10)],PlanningStatus.COMPLETE)
    settings=AppSettings(); segment=build_timeline(plan,settings).segments[0]
    on=scene_at(plan,segment.camera_end+.1,settings)
    off=scene_at(plan,segment.camera_end+.3,settings)
    move=scene_at(plan,(segment.highlight_end+segment.move_end)/2,settings)
    end=scene_at(plan,segment.move_end,settings)
    assert on.highlight_alpha>0 and off.highlight_alpha==0
    assert all('part' in frame.visible_group_ids for frame in (on,off,move,end))
    assert on.translations==off.translations
    assert move.highlight_alpha==on.highlight_alpha
    assert end.highlight_alpha==0


def test_camera_focal_point_and_distance_do_not_follow_moving_part():
    from pa2.rendering.vtk_scene import VtkScene
    plan=Plan('p','project',1,'base',['base','part'],[PlanStep('part',1,(0,0,1),(0,0,-1),1000)],PlanningStatus.COMPLETE)
    scene=VtkScene(offscreen=True)
    scene.group_bounds={'base':Bounds(0,0,0,10,10,10),'part':Bounds(10,0,0,11,1,1)}
    try:
        settings=AppSettings(); segment=build_timeline(plan,settings).segments[0]
        states=[]
        for t in (0,(segment.highlight_end+segment.move_end)/2,segment.move_end):
            scene.apply(scene_at(plan,t,settings),320,180)
            camera=scene.renderer.GetActiveCamera()
            states.append((camera.GetFocalPoint(),camera.GetDistance(),camera.GetViewAngle()))
        assert states[0]==states[1]==states[2]
        assert states[0][0]==(5,5,5)
    finally:scene.render_window.Finalize()


def test_empty_video_panels_still_draw_template():
    from PIL import Image, ImageDraw
    from pa2.video.renderer import VideoRenderer
    root=Path(__file__).resolve().parents[1]
    renderer=VideoRenderer(AppSettings(),root/'assets/video_template_v1.json')
    image=Image.new('RGB',(400,300),'#000000')
    renderer._panel(ImageDraw.Draw(image),(0,0,399,299),'주의사항','','#D53232')
    assert image.getpixel((200,200))==(255,255,255)
    assert image.getpixel((0,150))!=(0,0,0)
