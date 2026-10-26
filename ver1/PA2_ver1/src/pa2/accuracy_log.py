"""Allowlisted, identifier-free performance summaries for deliberate sharing.

Never copy nested private log objects or free-form strings into this schema.
The random report ID is independent of project, generation and model IDs.
"""
from __future__ import annotations

import math


COUNT_FIELDS = (
    'tested_candidates', 'native_path_calls', 'actual_native_path_calls',
    'virtual_native_path_calls', 'pair_calculations', 'brep_common_calls',
    'brep_common_cache_hits', 'pair_cache_hits', 'exact_path_cache_hits',
    'blocked_witness_cache_hits', 'unique_states', 'closed_states',
    'state_visits', 'closed_state_skips', 'duplicate_group_skips', 'backtracks',
    'completed_groups', 'total_moving_groups', 'verified_path_steps',
    'unresolved_general_steps', 'fastener_assigned_steps', 'collision_exception_steps',
    'unknown_count', 'blocked_count', 'native_timeout_count', 'direction_hint_calls',
)
TIME_FIELDS = ('generation_wall_sec', 'elapsed_sec', 'native_path_elapsed_sec',
               'direction_hint_elapsed_sec', 'skeleton_elapsed_sec')
FLAG_FIELDS = ('draft_complete', 'path_complete', 'search_complete')
SCOPES = ('all', 'general', 'general_without_exceptions')
COMPARISON_COUNTS = ('count', 'pair_count', 'preserved_pairs', 'lcs_length',
                     'direction_same', 'direction_changed')
COMPARISON_RATIOS = ('pair_order_ratio', 'lcs_ratio', 'direction_agreement')
STATUSES = {'COMPLETE', 'REVIEW_REQUIRED', 'PARTIAL', 'NO_SOLUTION_WITHIN_BUDGET',
            'CANCELLED', 'FAILED'}
PLANNERS = {
    'general-first-fastener-insertion-v16': 'two_stage_general_first',
    'two-stage-learned-priority-v21': 'two_stage_general_first',
    'manual-v20-list-order': 'manual_list_order',
    'exterior-virtual-fastener-v1': 'exterior_general_first',
    'target-fastener-v1': 'target_fastener',
    'default': 'default_priority',
}
PROXY_VERSION = 'boundary-bvh-outside-proof-v1'
PROXY_ACTIVITIES = ('PROXY_BUILD', 'PROXY_PLANAR_BOUNDARY_BUILD',
                    'PROXY_CURVED_BOUNDARY_BUILD', 'PROXY_ORIGINAL_CLASSIFY',
                    'PROXY_FACE_SWEEP_CLEAR', 'PROXY_ENCLOSURE_CLEAR')


def _mapping(value):
    return value if type(value) is dict else {}


def _count(value):
    return type(value) is int and 0 <= value <= 2**63 - 1


def _real(value, maximum=1e12):
    return (type(value) in (int, float) and 0 <= value <= maximum
            and math.isfinite(value))


def _comparison(raw, initial_available):
    raw = _mapping(raw)
    result = {'available': False, 'scopes': {}}
    if not initial_available or raw.get('available') is not True:
        return result
    for scope in SCOPES:
        source = _mapping(raw.get(scope))
        if not _count(source.get('count')):
            continue
        values = {key: source[key] for key in COMPARISON_COUNTS
                  if _count(source.get(key))}
        for key in COMPARISON_RATIOS:
            value = source.get(key)
            if value is None:
                values[key] = None
            elif _real(value, 1):
                values[key] = value
        result['scopes'][scope] = values
    result['available'] = bool(result['scopes'])
    # Report quantities only, never IDs of newly added or removed components.
    for key in ('added_ids', 'removed_ids'):
        if type(raw.get(key)) is list:
            result[key.removesuffix('_ids') + '_count'] = len(raw[key])
    return result


def _algorithms(data):
    """Use observed successful inference, not model IDs or arbitrary version text."""
    source = _mapping(data.get('initial_plan')).get('source_algorithm')
    version = source if type(source) is str and source in PLANNERS else None
    planner = PLANNERS.get(version, 'unknown')
    manual = version == 'manual-v20-list-order'
    metrics = _mapping(data.get('metrics'))
    model_metrics = metrics.get('learning_models')
    predictions = {'ranking': 0, 'direction': 0}
    observed = {'ranking': False, 'direction': False}
    fallback = False
    # Fallback providers may themselves use a previously validated model pair.
    # Bound traversal; never copy IDs, failures or unrecognized nested objects.
    for _ in range(16):
        if type(model_metrics) is not dict:
            break
        values = _mapping(model_metrics.get('predictions'))
        for role in predictions:
            count = values.get(role)
            if _count(count) and predictions[role] + count <= 2**63 - 1:
                observed[role] = True
                predictions[role] += count
        if type(model_metrics.get('failures')) is list and model_metrics['failures']:
            fallback = True
        model_metrics = model_metrics.get('fallback')

    def recommendation(role):
        if manual:
            return dict(method='manual_fixed', prediction_calls=0, fallback_occurred=False)
        if observed[role]:
            method = 'LGBMRanker' if predictions[role] else 'rule_based'
            if predictions[role] and fallback:
                method = 'LGBMRanker_with_fallback'
            return dict(method=method, prediction_calls=predictions[role], fallback_occurred=fallback)
        if version and version != 'two-stage-learned-priority-v21':
            return dict(method='rule_based', prediction_calls=0, fallback_occurred=False)
        return dict(method='unknown', prediction_calls=None, fallback_occurred=fallback)

    observation = _mapping(data.get('algorithm_observations'))
    activities = _mapping(data.get('native_activity_counts'))
    activity = {key: activities[key] for key in PROXY_ACTIVITIES if _count(activities.get(key))}
    enabled = observation.get('shape_proxy_enabled')
    enabled = enabled if type(enabled) is bool else None
    if any(activity.values()):
        enabled = True
    proxy_version = observation.get('shape_proxy_version')
    proxy_version = PROXY_VERSION if type(proxy_version) is str and proxy_version == PROXY_VERSION else None
    cleared = any(activity.get(key, 0) > 0 for key in ('PROXY_FACE_SWEEP_CLEAR', 'PROXY_ENCLOSURE_CLEAR'))
    calls = metrics.get('actual_native_path_calls')
    missing = metrics.get('native_calls_without_counters')
    applied = (True if cleared else False if enabled is False or manual or
               (_count(calls) and calls == 0) or
               (enabled is True and _count(missing) and missing == 0) else None)
    optimization = dict(method='selective_conservative_proxy' if enabled is not None or proxy_version else 'unknown',
                        version=proxy_version, enabled=enabled, applied=applied)
    if manual:
        optimization = dict(method='not_applicable', version=None, enabled=None, applied=False)
    return dict(planner=planner, planner_version=version,
                recommendation_scope='general_parts_only',
                order_recommendation=recommendation('ranking'),
                direction_recommendation=recommendation('direction'),
                fastener_direction='geometry_axis_head_rule' if version else 'unknown',
                shape_optimization=optimization)


def performance_summary(private_log, report_id):
    """Construct a NEW object using fixed keys and strictly typed numeric values."""
    data = _mapping(private_log)
    metrics = _mapping(data.get('metrics'))
    performance = {key: metrics[key] for key in COUNT_FIELDS if _count(metrics.get(key))}
    performance.update({key: metrics[key] for key in TIME_FIELDS if _real(metrics.get(key))})
    performance.update({key: metrics[key] for key in FLAG_FIELDS if type(metrics.get(key)) is bool})
    initial_available = data.get('initial_available') is True
    confirmations = data.get('confirmations')
    confirmations = confirmations if type(confirmations) is list else []
    history = [dict(version=i + 1,
                    **_comparison(_mapping(row).get('comparison'), initial_available))
               for i, row in enumerate(confirmations)]
    accuracy = _comparison(_mapping(data.get('accuracy')).get('comparison'), initial_available)
    if history:
        accuracy = {key: value for key, value in history[-1].items() if key != 'version'}
    accuracy.update(kind='user_confirmation_similarity_not_physical_accuracy',
                    physical_accuracy=False, direction_tolerance_deg=1)
    if not accuracy['available']:
        accuracy['unavailable_reason'] = ('NO_BASELINE' if not initial_available else
                                         'NOT_CONFIRMED' if not history else 'COMPARISON_UNAVAILABLE')
    mode = data.get('generation_mode')
    status = data.get('status')
    # No private status/error text is propagated, even for failed attempts.
    status = status if type(status) is str and status in STATUSES else (
        'CONFIRMED' if history else 'GENERATED' if initial_available else 'UNAVAILABLE')
    return dict(schema_version='pa2-accuracy-log-v1', report_id=report_id,
                generation_mode=mode if type(mode) is str and mode in ('auto', 'manual') else 'unknown',
                status=status, performance=performance, accuracy=accuracy,
                confirmations=history, algorithms=_algorithms(data))
