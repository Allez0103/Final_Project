import copy
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from pa2.domain.models import (AssemblyGroup, Bounds, ContactEdge, GeometryDecision,
    GeometryStatus, PartType, Plan, PlanningResult, PlanningStatus, PlanStep)
from pa2.settings.config import AppSettings


def group(gid, x=0, part_type=PartType.BLOCK, body_ids=None):
    return AssemblyGroup(gid, gid, body_ids or [gid], part_type,
                         Bounds(x, 0, 0, x+1, 1, 1), 1., (x+.5, .5, .5), True)


def test_manual_list_order_shared_fasteners_groups_and_zero_cad_search(monkeypatch):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from pa2.planning.manual import ManualPlanner
    from pa2.cad.contacts import ContactService
    from pa2.cad.path_check import ConservativePathChecker
    from pa2.jobs.isolated import IsolatedCadWorker
    def forbidden(*_, **__):
        pytest.fail('Manual generation invoked contact/path/native search')
    for cls, method in [(ContactService, 'build'), (ConservativePathChecker, 'check'),
                        (IsolatedCadWorker, 'call')]:
        monkeypatch.setattr(cls, method, forbidden)
    groups = [group('base'), group('a', 2, body_ids=['a1', 'a2']), group('b', 4),
              group('bolt', 3, PartType.BOLT), group('nut', 5, PartType.NUT),
              group('orphan', 6, PartType.BOLT)]
    shapes = {b: BRepPrimAPI_MakeBox(1, 1, 1).Shape() for g in groups for b in g.body_ids}
    shapes['bolt'] = shapes['nut'] = shapes['orphan'] = BRepPrimAPI_MakeCylinder(1, 3).Shape()
    contacts = [ContactEdge('a', 'bolt', 0), ContactEdge('b', 'bolt', 0),
                ContactEdge('bolt', 'nut', 0)]
    result = ManualPlanner(AppSettings()).generate('p', 1, 's', groups, contacts, shapes, 'base',
        display_order=['bolt', 'b', 'base', 'a', 'nut', 'orphan'], collision_exception_ids=['b'])
    plan = result.assembly_plan
    assert [s.group_id for s in plan.steps] == ['orphan', 'b', 'a', 'bolt', 'nut']
    assert result.metrics['native_path_calls'] == result.metrics['tested_candidates'] == 0
    assert result.metrics['general_assembly_order'] == ['b', 'a']
    assert len(plan.steps) == 5 and all(p.decision == GeometryDecision.NOT_TESTED for p in result.path_results)
    assert plan.steps[1].geometry_status == GeometryStatus.USER_COLLISION_EXCEPTION
    assert plan.steps[2].geometry_status == GeometryStatus.MANUAL_ASSIGNED
    assert plan.steps[2].removal_direction == (0, 0, 1)
    plan.validate()
    with pytest.raises(InterruptedError):
        ManualPlanner(AppSettings()).generate('p', 1, 's', groups, contacts, shapes,
                                              'base', cancel_check=lambda: True)
    with pytest.raises(ValueError):
        ManualPlanner(AppSettings()).generate('p', 1, 's', groups, contacts, shapes,
                                              'base', display_order=['base'])


def test_original_immutable_metrics_exception_capture_dedup_and_training_guard(tmp_path):
    from pa2.cli import _runtime
    from pa2.application.plan_service import PlanService
    from pa2.learning.collection import collect_confirmation, learning_status
    from pa2.learning.offline import train_recorded
    from pa2.storage.database import GenerationRecord, ConfirmationAnalysis, LearningObservation, RankingState
    layout, db, projects, _ = _runtime(tmp_path/'data')
    project = projects.create('test', 'KD1', 'HVJB'); plans = PlanService(db)
    groups = [group('base'), group('a', 2), group('b', 4), group('bolt', 6, PartType.BOLT)]
    plan = Plan('plan', project.id, 1, 'base', [g.id for g in groups], [
        PlanStep('a', 1, (0, 0, 1), (0, 0, -1), 10, geometry_status=GeometryStatus.USER_COLLISION_EXCEPTION),
        PlanStep('b', 2, (0, 0, 1), (0, 0, -1), 10),
        PlanStep('bolt', 3, (0, 0, 1), (0, 0, -1), 10, geometry_status=GeometryStatus.FASTENER_ASSIGNED)],
        PlanningStatus.REVIEW_REQUIRED, input_snapshot_id='s')
    result = PlanningResult(plan.status, ['bolt', 'b', 'a'], plan, [],
                            metrics={'collision_exception_ids': ['a'], 'native_path_calls': 0})
    plans.save_generated(result, AppSettings()); original = plans.load_original('plan').to_dict()
    imported = SimpleNamespace(snapshot=SimpleNamespace(id='s', groups=groups, contacts=[],
                                                        assembly_asset_hash='family'))
    plan.steps[0], plan.steps[1] = plan.steps[1], plan.steps[0]
    plan.steps[0].removal_direction = (1, 0, 0); plan.steps[0].assembly_direction = (-1, 0, 0)
    plan.user_modified = True
    cid = plans.confirm(plan)
    captured = collect_confirmation(db, plans, cid, imported, 'HVJB')
    assert plans.load_original('plan').to_dict() == original
    assert captured['comparison']['all']['preserved_pairs'] == 2
    assert captured['comparison']['general']['lcs_length'] == 1
    assert captured['comparison']['general']['direction_changed'] == 1
    assert captured['comparison']['general_without_exceptions']['count'] == 1
    assert plans.load_confirmation(cid).steps[1].geometry_status == GeometryStatus.USER_COLLISION_EXCEPTION
    cid2 = plans.confirm(plan); collect_confirmation(db, plans, cid2, imported, 'HVJB')
    with db.session() as session:
        assert session.query(GenerationRecord).count() == 1
        assert session.query(ConfirmationAnalysis).count() == 2
        assert session.query(LearningObservation).count() == 1
        assert session.query(RankingState).count() == 1
        observation = session.query(LearningObservation).one().payload_json
        assert len(observation['steps']) == 3 and observation['exception_ids'] == ['a']
        assert all(not s['confirmed_geometry_pass'] for s in observation['steps'])
    assert not learning_status(db, AppSettings())['ready']
    with pytest.raises(ValueError, match='학습 보류'):
        train_recorded(db, AppSettings(), tmp_path/'model')
    assert not (tmp_path/'model').exists()


def test_color_metadata_whole_face_majority_and_cache(tmp_path):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Quantity import Quantity_Color, Quantity_TOC_sRGB
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorSurf
    from pa2.cad.importer import StepImporter
    from pa2.cad.brep_cache import save_scene, load_scene
    doc = TDocStd_Document(TCollection_ExtendedString('BinXCAF'))
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main()); ct = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    shape = BRepPrimAPI_MakeBox(4, 2, 1).Shape(); label = st.AddShape(shape, False)
    red = Quantity_Color(.9, .1, .2, Quantity_TOC_sRGB)
    blue = Quantity_Color(.1, .2, .9, Quantity_TOC_sRGB)
    ct.SetColor(label, red, XCAFDoc_ColorSurf)
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        ct.SetColor(st.AddSubShape(label, explorer.Current()), blue, XCAFDoc_ColorSurf)
        explorer.Next()
    path = tmp_path/'colored.step'
    writer = STEPCAFControl_Writer(); writer.SetColorMode(True)
    assert writer.Transfer(doc, STEPControl_AsIs)
    assert writer.Write(str(path)) == IFSelect_RetDone
    progress = []
    scene = StepImporter().read(path, 'hash', 'source', progress=lambda *p: progress.append(p))
    assert not any('생략' in p[1] for p in progress), progress
    assert scene.bodies[0].color_rgb == pytest.approx((.9, .1, .2), abs=1e-5)
    cache = tmp_path/'cache'; cache.mkdir(); save_scene(scene, cache)
    assert load_scene(cache, path).bodies[0].color_rgb == pytest.approx((.9, .1, .2), abs=1e-5)
    # Face-only styles: two 8mm² faces blue, remaining 24mm² red => red wins.
    ct.UnSetColor(label, XCAFDoc_ColorSurf)
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    for i in range(6):
        ct.SetColor(st.AddSubShape(label, explorer.Current()), red if i < 4 else blue, XCAFDoc_ColorSurf)
        explorer.Next()
    writer = STEPCAFControl_Writer(); writer.SetColorMode(True); writer.Transfer(doc, STEPControl_AsIs)
    writer.Write(str(tmp_path/'faces.step'))
    scene = StepImporter().read(tmp_path/'faces.step', 'faces', 'source')
    assert scene.bodies[0].color_rgb == pytest.approx((.1, .2, .9), abs=1e-5)  # 16 > 12 mm²


def test_red_selection_fade_restore_and_video_color(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from pa2.cad.importer import CadScene
    from pa2.rendering.vtk_scene import VtkScene
    from pa2.rendering.scene import build_timeline, scene_at
    app = QApplication.instance() or QApplication([])
    groups = [group('base'), group('a', 2)]
    scene = CadScene(Path('test'), 'h', 's', 'mm', [
        SimpleNamespace(id=g.id, bounds=g.bounds, area_mm2=1, color_rgb=(.2, .7, .4)) for g in groups],
        {g.id: BRepPrimAPI_MakeBox(1, 1, 1).Shape() for g in groups})
    vtk = VtkScene(offscreen=True)
    try:
        vtk.load(scene, groups)
        vtk.actors['base'].GetProperty().SetOpacity(.6)
        vtk.highlight({'a'})
        assert vtk.actors['a'].GetProperty().GetColor() == (1, 0, 0)
        assert vtk.actors['base'].GetProperty().GetOpacity() == .25
        vtk.highlight(set())
        assert vtk.actors['base'].GetProperty().GetOpacity() == .6
        assert vtk.actors['a'].GetProperty().GetColor() == (.2, .7, .4)
        plan = Plan('p', 'pr', 1, 'base', ['base', 'a'], [PlanStep('a', 1, (0, 0, 1), (0, 0, -1), 10)], PlanningStatus.REVIEW_REQUIRED)
        settings = AppSettings(); timeline = build_timeline(plan, settings); segment = timeline.segments[0]
        for t, expected in [(segment.camera_end+.01, (1, 0, 0)),
                            (segment.camera_end+.26, (.2, .7, .4)),
                            (segment.highlight_end+.1, (1, 0, 0)),
                            (timeline.duration, (.2, .7, .4))]:
            vtk.apply(scene_at(plan, t, settings, timeline))
            assert vtk.actors['a'].GetProperty().GetColor() == pytest.approx(expected)
            assert vtk.actors['base'].GetProperty().GetOpacity() == 1.
    finally:
        vtk.render_window.Finalize()


def test_geometric_family_key_ignores_names_translation_and_manual_groups():
    from dataclasses import replace
    from pa2.learning.collection import family_fingerprint
    bodies = [group('x', 0), group('y', 2)]
    a = SimpleNamespace(atomic_bodies=bodies, groups=bodies)
    moved = [replace(b, id='renamed'+b.id, display_name='different',
                     bounds=b.bounds.translated((10,20,30)),
                     centroid=tuple(v+d for v,d in zip(b.centroid,(10,20,30)))) for b in bodies]
    b = SimpleNamespace(atomic_bodies=moved, groups=[group('manual')])
    assert family_fingerprint(a) == family_fingerprint(b)
    moved[1].volume_mm3 = 2
    assert family_fingerprint(a) != family_fingerprint(b)


def test_offline_pilot_separates_families_and_never_activates_synthetic_model(tmp_path):
    from pa2.cli import _runtime
    from pa2.learning.ranker import LearningService
    from pa2.learning.offline import train_recorded
    from pa2.storage.database import ActiveModel
    _, db, _, _ = _runtime(tmp_path/'synthetic-data')
    for i in range(10):
        groups = [group('base'), group('a', i+2), group('b', i+5), group('c', i+9)]
        plan = Plan('p'+str(i),'project',1,'base',[g.id for g in groups],
            [PlanStep(gid,n,(0,0,1),(0,0,-1),10) for n,gid in enumerate(['a','b','c'],1)],
            PlanningStatus.REVIEW_REQUIRED)
        LearningService().capture(db,confirmation_id='synthetic-'+str(i),family_id='synthetic-family-'+str(i),
            plan=plan,groups=groups,contacts=[],product_type='SYNTHETIC_TEST_ONLY')
    result = train_recorded(db,AppSettings(),tmp_path/'synthetic-model',pilot=True)
    assert not set(result['training_families']) & set(result['held_out_families'])
    assert not result['auto_activated'] and not result['deployment_approved']
    assert (tmp_path/'synthetic-model/evaluation.json').is_file()
    with db.session() as session:
        assert session.get(ActiveModel,'ranking').model_bundle_id is None
