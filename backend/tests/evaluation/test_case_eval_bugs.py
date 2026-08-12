"""EVAL_AGENT_REDESIGN_PLAN.md Phase 0 — 2번 섹션 버그 1~4 재현 테스트.

수정 전에는 아래 테스트가 실패해야 한다(버그 재현). 수정 후에는 전부 통과해야 한다.
전부 순수 함수 테스트라 DB·OpenAI 키가 필요 없다.
"""
from ai.agents.evaluation import case_eval
from ai.agents.evaluation.agent_bench import _is_drug_prescribed, _is_phrase_assertive


# ── 버그 1: _build_result가 ERROR를 무시하고 overall="OK"로 표시 ──────────

def test_build_result_does_not_report_ok_when_a_module_errors():
    triage_v = {
        "status": "ERROR",
        "checks": [{"item": "모듈 오류", "status": "ERROR", "detail": "boom"}],
    }
    schedule_v = {"status": "SKIPPED", "checks": []}
    chart_v = {"status": "SKIPPED", "checks": []}

    result = case_eval._build_result(triage_v, schedule_v, chart_v)

    assert result["overall"] != "OK"


# ── 버그 2: consistency_score가 SOAP 섹션 완전성 실패를 반영하지 못함 ────

def test_consistency_score_is_none_when_soap_section_check_warns():
    """SOAP만 WARN이어도 임의의 숫자(기존 버그: 10.0 유지) 대신 None이어야 한다."""
    triage_v = {"status": "SKIPPED", "checks": []}
    schedule_v = {"status": "SKIPPED", "checks": []}
    chart_v = {
        "status": "WARN",
        "checks": [
            {"item": "SOAP 섹션 완전성", "status": "WARN", "detail": "미흡 섹션: P(다음 단계 계획 없음)"},
            {"item": "임상 품질", "status": "PASS", "detail": "이상 없음"},
        ],
    }

    result = case_eval._build_result(triage_v, schedule_v, chart_v)

    assert result["consistency_score"] is None


def test_consistency_score_is_10_when_both_chart_checks_pass():
    """둘 다 PASS일 때만 기존 값(10.0)을 유지한다 — 이 값 자체는 건드리지 않음."""
    triage_v = {"status": "SKIPPED", "checks": []}
    schedule_v = {"status": "SKIPPED", "checks": []}
    chart_v = {
        "status": "PASS",
        "checks": [
            {"item": "SOAP 섹션 완전성", "status": "PASS", "detail": "충족"},
            {"item": "임상 품질", "status": "PASS", "detail": "이상 없음"},
        ],
    }

    result = case_eval._build_result(triage_v, schedule_v, chart_v)

    assert result["consistency_score"] == 10.0


# ── 버그 3: SOAP A/P 체크가 부정 문맥을 구분 못해 게임 가능 ──────────────

def test_check_soap_sections_rejects_negated_p_keyword():
    soap = {
        "S": "3일 전부터 구토와 식욕부진이 지속되어 상태를 지켜보다가 오늘 내원함",
        "O": "내원 시 촉진 상 복부 불편감 확인됨",
        "A": "급성 위장염 의심",
        "P": "검사는 필요 없습니다",
    }
    result = case_eval._check_soap_sections(soap)
    assert result["status"] == "WARN"
    assert "P" in result["detail"]


def test_check_soap_sections_passes_when_p_keyword_not_negated():
    """정상적인(부정되지 않은) 키워드는 여전히 PASS — 버그 수정이 정상 케이스를 깨지 않는지 확인."""
    soap = {
        "S": "3일 전부터 구토와 식욕부진이 지속되어 상태를 지켜보다가 오늘 내원함",
        "O": "내원 시 촉진 상 복부 불편감 확인됨",
        "A": "급성 위장염 의심",
        "P": "추가 혈액 검사와 재진을 권장함",
    }
    result = case_eval._check_soap_sections(soap)
    assert result["status"] == "PASS"


# ── 버그 4: 고정 윈도우 부정어 탐지 — 부정어가 키워드보다 앞/멀리 있으면 못 잡음 ──

def test_is_phrase_assertive_detects_negation_before_keyword():
    text = "확정 진단을 내리는 것은 어렵지만, 파보바이러스 장염으로 최종 진단합니다"
    assert _is_phrase_assertive(text, "파보바이러스 장염") is False


def test_is_phrase_assertive_detects_negation_beyond_fixed_window():
    text = (
        "검사 결과 종합적으로 판단할 때 이 소견은 파보바이러스 장염이 확실시되는 "
        "양상이나 최종 확진은 아님을 참고 바랍니다"
    )
    assert _is_phrase_assertive(text, "파보바이러스 장염") is False


def test_is_phrase_assertive_still_true_when_genuinely_assertive():
    text = "본 소견은 파보바이러스 장염으로 확정합니다"
    assert _is_phrase_assertive(text, "파보바이러스 장염") is True


def test_is_drug_prescribed_detects_negation_before_pattern():
    tip = "절대 투여 금지 사항이 있으니 참고하시고, 항생제 반응을 지켜봐 주세요"
    assert _is_drug_prescribed(tip, "항생제") is False


def test_is_drug_prescribed_still_true_when_genuinely_prescribed():
    tip = "항생제 처방을 시작하고 경과를 관찰하세요"
    assert _is_drug_prescribed(tip, "항생제") is True
