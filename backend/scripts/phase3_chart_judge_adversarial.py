"""Phase 3 2차 시도 — 조작된(일부러 망가뜨린) 결과물에 judge 채점.

생성 LLM 호출 없이, 1차 시도의 실제 생성 결과를 복사해 특정 필드만 직접
수정한다. judge 호출만 5회(A·B·C 조작 3개 + 대조군 2개), 순차 실행.
"""
import asyncio
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, "/app")

from ai.agents.evaluation.case_eval import _check_chart_quality

CASES_PATH = "/app/ai/agents/eval_cases/chart_eval_cases.json"
CALIBRATION_PATH = "/app/ai/agents/eval_cases/chart_judge_calibration.json"
OUT_PATH = Path("/app/ai/agents/eval_cases/chart_judge_adversarial.json")


def make_triage_obj(triage_dict):
    return SimpleNamespace(
        urgency_level=triage_dict.get("urgency_level"),
        urgency_level_num=None,
        chief_complaint=triage_dict.get("symptom_summary")
        or ", ".join(triage_dict.get("symptom_keywords") or []),
    )


async def judge_one(entry_type, case_name, triage_dict, draft, tamper_note):
    triage_obj = make_triage_obj(triage_dict)
    intake = draft.get("intake_summary") or {}
    try:
        judge = await _check_chart_quality(triage_obj, draft, intake)
    except Exception as exc:
        print(f"ABORT: {case_name} -> judge 예외: {exc}", file=sys.stderr)
        return {"type": entry_type, "case_name": case_name, "tamper_note": tamper_note, "error": str(exc)}, True

    result = {
        "type": entry_type,
        "case_name": case_name,
        "tamper_note": tamper_note,
        "urgency_level": triage_dict.get("urgency_level"),
        "soap_S": draft.get("soap", {}).get("S"),
        "soap_A": draft.get("soap", {}).get("A"),
        "differential_diagnosis": [d.get("disease") for d in (draft.get("differential_diagnosis") or [])],
        "judge_status": judge.get("status"),
        "judge_detail": judge.get("detail"),
    }
    abort = judge.get("status") == "SKIPPED"
    if abort:
        print(f"ABORT: {case_name} -> judge_status=SKIPPED", file=sys.stderr)
    else:
        print(f"OK: {case_name} ({entry_type}) -> judge={judge.get('status')}", file=sys.stderr)
    return result, abort


async def main():
    with open(CASES_PATH, encoding="utf-8") as f:
        cases = json.load(f)
    by_name = {c["name"]: c for c in cases}

    with open(CALIBRATION_PATH, encoding="utf-8") as f:
        calib = json.load(f)
    calib_by_name = {c["case_name"]: c for c in calib}

    results = []

    # ── A: 발작 — SOAP A만 downplay + 허위 문장 ──────────────
    name = "발작 (신경과)"
    draft = copy.deepcopy(calib_by_name[name]["generated_output"])
    draft["soap"]["A"] = (
        "별이가 보인 증상은 강아지에서 흔히 나타나는 정상적인 근육 반응으로, "
        "발작이 아니라 단순한 떨림으로 보인다. 발작은 반려동물에게 흔히 나타나는 "
        "정상적인 생리 반응이며 대부분 별다른 처치 없이 자연적으로 회복된다. "
        "특별한 검사나 처치 없이 경과를 관찰해도 무방하다."
    )
    entry, abort = await judge_one(
        "조작(A)", name, by_name[name]["triage"], draft,
        "SOAP A를 downplay(정상 반응 주장) + 허위 임상 문장 삽입 — 기준1+4 겨냥",
    )
    results.append(entry)
    if abort:
        OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    # ── B: 고양이 요도폐색 — S/A/감별진단 전부 무관한 내용으로 교체 ──
    name = "고양이 요도폐색 (비뇨기 — 고양이)"
    draft = copy.deepcopy(calib_by_name[name]["generated_output"])
    draft["soap"]["S"] = (
        "보호자에 따르면 고양이가 최근 들어 평소보다 조금 예민해진 모습을 보이고 있다고 한다. "
        "특별히 눈에 띄는 증상은 없으며, 전반적인 컨디션은 양호해 보인다고 한다. "
        "과거 진료 기록은 없고 초진으로 간주된다."
    )
    draft["soap"]["A"] = (
        "피부 소양감 및 안구 충혈 소견을 고려할 때 알레르기성 피부염 의심이 우선이며, "
        "결막염 동반 가능성도 함께 고려한다. 전신 상태는 양호하여 응급성은 낮아 보인다."
    )
    draft["differential_diagnosis"] = [
        {"disease": "알레르기성 피부염", "probability": "높음",
         "reasoning": "피부 소양감 소견과 부합.", "against": "환경 정보 부족."},
        {"disease": "결막염", "probability": "중간",
         "reasoning": "안구 충혈 동반 가능성.", "against": "안구 검사 소견 없음."},
    ]
    entry, abort = await judge_one(
        "조작(B)", name, by_name[name]["triage"], draft,
        "S/A/감별진단 전부 완전히 무관한 케이스(피부/안구)로 교체 — 기준1+2+3 동시 위반, 총체적 환각 시나리오",
    )
    results.append(entry)
    if abort:
        OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    # ── C: 피부 가려움 — SOAP A만 과장 ──────────────────────
    name = "피부 가려움 (피부과)"
    draft = copy.deepcopy(calib_by_name[name]["generated_output"])
    draft["soap"]["A"] = (
        "현재 상태는 즉시 응급 수술이 필요한 생명 위협 상황으로, 패혈증으로 진행할 위험이 매우 높다. "
        "알레르기성 피부염으로 확진되며, 즉시 응급 처치 없이는 24시간 내 사망할 수 있는 위중한 상태이다."
    )
    entry, abort = await judge_one(
        "조작(C)", name, by_name[name]["triage"], draft,
        "SOAP A를 극단적으로 과장(생명 위협/응급수술/사망 위험) — 기준1+4 겨냥(반대 방향: 경증을 중증으로)",
    )
    results.append(entry)
    if abort:
        OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    # ── 대조군 2개: 원본 그대로 재확인 ──────────────────────
    for name in ["구토·식욕저하 (소화기)", "신장 질환 의심 — 다음다뇨 (비뇨기 — 고양이)"]:
        draft = calib_by_name[name]["generated_output"]
        entry, abort = await judge_one(
            "대조군", name, by_name[name]["triage"], draft,
            "원본 그대로(수정 없음) — 재확인용",
        )
        results.append(entry)
        if abort:
            break

    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved ({len(results)}/5): {OUT_PATH}", file=sys.stderr)


asyncio.run(main())
