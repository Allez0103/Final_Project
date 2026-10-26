from types import SimpleNamespace as NS
from pa2.domain.models import GeometryDecision,PathCheckResult
from pa2.ui.main_window import ModelPage


def render(paths):
    page=NS(result=NS(snapshot=NS(groups=[NS(id='part',display_name='Test part')])),
            diagnostics_button=NS(setEnabled=lambda _:None))
    result=NS(removal_order=[],metrics={'total_moving_groups':1},reason='test',path_results=paths)
    ModelPage.set_planning_diagnostics(page,result,'report.json')
    return page.diagnostics_text


def test_rejected_repair_limits_are_visible():
    result=PathCheckResult('part','state',(1,0,0),3,GeometryDecision.UNKNOWN,'PATH_UNKNOWN',
        evidence={'pair_diagnostics':[{'code':'INPUT_GEOMETRY_INVALID','obstacle_id':'part',
            'max_tolerance_after_mm':.00497,'epsilon_mm':.001,'volume_before_mm3':10,'volume_after_mm3':10.001}]})
    text=render([result])
    assert '0.0049700 mm' in text and '0.0010000 mm' in text and '보정 적용 안 함' in text


def test_clear_path_with_repair_is_not_hidden():
    result=PathCheckResult('part','state',(1,0,0),3,GeometryDecision.PASS,'CERTIFIED_CLEAR',
        evidence={'input_repairs':[{'group_id':'part','max_tolerance_after_mm':.0009}]})
    assert '계산용 파라미터 보정: Test part' in render([result])


def test_repair_limit_is_distinct_from_collision_epsilon():
    result=PathCheckResult('part','state',(1,0,0),3,GeometryDecision.UNKNOWN,'PATH_UNKNOWN',
        evidence={'pair_diagnostics':[{'code':'INPUT_GEOMETRY_INVALID','obstacle_id':'part',
            'max_tolerance_after_mm':.00497,'epsilon_mm':.001,'repair_max_tolerance_mm':.01,
            'volume_before_mm3':10,'volume_after_mm3':10.001}]})
    text=render([result])
    assert '기준 0.0100000 mm' in text


def test_decrease_review_limit_and_samples_are_visible():
    result=PathCheckResult('part','state',(0,0,1),3,GeometryDecision.PASS,'INITIAL_DECREASE_ALLOWED',
        evidence={'initial_decrease_exceptions':[{'obstacle_id':'part','initial_overlap_mm3':100,'pair_decision':'PASS'}],
                  'pair_diagnostics':[{'obstacle_id':'part','code':'INITIAL_DECREASE_SAMPLED',
                      'samples':[{'position_mm':0,'overlap_mm3':100},{'position_mm':.5,'overlap_mm3':0}]}]})
    text=render([result])
    assert '위치별 검사·검토용' in text
    assert '국소 충돌 배제 불가' in text
    assert '0.500/0.000000' in text


def test_decrease_rebound_and_failed_volume_are_visible():
    result=PathCheckResult('part','state',(0,0,1),3,GeometryDecision.BLOCKED,'PATH_BLOCKED',
        evidence={'pair_diagnostics':[{'obstacle_id':'part','code':'OVERLAP_REINCREASE',
            'samples':[{'position_mm':.1,'overlap_mm3':None}]}]})
    text=render([result])
    assert '초기 겹침 부피 재증가' in text
    assert '0.100/계산 실패' in text


def test_new_calculation_and_reuse_counters_are_separate():
    page=NS(result=NS(snapshot=NS(groups=[])),diagnostics_button=NS(setEnabled=lambda _:None))
    result=NS(removal_order=[],metrics={'total_moving_groups':1,'native_path_calls':12,
        'blocked_witness_cache_hits':31,'closed_state_skips':4,'group_evaluation_cache_hits':8,
        'elapsed_sec':9.5,'native_path_elapsed_sec':7.25},reason='test',path_results=[])
    ModelPage.set_planning_diagnostics(page,result,'report.json')
    assert '신규 경로 계산 요청: 12회 · 차단 근거 재사용: 31회' in page.diagnostics_text
    assert '중복 상태 건너뛰기: 4회 · 부품 판정 재사용: 8회' in page.diagnostics_text
    assert '전체 탐색 시간: 9.5초' in page.diagnostics_text
