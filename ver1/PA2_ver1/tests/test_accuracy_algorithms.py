import json
import uuid
from types import SimpleNamespace

import pytest

from pa2.accuracy_log import performance_summary
from pa2.run_log import RunLog


def document(version='two-stage-learned-priority-v21', predictions=None):
    return dict(initial_available=True, generation_mode='auto',
                initial_plan={'source_algorithm': version},
                metrics={'learning_models': {'pinned_models': {'ranking': 'PRIVATE_MODEL'},
                         'predictions': predictions or {'ranking': 8, 'direction': 9},
                         'failures': [], 'fallback': None}},
                algorithm_observations={'shape_proxy_enabled': True,
                                        'shape_proxy_version': 'boundary-bvh-outside-proof-v1'},
                native_activity_counts={'PROXY_FACE_SWEEP_CLEAR': 5})


def algorithms(data):return performance_summary(data, uuid.uuid4().hex)['algorithms']


def test_learned_observed_roles_and_proxy_clearance():
    data = document()
    value = algorithms(data)
    assert value['planner_version'] == 'two-stage-learned-priority-v21'
    assert value['order_recommendation']['method'] == 'LGBMRanker'
    assert value['direction_recommendation']['prediction_calls'] == 9
    assert value['shape_optimization'] == dict(method='selective_conservative_proxy',
        version='boundary-bvh-outside-proof-v1', enabled=True, applied=True)
    assert 'PRIVATE_' not in json.dumps(value)


@pytest.mark.parametrize('role', ['ranking', 'direction'])
def test_selected_but_unused_model_is_not_reported_as_used(role):
    data = document(predictions={role: 0, 'direction' if role == 'ranking' else 'ranking': 2})
    name = 'order_recommendation' if role == 'ranking' else 'direction_recommendation'
    assert algorithms(data)[name] == dict(method='rule_based', prediction_calls=0, fallback_occurred=False)


def test_fallback_chain_counts_successes_without_exporting_ids_or_errors():
    data = document()
    model = data['metrics']['learning_models']
    model['failures'] = [{'model_id': 'PRIVATE_ID', 'error': 'PRIVATE_ERROR C:/secret'}]
    model['fallback'] = {'pinned_models': {'direction': 'PRIVATE_FALLBACK'},
                         'predictions': {'ranking': 3, 'direction': 4}, 'failures': []}
    result = algorithms(data)
    assert result['order_recommendation'] == dict(method='LGBMRanker_with_fallback',
                                                 prediction_calls=11, fallback_occurred=True)
    assert result['direction_recommendation']['prediction_calls'] == 13
    assert 'PRIVATE_' not in json.dumps(result)


def test_rule_and_manual_without_model_ids():
    rule = document('general-first-fastener-insertion-v16')
    rule['metrics']['learning_models'] = None
    assert algorithms(rule)['order_recommendation']['method'] == 'rule_based'
    manual = document('manual-v20-list-order')
    manual['generation_mode'] = 'manual'
    result = algorithms(manual)
    assert result['direction_recommendation']['method'] == 'manual_fixed'
    assert result['order_recommendation']['prediction_calls'] == 0
    assert result['shape_optimization']['method'] == 'not_applicable'
    assert result['shape_optimization']['applied'] is False


def test_unknown_and_malicious_versions_are_not_copied():
    data = document('PRIVATE_PROJECT_VERSION')
    data['metrics']['learning_models'] = {'predictions': {'ranking': 'PRIVATE_ID', 'direction': True},
                                         'PRIVATE_MODEL': {'id': 'PRIVATE_ID'}}
    data['algorithm_observations'] = {'shape_proxy_enabled': 'PRIVATE_BOOL',
                                     'shape_proxy_version': 'PRIVATE_PATH'}
    data['native_activity_counts'] = {'PROXY_FACE_SWEEP_CLEAR': 'PRIVATE_COUNT',
                                     'PRIVATE_KEY': 100}
    result = algorithms(data)
    assert result['planner_version'] is None
    assert result['order_recommendation']['method'] == 'unknown'
    assert result['shape_optimization']['enabled'] is None
    assert result['shape_optimization']['applied'] is None
    assert 'PRIVATE_' not in json.dumps(result)
    assert algorithms({})['order_recommendation']['method'] == 'unknown'


@pytest.mark.parametrize('enabled,missing,expected', [(False, 0, False), (True, 0, False), (True, 1, None)])
def test_enabled_does_not_imply_optimization_was_applied(enabled, missing, expected):
    data = document()
    data['algorithm_observations']['shape_proxy_enabled'] = enabled
    data['native_activity_counts'] = {}
    data['metrics'].update(actual_native_path_calls=1, native_calls_without_counters=missing)
    assert algorithms(data)['shape_optimization']['applied'] is expected


def test_legacy_positive_activity_is_evidence_but_version_is_unknown():
    data = document()
    data.pop('algorithm_observations')
    result = algorithms(data)['shape_optimization']
    assert result['enabled'] is True and result['applied'] is True
    assert result['version'] is None


def test_generated_log_captures_native_observation_and_reexport_is_stable(tmp_path, monkeypatch):
    monkeypatch.setenv('PA2_INSTALL_ROOT', str(tmp_path))
    data = document()
    generation = SimpleNamespace(id=str(uuid.uuid4()), project_id='PRIVATE_PROJECT',
        plan_id='PRIVATE_PLAN', snapshot_id='PRIVATE_SNAPSHOT', generation_mode='auto',
        plan_snapshot_json=data['initial_plan'], metrics_json=data['metrics'], settings_json={},
        path_results_json=[dict(evidence=dict(evaluation_source='native', calculation_metrics=dict(
            activity_counts=data['native_activity_counts'],
            spatial_proxy={'enabled': True, 'version': 'boundary-bvh-outside-proof-v1',
                           'profiles': [{'shape_key': 'PRIVATE_GEOMETRY'}]})))])
    logs = RunLog()
    path = logs.generated(generation)
    private = json.loads(path.read_text(encoding='utf-8'))
    assert private['algorithm_observations']['shape_proxy_enabled'] is True
    public = next((tmp_path/'log/accuracy_log').glob('*.json'))
    first = public.read_bytes()
    assert json.loads(first)['algorithms']['shape_optimization']['applied'] is True
    assert b'PRIVATE_' not in first
    assert logs.export_existing()['exported'] == 1
    assert public.read_bytes() == first
