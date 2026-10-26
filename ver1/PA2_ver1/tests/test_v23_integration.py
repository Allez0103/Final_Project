"""UI integration contracts; no model training or evaluation is performed."""
import copy

from test_mentor_visuals import editor


def test_new_ui_retains_manual_generation_and_autosave(editor):
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtCore import Qt
    assert editor.auto_generate.text()=='자동생성'
    assert editor.manual_generate.text()=='수동생성'
    assert not any(b.text()=='초안 저장' for b in editor.findChildren(QPushButton))
    requests=[];editor.manual_requested.connect(requests.append)
    editor.manual_generate.click()
    assert requests[0]['display_order']==[editor.parts.item(i).data(Qt.UserRole) for i in range(editor.parts.count())]
    saves=[];editor.save_requested.connect(lambda p:saves.append(copy.deepcopy(p.to_dict())))
    original=editor.plan.to_dict()
    editor.direction.setCurrentText('-X');editor._apply_step()
    assert len(saves)==1 and saves[-1]==editor.plan.to_dict()
    editor._history(False)
    assert len(saves)==2 and saves[-1]==original
    editor._history(True)
    assert len(saves)==3 and saves[-1]==editor.plan.to_dict()
    editor.order.setCurrentRow(0);editor._single();editor.order.move_selection(1)
    assert len(saves)==4 and saves[-1]==editor.plan.to_dict()


def test_step_preview_restores_all_display_state_and_blink_policy(editor):
    from pa2.rendering.scene import build_timeline,scene_at
    import pytest
    scene=editor.vtk_scene
    before={g:(a.GetVisibility(),a.GetPosition(),a.GetProperty().GetOpacity(),a.GetProperty().GetColor())
            for g,a in scene.actors.items()}
    camera=scene.renderer.GetActiveCamera()
    pose=(camera.GetPosition(),camera.GetFocalPoint(),camera.GetViewUp())
    for _ in range(3):editor._preview_step();editor._preview_tick();editor._stop_preview()
    assert before=={g:(a.GetVisibility(),a.GetPosition(),a.GetProperty().GetOpacity(),a.GetProperty().GetColor())
                    for g,a in scene.actors.items()}
    assert pose==(camera.GetPosition(),camera.GetFocalPoint(),camera.GetViewUp())
    timeline=build_timeline(editor.plan,editor.settings);seg=timeline.segments[0]
    for t,color in [(seg.camera_end+.01,(1,0,0)),(seg.camera_end+.26,scene.base_colors['bolt']),
                    (seg.highlight_end+.1,(1,0,0)),(timeline.duration,scene.base_colors['bolt'])]:
        scene.apply(scene_at(editor.plan,t,editor.settings,timeline))
        assert scene.actors['bolt'].GetProperty().GetColor()==pytest.approx(color)
        assert not scene._selection_overlay_ids and not scene._selection_positions
        assert all(a.GetProperty().GetOpacity()==1 for a in scene.actors.values())
