import copy
import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture
def imported(tmp_path):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from OCP.STEPControl import STEPControl_Writer,STEPControl_AsIs
    from pa2.cad.shapes import compound
    from pa2.cli import _runtime
    from pa2.settings.config import AppSettings
    def box(x,size):return BRepPrimAPI_MakeBox(gp_Pnt(x,0,0),size,1,1).Shape()
    def write(path,shapes):
        writer=STEPControl_Writer();writer.Transfer(compound(shapes),STEPControl_AsIs);writer.Write(str(path))
    assembly=tmp_path/'assembly.step';part=tmp_path/'AUTO.step'
    write(assembly,[box(0,1),box(3,2),box(7,3),box(12,4),box(18,5)])
    write(part,[box(3,2),box(7,3)])
    layout,db,projects,imports=_runtime(tmp_path/'data');project=projects.create('수동 그룹 시험','test','test')
    result=imports.prepare(project.id,assembly,[part],AppSettings())
    from pa2.domain.models import MatchingStatus
    auto=next(g for g in result.snapshot.groups if g.matching_status==MatchingStatus.MATCHED)
    assert len(auto.body_ids)==2
    raw=sorted((g for g in result.snapshot.groups if g.id!=auto.id),key=lambda g:g.volume_mm3)
    return SimpleNamespace(layout=layout,db=db,projects=projects,imports=imports,result=result,project=project,auto=auto,raw=raw)


def test_manual_group_reopen_ungroup_automatic_lock_and_old_confirmation(imported):
    from pa2.application.manual_grouping import ManualGroupingService
    from pa2.application.plan_service import PlanService
    from pa2.domain.models import Plan,PlanStep,PlanningStatus
    from pa2.storage.database import Project
    t=imported;original=t.result.snapshot;service=ManualGroupingService(t.db);plans=PlanService(t.db)
    base=t.raw[0].id
    plan=Plan('old',t.project.id,1,base,[g.id for g in original.groups],
        [PlanStep(g.id,i,(0,0,1),(0,0,-1),10) for i,g in enumerate((g for g in original.groups if g.id!=base),1)],
        PlanningStatus.REVIEW_REQUIRED,input_snapshot_id=original.id)
    cid=plans.confirm(plan);before=plans.load_confirmation(cid).to_dict()
    with pytest.raises(ValueError,match='자동 그룹'):
        service.change(t.result,[t.auto.id],ungroup=True,base_id=base)
    with pytest.raises(ValueError,match='기준 부품'):
        service.change(t.result,[base,t.auto.id],name='bad',base_id=base)
    selected=[t.auto.id,t.raw[1].id]
    sid=service.change(t.result,selected,name='선택한 조립체',base_id=base,exception_ids=[t.auto.id])
    new=t.imports.reopen(t.project.id);manual=next(g for g in new.snapshot.groups if g.id.startswith('manual-'))
    assert sid==new.snapshot.id and manual.display_name=='선택한 조립체'
    assert len(manual.body_ids)==3 and len(new.snapshot.groups)==3
    assert len(set(b for g in new.snapshot.groups for b in g.body_ids))==5
    assert plans.load_preset(t.project.id,sid)['exception_ids']==[manual.id]
    with t.db.session() as session:
        row=session.get(Project,t.project.id)
        assert row.current_draft_plan_id is None and row.current_confirmation_id is None
    assert plans.load_confirmation(cid).to_dict()==before
    with pytest.raises(ValueError,match='다시 생성'):plans.save_draft(plan)
    with pytest.raises(ValueError,match='다시 불러오세요'):
        service.change(t.result,selected,name='stale',base_id=base)
    service.change(new,[manual.id],ungroup=True,base_id=base,exception_ids=[manual.id])
    restored=t.imports.reopen(t.project.id)
    locked=next(g for g in restored.snapshot.groups if g.id==t.auto.id)
    assert locked.body_ids==t.auto.body_ids and locked.matching_status==t.auto.matching_status
    assert {g.id for g in restored.snapshot.groups}=={g.id for g in original.groups}
    assert plans.load_preset(t.project.id,restored.snapshot.id)['exception_ids']==[t.auto.id]
    assert restored.snapshot.assembly_asset_hash==original.assembly_asset_hash
    assert set(restored.assembly_scene.shapes)==set(t.result.assembly_scene.shapes)


def test_contact_aggregation_and_nested_manual_group_undo(imported):
    from pa2.application.manual_grouping import ManualGroupingService
    from pa2.storage.database import ContactRecord
    t=imported;sid=t.result.snapshot.id;base,a,b=[g.id for g in t.raw];auto=t.auto.id
    with t.db.session() as session:
        session.query(ContactRecord).filter_by(snapshot_id=sid).delete()
        for left,right,distance in [(base,a,.01),(base,b,.03),(a,b,0),(auto,a,.02)]:
            session.add(ContactRecord(pair_id=sid+':'+left+'::'+right,snapshot_id=sid,group_a=left,
                group_b=right,distance_mm=distance,evidence_json={},policy_version='test'))
    original=t.imports.reopen(t.project.id);service=ManualGroupingService(t.db)
    service.change(original,[a,b],name='inner',base_id=base)
    inner=t.imports.reopen(t.project.id);group=next(g for g in inner.snapshot.groups if g.id.startswith('manual-'))
    assert len(inner.snapshot.contacts)==2
    edge=next(e for e in inner.snapshot.contacts if base in (e.group_a,e.group_b))
    assert edge.distance_mm==.01 and group.id in (edge.group_a,edge.group_b)
    service.change(inner,[group.id,auto],name='outer',base_id=base)
    outer=t.imports.reopen(t.project.id);outer_id=next(g.id for g in outer.snapshot.groups if g.id.startswith('manual-'))
    service.change(outer,[outer_id],ungroup=True,base_id=base)
    unwrapped=t.imports.reopen(t.project.id)
    assert {g.id for g in unwrapped.snapshot.groups}=={base,auto,group.id}
    service.change(unwrapped,[group.id],ungroup=True,base_id=base)
    restored=t.imports.reopen(t.project.id)
    assert sorted((e.pair_id,e.distance_mm) for e in restored.snapshot.contacts)==sorted((e.pair_id,e.distance_mm) for e in original.snapshot.contacts)


def test_group_dialog_only_selected_names_and_no_direction(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication,QComboBox
    from pa2.ui.group_dialog import ManualGroupDialog
    app=QApplication.instance() or QApplication([])
    dialog=ManualGroupDialog([SimpleNamespace(display_name=name) for name in ['선택1','선택2','선택1']])
    assert [dialog.name.itemText(i) for i in range(dialog.name.count())]==['선택1','선택2']
    assert dialog.findChildren(QComboBox)==[dialog.name]
    dialog.name.setEditText('직접 지정');assert dialog.group_name()=='직접 지정'
    dialog.close()


def test_confirmation_fingerprint_survives_db_roundtrip_and_rejects_all_edits(tmp_path):
    from pa2.cli import _runtime
    from pa2.application.plan_service import PlanService
    from pa2.domain.models import Plan,PlanStep,PlanningStatus
    _,db,projects,_=_runtime(tmp_path/'data');project=projects.create('confirm','t','t');service=PlanService(db)
    plan=Plan('p',project.id,1,'base',['base','a','b'],[
        PlanStep('a',1,(1,0,0),(-1,0,0),10),PlanStep('b',2,(0,0,1),(0,0,-1),12)],PlanningStatus.REVIEW_REQUIRED)
    cid=service.confirm(plan);loaded=service.load_current_draft(project.id)
    assert service.matches_confirmation(loaded,cid)
    for field,value in [('travel_mm',11),('camera_mode','TOP'),('process_text','new'),('material_text','new'),
                        ('caution_text','new'),('removal_direction',(0,1,0)),('assembly_direction',(0,-1,0))]:
        changed=copy.deepcopy(loaded);setattr(changed.steps[0],field,value)
        assert not service.matches_confirmation(changed,cid)
    changed=copy.deepcopy(loaded);changed.steps.reverse()
    for i,step in enumerate(changed.steps,1):step.step_index=i
    assert not service.matches_confirmation(changed,cid)
    service.save_draft(changed)
    assert not service.matches_confirmation(service.load_current_draft(project.id),cid)
    assert service.load_confirmation(cid).steps[0].group_id=='a'


def test_cleanup_keeps_latest_valid_and_preserves_invalid_exports_and_other_projects(tmp_path):
    import imageio_ffmpeg
    from pa2.cli import _runtime
    from pa2.application.plan_service import PlanService
    from pa2.application.video_library import VideoLibrary,complete_video
    from pa2.domain.models import Plan,PlanStep,PlanningStatus
    layout,db,projects,_=_runtime(tmp_path/'data');plans=PlanService(db)
    project=projects.create('videos','t','t');other=projects.create('other','t','t')
    def confirm(p):return plans.confirm(Plan('plan-'+p.id,p.id,1,'base',['base','a'],
        [PlanStep('a',1,(0,0,1),(0,0,-1),10)],PlanningStatus.REVIEW_REQUIRED))
    cid=confirm(project);other_cid=confirm(other)
    fixture=tmp_path/'small.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=10',
        '-t','1','-c:v','libx264','-pix_fmt','yuv420p',str(fixture)],check=True,capture_output=True)
    assert complete_video(fixture)
    directory=layout.projects/project.id/'videos';directory.mkdir(parents=True)
    old=directory/f'{cid}-00000001.mp4';latest=directory/f'{cid}-00000002.mp4'
    for path,stamp in [(old,100),(latest,200)]:shutil.copy2(fixture,path);os.utime(path,(stamp,stamp))
    invalid=directory/f'{cid}-00000003.mp4';invalid.write_bytes(b'failed');os.utime(invalid,(300,300))
    exported=directory/'exported.mp4';shutil.copy2(fixture,exported)
    partial=directory/f'.{cid}.tmp.mp4';shutil.copy2(fixture,partial)
    foreign=directory/f'{other_cid}-00000001.mp4';shutil.copy2(fixture,foreign)
    otherdir=layout.projects/other.id/'videos';otherdir.mkdir(parents=True)
    otherfile=otherdir/f'{other_cid}.mp4';shutil.copy2(fixture,otherfile)
    exported_copy=tmp_path/'separate-export.mp4';shutil.copy2(fixture,exported_copy)
    size=old.stat().st_size;result=VideoLibrary(db,layout).keep_latest(project.id)
    assert result['kept']==str(latest.resolve()) and result['deleted']==[old.name]
    assert result['freed_bytes']==size and not result['errors']
    assert not old.exists() and all(p.exists() for p in [latest,invalid,exported,partial,foreign,otherfile,exported_copy])
    again=VideoLibrary(db,layout).keep_latest(project.id)
    assert again['deleted']==[] and again['freed_bytes']==0
    with pytest.raises(ValueError):VideoLibrary(db,layout).keep_latest('../escape')


def test_video_cleanup_no_valid_output_never_deletes(tmp_path):
    from pa2.cli import _runtime
    from pa2.application.video_library import VideoLibrary
    layout,db,projects,_=_runtime(tmp_path/'data');project=projects.create('empty','t','t')
    directory=layout.projects/project.id/'videos';directory.mkdir(parents=True)
    arbitrary=directory/'old.mp4';arbitrary.write_bytes(b'not-a-video')
    result=VideoLibrary(db,layout).keep_latest(project.id)
    assert result=={'kept':None,'deleted':[],'freed_bytes':0,'errors':[]}
    assert arbitrary.exists()
