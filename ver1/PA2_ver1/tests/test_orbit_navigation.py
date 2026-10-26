import math
import pytest
import vtk
from pa2.rendering.orbit import OrbitCamera


def controller():
    camera=vtk.vtkCamera(); camera.SetPosition(10,-10,10); camera.SetFocalPoint(0,0,0); camera.SetViewUp(0,0,1)
    return OrbitCamera(camera)


def settle(orbit):
    for _ in range(250):
        if not orbit.step():break
    else:raise AssertionError('Orbit damping never settled')


def test_orbit_preserves_pivot_distance_and_vertical_axis():
    orbit=controller(); camera=orbit.camera; distance=camera.GetDistance()
    orbit.rotate(150,40,600); settle(orbit)
    assert camera.GetPosition()!=pytest.approx((10,-10,10))
    assert camera.GetDistance()==pytest.approx(distance)
    assert camera.GetFocalPoint()==pytest.approx((0,0,0))
    assert camera.GetViewUp()==pytest.approx((0,0,1))
    orbit.rotate(0,100000,600); settle(orbit)
    assert all(math.isfinite(v) for v in camera.GetPosition())
    assert 0<abs(camera.GetPosition()[2])<distance


def test_pan_moves_pivot_and_camera_together_without_changing_view():
    orbit=controller(); camera=orbit.camera
    direction=camera.GetDirectionOfProjection(); distance=camera.GetDistance()
    orbit.pan(100,50,600); settle(orbit)
    assert camera.GetFocalPoint()!=pytest.approx((0,0,0))
    assert camera.GetDirectionOfProjection()==pytest.approx(direction)
    assert camera.GetDistance()==pytest.approx(distance)


def test_wheel_is_reversible_and_stays_inside_model_relative_limits():
    orbit=controller(); camera=orbit.camera; before=camera.GetDistance()
    orbit.zoom(1); assert camera.GetDistance()==pytest.approx(before*.95)
    orbit.zoom(-1); assert camera.GetDistance()==pytest.approx(before)
    orbit.min_distance=2; orbit.max_distance=50
    orbit.zoom(1000); assert camera.GetDistance()==pytest.approx(2)
    orbit.zoom(-1000); assert camera.GetDistance()==pytest.approx(50)


def test_drag_consumes_the_full_input_in_one_update_without_inertia():
    orbit=controller(); camera=orbit.camera
    theta=math.atan2(10,10)
    orbit.rotate(50,0,600)
    assert orbit.step() is False
    actual=math.atan2(camera.GetPosition()[0],-camera.GetPosition()[1])
    assert actual==pytest.approx(theta-2*math.pi*50/600)
    position=camera.GetPosition()
    assert orbit.step() is False and camera.GetPosition()==pytest.approx(position)


def test_mouse_burst_updates_camera_before_event_loop_and_coalesces_render(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from pa2.rendering.vtk_scene import VtkScene
    app=QApplication.instance() or QApplication([])
    scene=VtkScene(offscreen=True); scene.render_window.SetSize(600,400)
    interactor=vtk.vtkGenericRenderWindowInteractor();interactor.SetRenderWindow(scene.render_window)
    scene.configure_interaction(interactor,lambda *_:None)
    camera=scene.renderer.GetActiveCamera();camera.SetPosition(10,-10,10);camera.SetFocalPoint(0,0,0)
    renders=[];scene.render_window.AddObserver('StartEvent',lambda *_:renders.append(1))
    style=scene._interaction_style
    try:
        interactor.SetEventInformation(200,200,0,0);style.InvokeEvent('LeftButtonPressEvent')
        positions=[]
        for x in range(210,310,10):
            interactor.SetEventInformation(x,200,0,0);style.InvokeEvent('MouseMoveEvent');positions.append(camera.GetPosition())
        assert len(set(positions))==10
        assert scene._orbit_timer.isActive() and not renders
        style.InvokeEvent('LeftButtonReleaseEvent');released=camera.GetPosition()
        app.processEvents()
        assert len(renders)==1
        app.processEvents()
        assert camera.GetPosition()==released and not scene._orbit_timer.isActive()
    finally:
        scene._stop_navigation();scene.render_window.Finalize()
