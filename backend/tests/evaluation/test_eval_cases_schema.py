"""EVAL_AGENT_REDESIGN_PLAN.md Phase 1 — eval_cases/*.json 스키마 확장 검증.

lint_eval_cases.py는 JSON 파일을 직접 파싱해서 형식을 검사하지만, 이 테스트는
agent_bench.py가 실제로 쓰는 로더 함수(_load_triage_cases 등)를 그대로 호출해서
human_label/human_note 필드 추가 후에도 프로덕션 로드 경로가 정상 동작하는지
확인한다 — 파일 포맷과 로더 양쪽 모두 확인하는 것이 목적.

로더별로 parametrize해 파일 하나가 깨져도 그 파일의 테스트 노드만 개별
실패로 표시되게 한다 — 여러 파일이 동시에 깨져도 한 번에 전부 드러난다.
"""
import pytest

from ai.agents.evaluation import agent_bench

_LOADERS_AND_COUNTS = [
    (agent_bench._load_triage_cases, 40),
    (agent_bench._load_chart_cases, 20),
    (agent_bench._load_schedule_cases, 20),
    (agent_bench._load_followup_cases, 100),
    (agent_bench._load_orchestrator_cases, 23),
    (agent_bench._load_reception_cases, 20),
]
_LOADER_IDS = [loader.__name__ for loader, _ in _LOADERS_AND_COUNTS]


@pytest.mark.parametrize("loader,expected_count", _LOADERS_AND_COUNTS, ids=_LOADER_IDS)
def test_loader_returns_expected_case_count(loader, expected_count):
    cases = loader()
    assert len(cases) == expected_count


_VALID_LABELS = {"PASS", "FAIL", "SKIP"}


@pytest.mark.parametrize("loader,expected_count", _LOADERS_AND_COUNTS, ids=_LOADER_IDS)
def test_loader_cases_have_human_label_and_human_note_fields(loader, expected_count):
    """human_label/human_note 필드 존재 + (라벨링됐다면) 값 형식만 확인한다.

    Phase 2에서 라벨링이 진행 중이라 null(미라벨)과 PASS/FAIL/SKIP(라벨링 완료)이
    섞여 있는 게 정상 상태 — lint_eval_cases.py와 동일한 기준으로 검증한다.
    """
    cases = loader()
    for i, case in enumerate(cases):
        assert "human_label" in case, f"[{i}]: human_label 없음"
        assert "human_note" in case, f"[{i}]: human_note 없음"
        label = case["human_label"]
        assert label is None or label in _VALID_LABELS, f"[{i}]: human_label 값이 잘못됨 ({label!r})"
        if label is not None:
            assert case["human_note"], f"[{i}]: human_label={label}인데 human_note가 비어 있음"


def test_reception_cases_preserve_original_tool_expectations():
    """Reception 케이스 분리(코드 내 튜플 → JSON) 후에도 내용이 그대로인지 확인."""
    cases = agent_bench._load_reception_cases()
    by_name = {c["name"]: c for c in cases}

    assert by_name["병원 위치 질문"]["expected_tool"] == "get_hospital_info"
    assert by_name["예약 슬롯 질문"]["expected_tool"] == "find_open_slots"
    assert by_name["무관 질문(날씨)"]["expected_tool"] is None
    assert by_name["무관 질문(음식)"]["expected_tool"] is None
