import copy
from dataclasses import replace,asdict
import pytest
from test_grouping import body,scene
from test_mentor_visuals import editor
from pa2.cad.grouping import GroupingService
from pa2.domain.models import Plan,PlanStep,PlanningStatus
from pa2.rendering.scene import (build_timeline,scene_at,camera_for_step,
    set_shared_camera_roll,shared_camera_roll,camera_view_key)
from pa2.settings.config import AppSettings


def test_extended_retry_preserves_strict_and_existing_fallback():
    part=scene('AIR-X.STP',[body('p',10,(100,0,0)),body('q',20,(105,0,0))])
    assembly=scene('assembly.step',[body('a',10.015,(0,0,0)),body('b',20,(5.008,0,0)),body('known',5000,(0,20,0))])
    known=scene('MBD-X.STP',[body('k',5000,(0,0,0))])
    old=GroupingService().resolve(scene('x',[assembly.bodies[-1]]),[known]).groups[0]
    result=GroupingService(position_tolerance_mm=.001).resolve(assembly,[part,known])
    assert not result.unresolved_body_ids and len(result.relaxed_matches)==1
    assert next(g for g in result.groups if g.body_ids==['known'])==old
    info=result.relaxed_matches[0]
    assert info['relative_tolerance']==.002 and info['position_tolerance_mm']==.01
    assert info['search_complete'] and info['distinct_body_sets']==1


@pytest.mark.parametrize('kind',['multiple','competing','budget','oversize'])
def test_extended_retry_never_guesses(kind):
    part=scene('A.STP',[body('p',10,(100,0,0))])
    assembly=scene('x',[body('a',10.015,(0,0,0))]);parts=[part]
    service=GroupingService(position_tolerance_mm=.001)
    if kind=='multiple':assembly.bodies.append(body('b',10.015,(10,0,0)))
    if kind=='competing':parts.append(scene('B.STP',[body('q',10,(200,0,0))]))
    if kind=='budget':service.ANCHOR_RETRY_NODE_LIMIT=0
    if kind=='oversize':assembly.bodies[0]=replace(assembly.bodies[0],volume_mm3=10.03)
    result=service.resolve(assembly,parts)
    assert not result.relaxed_matches and len(result.unresolved_body_ids)==len(assembly.bodies)


def plan_fixture():
    modes=['TOP','TOP','BOTTOM','FRONT','BACK','LEFT','RIGHT','AUTO']
    return Plan('p','q',1,'base',['base']+[str(i) for i in range(len(modes))],
        [PlanStep(str(i),i+1,(0,0,1),(0,0,-1),10,camera_mode=mode) for i,mode in enumerate(modes)],PlanningStatus.COMPLETE)


@pytest.mark.parametrize('mode',['TOP','BOTTOM','FRONT','BACK','LEFT','RIGHT'])
def test_each_view_common_roll_changes_all_same_axis_including_auto(mode):
    plan=plan_fixture();step=next(s for s in plan.steps if s.camera_mode==mode)
    original=copy.deepcopy(plan.to_dict());set_shared_camera_roll(plan,step,90)
    for s,before in zip(plan.steps,original['steps']):
        assert s.removal_direction==before['removal_direction'] and s.travel_mm==before['travel_mm']
        assert shared_camera_roll(plan,s)==(90 if camera_view_key(s)==mode else 0)
    changed=next(s for s in plan.steps if camera_view_key(s)!=mode)
    changed.camera_mode=mode  # A subsequently chosen view uses the saved common value.
    assert camera_for_step(changed,0,plan.camera_rolls)==camera_for_step(replace(changed,camera_roll_deg=90))


def test_base_stage_no_translation_no_new_computational_step():
    plan=plan_fixture();before=copy.deepcopy(plan.to_dict());settings=AppSettings()
    timeline=build_timeline(plan,settings)
    for t in (0,.25,.5,settings.highlight_sec-.001):
        f=scene_at(plan,t,settings,timeline)
        assert f.active_group_id=='base' and f.visible_group_ids=={'base'}
        assert f.translations=={'base':(0,0,0)} and f.caution_text==''
    assert scene_at(plan,0,settings,timeline).highlight_alpha!=scene_at(plan,.25,settings,timeline).highlight_alpha
    assert timeline.segments[0].camera_start==timeline.base_end
    assert scene_at(plan,timeline.duration,settings,timeline).visible_group_ids==set(plan.group_ids)
    assert plan.to_dict()==before
    no_blink=replace(settings,highlight_sec=0)
    assert build_timeline(plan,no_blink).base_end==.5
    assert scene_at(plan,0,no_blink).active_group_id=='base'


def test_common_roll_db_legacy_confirm_undo_and_base_card(editor,tmp_path):
    from pa2.cli import _runtime
    from pa2.application.plan_service import PlanService
    p=editor
    assert p.base_card.text().startswith('01  base') and not p.base_card.isHidden()
    assert p.order.item(0).text().startswith('02') and len(p.plan.steps)==2
    p.camera.setCurrentText('TOP');p.camera_roll_right.click();p.apply_button.click()
    assert p.plan.camera_rolls=={'TOP':90}
    assert all(shared_camera_roll(p.plan,s)==90 for s in p.plan.steps)
    p._history(False);assert p.plan.camera_rolls=={}
    p._history(True);assert p.plan.camera_rolls=={'TOP':90}
    p.base_card.click();assert p.base_card.isChecked() and p.order.active_step_id=='base'
    assert not p.apply_button.isEnabled()
    _,db,projects,_=_runtime(tmp_path/'data');project=projects.create('shared','KD1','HVJB')
    service=PlanService(db);plan=copy.deepcopy(p.plan);plan.project_id=project.id
    service.save_draft(plan);loaded=service.load_current_draft(project.id)
    assert loaded.camera_rolls==plan.camera_rolls
    cid=service.confirm(plan);assert service.load_confirmation(cid).camera_rolls==plan.camera_rolls
    assert service.matches_confirmation(loaded,cid)
    loaded.camera_rolls={'TOP':180};assert not service.matches_confirmation(loaded,cid)
    legacy=copy.deepcopy(plan.to_dict());legacy.pop('camera_rolls')
    assert service._from_dict(legacy).camera_rolls=={}


def test_pending_common_roll_preview_does_not_mutate_plan(editor):
    p=editor;p.camera.setCurrentText('TOP');before=copy.deepcopy(p.plan.to_dict())
    p.camera_roll_right.click();p._preview_step()
    preview=p._step_preview['plan'];assert preview.camera_rolls=={'TOP':90}
    assert all(shared_camera_roll(preview,s)==90 for s in preview.steps)
    p._stop_preview();assert p.plan.to_dict()==before


@pytest.mark.parametrize('value',[45,360,True,-90])
def test_invalid_common_roll_rejected(value):
    plan=plan_fixture();plan.camera_rolls={'TOP':value}
    with pytest.raises(ValueError):plan.validate()
