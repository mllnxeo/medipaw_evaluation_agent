"""Phase 3 1차 시도 — Chart 8개 케이스에 대해 실제 생성 + judge 실행.

일회성 측정 스크립트. 순차 실행(케이스 하나씩, 병렬 호출 없음) — 이상
징후(생성 실패/빈 결과, judge SKIPPED, 예외)가 나오면 그 시점까지의
결과를 저장하고 즉시 중단해 사람이 확인할 수 있게 한다.
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, "/app")

from ai.agents.chart.agent import ChartAgent
from ai.agents.evaluation.case_eval import _check_chart_quality

TARGET_NAMES = [
    "구토·식욕저하 (소화기)",
    "피부 가려움 (피부과)",
    "발작 (신경과)",
    "신장 질환 의심 — 다음다뇨 (비뇨기 — 고양이)",
    "고양이 요도폐색 (비뇨기 — 고양이)",
    "고양이 호흡곤란 (호흡기 — 고양이)",
    "아나필락시스 의심 (알레르기 반응 — 강아지)",
    "척추 디스크 악화 (신경과)",
]

OUT_PATH = Path("/app/ai/agents/eval_cases/chart_judge_calibration.json")


async def main():
    with open("/app/ai/agents/eval_cases/chart_eval_cases.json", encoding="utf-8") as f:
        cases = json.load(f)
    by_name = {c["name"]: c for c in cases}

    agent = ChartAgent()
    results = []

    for name in TARGET_NAMES:
        case = by_name[name]
        triage_dict = case["triage"]

        try:
            draft = await agent.generate(
                pet=case["pet"],
                triage=triage_dict,
                chat_history=case.get("chat_history", []),
            )
        except Exception as exc:
            print(f"ABORT: {name} -> generate() 예외: {exc}", file=sys.stderr)
            results.append({"case_name": name, "error": f"generate() 예외: {exc}"})
            break

        if not draft:
            print(f"ABORT: {name} -> generate() 결과가 비어 있음(재시도 2회 후에도 실패)", file=sys.stderr)
            results.append({"case_name": name, "error": "generate() 빈 결과"})
            break

        triage_obj = SimpleNamespace(
            urgency_level=triage_dict.get("urgency_level"),
            urgency_level_num=None,
            chief_complaint=triage_dict.get("symptom_summary")
            or ", ".join(triage_dict.get("symptom_keywords") or []),
        )
        intake = draft.get("intake_summary") or {}

        try:
            judge = await _check_chart_quality(triage_obj, draft, intake)
        except Exception as exc:
            print(f"ABORT: {name} -> _check_chart_quality() 예외: {exc}", file=sys.stderr)
            results.append({"case_name": name, "generated_output": draft, "error": f"judge 예외: {exc}"})
            break

        entry = {
            "case_name": name,
            "existing_human_label": case["human_label"],
            "generated_output": draft,
            "judge_status": judge.get("status"),
            "judge_detail": judge.get("detail"),
        }
        results.append(entry)

        if judge.get("status") == "SKIPPED":
            print(f"ABORT: {name} -> judge_status=SKIPPED(LLM 평가 자체 실패) — 중단하고 확인 필요", file=sys.stderr)
            break

        print(f"OK: {name} -> judge={judge.get('status')}", file=sys.stderr)

    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved ({len(results)}/{len(TARGET_NAMES)}): {OUT_PATH}", file=sys.stderr)


asyncio.run(main())
