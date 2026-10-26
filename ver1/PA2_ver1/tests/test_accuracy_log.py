import copy
import json
import uuid
from types import SimpleNamespace

import pytest

from pa2.accuracy_log import performance_summary
from pa2.application.plan_service import PlanService
from pa2.application.project_service import ProjectService
from pa2.domain.models import AssemblyGroup, Bounds, PartType, Plan, PlanStep, PlanningStatus
from pa2.run_log import RunLog
from pa2.settings.config import AppSettings
from pa2.storage.database import Database
from pa2.storage.layout import DataLayout


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv('PA2_INSTALL_ROOT', str(tmp_path / 'install'))
    database = Database(DataLayout(tmp_path / 'data'))
    database.initialize()
    project = ProjectService(database).create('PRIVATE_PROJECT', 'PRIVATE_VEHICLE', 'PRIVATE_PRODUCT')
    plan = Plan(str(uuid.uuid4()), project.id, 1, 'PRIVATE_BASE',
                ['PRIVATE_BASE', 'PRIVATE_A', 'PRIVATE_B'],
                [PlanStep('PRIVATE_A', 1, (0, 0, 1), (0, 0, -1), 10,
                          material_text='PRIVATE_MATERIAL', caution_text='PRIVATE_CAUTION'),
                 PlanStep('PRIVATE_B', 2, (1, 0, 0), (-1, 0, 0), 20)],
                PlanningStatus.REVIEW_REQUIRED)
    groups = [AssemblyGroup(g, g, [g], PartType.UNKNOWN, Bounds(0, 0, 0, 1, 1, 1), 1, None, True)
              for g in plan.group_ids]
    result = SimpleNamespace(assembly_plan=plan, path_results=[], metrics=dict(
        elapsed_sec=3.5, generation_wall_sec=4.0, tested_candidates=7,
        actual_native_path_calls=3, completed_groups=2, total_moving_groups=2,
        draft_complete=True, unknown_count=0,
        models_selected={'ranking': 'PRIVATE_MODEL'},
        unresolved_general_ids=['PRIVATE_A'], direction_hints=[{'secret': 'PRIVATE_HINT'}]))
    return database, PlanService(database), result, groups


def read_reports(tmp_path):
    return [json.loads(p.read_text(encoding='utf-8'))
            for p in (tmp_path / 'install/log/accuracy_log').glob('accuracy_*.json')]


def test_public_generation_and_confirmation_history(case, tmp_path):
    database, plans, result, groups = case
    plans.save_generated(result, AppSettings())
    before = read_reports(tmp_path)[0]
    assert before['performance']['generation_wall_sec'] == 4
    assert before['performance']['tested_candidates'] == 7
    assert not before['accuracy']['available']
    assert before['accuracy']['unavailable_reason'] == 'NOT_CONFIRMED'
    plan = result.assembly_plan
    cid = plans.confirm(plan)
    plans.analyze_confirmation(cid, groups)
    plans.analyze_confirmation(cid, groups)
    first = read_reports(tmp_path)[0]
    assert first['report_id'] == before['report_id']
    assert len(first['confirmations']) == 1
    assert first['accuracy']['scopes']['all']['pair_order_ratio'] == 1
    plan.steps.reverse()
    for i, step in enumerate(plan.steps, 1):
        step.step_index = i
    plan.steps[0].removal_direction = (0, 1, 0)
    plan.steps[0].assembly_direction = (0, -1, 0)
    plan.user_modified = True
    cid = plans.confirm(plan)
    plans.analyze_confirmation(cid, groups)
    reports = read_reports(tmp_path)
    assert len(reports) == 1
    public = reports[0]
    assert len(public['confirmations']) == 2
    assert public['accuracy']['scopes']['all']['pair_order_ratio'] == 0
    assert public['accuracy']['scopes']['all']['direction_agreement'] == .5
    assert not public['accuracy']['physical_accuracy']
    assert set(public['accuracy']['scopes']) == {'all', 'general', 'general_without_exceptions'}
    assert public['confirmations'][0]['scopes']['all']['pair_order_ratio'] == 1
    text = json.dumps(public)
    assert 'PRIVATE_' not in text and str(tmp_path) not in text
    for private_id in (plan.id, plan.project_id, cid, plans.generation(plan.id).id):
        assert private_id not in text and private_id.replace('-', '') not in text
    private = json.loads(next((tmp_path / 'install/log').glob('generation_*.json')).read_text(encoding='utf-8'))
    assert private['project']['name'] == 'PRIVATE_PROJECT'
    assert private['initial_plan']['steps'][0]['group_id'] == 'PRIVATE_A'
    assert len(private['confirmations']) == 2
    assert private['accuracy_report_id'] == public['report_id']


def test_only_allowlisted_types_and_keys_can_cross_boundary():
    raw = dict(initial_available=True, generation_mode='PRIVATE_MODE',
               status='PRIVATE_ERROR /home/secret', project={'name': 'PRIVATE_PROJECT'},
               settings={'url': 'PRIVATE_PASSWORD'}, created_at='PRIVATE_DATE',
               metrics=dict(elapsed_sec=float('nan'), generation_wall_sec=float('inf'),
                            tested_candidates='PRIVATE_COUNT', actual_native_path_calls=True,
                            brep_common_calls=-1, unknown_count=0, pair_calculations=10**100,
                            draft_complete='PRIVATE_BOOL', path_complete=False,
                            PRIVATE_FIELD='PRIVATE_PAYLOAD'),
               confirmations=[dict(confirmation_id='PRIVATE_ID', confirmed_at='PRIVATE_DATE',
                   comparison=dict(available=True, PRIVATE_SCOPE={'count': 100},
                       all=dict(count=2, pair_order_ratio=0.5, lcs_ratio='PRIVATE_RATIO',
                                direction_agreement=2, PRIVATE_FIELD='PRIVATE_PAYLOAD'),
                       added_ids=['PRIVATE_A'], removed_ids=['PRIVATE_B']))])
    before = copy.deepcopy(raw)
    public = performance_summary(raw, uuid.uuid4().hex)
    assert 'PRIVATE_' not in json.dumps(public, allow_nan=False)
    assert public['performance'] == {'unknown_count': 0, 'path_complete': False}
    assert public['generation_mode'] == 'unknown'
    assert public['status'] == 'CONFIRMED'
    assert public['accuracy']['scopes']['all'] == {'count': 2, 'pair_order_ratio': .5}
    assert public['accuracy']['added_count'] == public['accuracy']['removed_count'] == 1
    assert raw['confirmations'] == before['confirmations']


def test_no_baseline_does_not_fabricate_accuracy(case, tmp_path):
    _, plans, result, groups = case
    plans.confirm(result.assembly_plan)
    public = read_reports(tmp_path)[0]
    assert not public['accuracy']['available']
    assert public['accuracy']['unavailable_reason'] == 'NO_BASELINE'
    assert not public['confirmations'][0]['available']


@pytest.mark.parametrize('status', ['FAILED', 'CANCELLED', 'PRIVATE_ERROR'])
def test_failed_attempt_never_exports_free_text(status, tmp_path, monkeypatch):
    monkeypatch.setenv('PA2_INSTALL_ROOT', str(tmp_path / 'install'))
    logs = RunLog()
    path = logs.attempt('PRIVATE_PROJECT', 'manual', status, 1.25,
                        {'message': 'PRIVATE_PATH C:/secret/part.step', 'models_selected': 'PRIVATE_MODEL'})
    private = json.loads(path.read_text(encoding='utf-8'))
    public = read_reports(tmp_path)[0]
    assert 'PRIVATE_' not in json.dumps(public)
    assert private['attempt_id'] not in json.dumps(public)
    assert public['status'] == (status if status in ('FAILED', 'CANCELLED') else 'UNAVAILABLE')
    assert public['performance'] == {'generation_wall_sec': 1.25}
    assert not public['accuracy']['available']


def test_existing_log_export_idempotent_and_preserves_baseline(case, tmp_path):
    database, plans, result, _ = case
    plans.save_generated(result, AppSettings())
    root = tmp_path / 'install/log'
    private_path = next(root.glob('generation_*.json'))
    old = json.loads(private_path.read_text(encoding='utf-8'))
    original_plan = copy.deepcopy(old['initial_plan'])
    report = next((root / 'accuracy_log').glob('*.json'))
    report.unlink()  # Only the known generated test file; regeneration is expected.
    old.pop('accuracy_report_id')
    private_path.write_text(json.dumps(old), encoding='utf-8')
    (root / 'event_private.json').write_text('{"project":"PRIVATE_PROJECT"}', encoding='utf-8')
    (root / 'generation_bad.json').write_text('not JSON', encoding='utf-8')
    logs = RunLog(database)
    assert logs.export_existing() == {'exported': 1, 'failed': 1, 'skipped': 0}
    first = read_reports(tmp_path)
    assert logs.export_existing() == {'exported': 1, 'failed': 1, 'skipped': 0}
    assert read_reports(tmp_path) == first
    assert json.loads(private_path.read_text(encoding='utf-8'))['initial_plan'] == original_plan
    assert len(first) == 1


def test_accuracy_output_failure_keeps_private_save_and_can_retry(case, tmp_path):
    _, plans, result, _ = case
    root = tmp_path / 'install/log'
    root.mkdir(parents=True)
    block = root / 'accuracy_log'
    block.write_text('user data', encoding='utf-8')
    with pytest.warns(RuntimeWarning, match='LOG_WRITE_FAILED'):
        plans.save_generated(result, AppSettings())
    assert plans.load_original(result.assembly_plan.id)
    assert next(root.glob('generation_*.json')).exists()
    assert block.read_text(encoding='utf-8') == 'user data'
    block.rename(root / 'preserved-user-note.txt')
    plans.save_generated(result, AppSettings())
    assert len(read_reports(tmp_path)) == 1


def test_uninstall_manages_only_public_schema_in_known_folder(tmp_path):
    from pa2.uninstaller import inventory, build_plan, execute
    root = tmp_path / 'install'
    (root / '_internal').mkdir(parents=True)
    (root / 'PA2.exe').write_bytes(b'fixture')
    (root / 'uninst.exe').write_bytes(b'fixture')
    inventory(root)
    folder = root / 'log/accuracy_log'
    folder.mkdir(parents=True)
    managed = folder / 'accuracy_fixture.json'
    managed.write_text(json.dumps(performance_summary({}, uuid.uuid4().hex)), encoding='utf-8')
    note = folder / 'notes.json'
    note.write_text('{"user":"preserve"}', encoding='utf-8')
    unrelated = root / 'log/other'
    unrelated.mkdir()
    (unrelated / 'do-not-delete.json').write_text(managed.read_text(), encoding='utf-8')
    plan = build_plan(root)
    assert str(managed) in plan['files'] and str(note) not in plan['files']
    assert execute(root, plan['approval'])['ok']
    assert not managed.exists() and note.exists() and (unrelated / 'do-not-delete.json').exists()
