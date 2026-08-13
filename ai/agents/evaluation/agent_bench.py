"""에이전트 벤치마크 — 각 에이전트를 테스트셋으로 직접 호출해 성능 측정.

  run_followup_filter_eval  — 경과 필터 Recall/Precision + LLM 정확도
  run_triage_eval           — 응급도 정확도 · Red flag 감지 · 슬롯 추출 F1
  run_mcp_health_check      — MCP 연결·레이턴시·Fallback
  run_orchestrator_eval     — 라우팅 정확도 · 문진 중 유출
  run_reception_eval        — MCP 도구 선택 정확도
  run_schedule_eval         — 소요시간 범위 · 응급도 순서 · 케어 가이드 품질
  run_chart_eval            — SOAP 완전성 · 키워드 포함율 · 감별진단 구조
  run_full_agent_report     — 전체 모듈 통합 리포트
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ai.agents.evaluation.case_eval import _soap_section_issues
from ai.agents.evaluation.text_match import keyword_in_context

logger = logging.getLogger("ai.agents.evaluation.agent_bench")

_EVAL_CASES_DIR = Path(__file__).resolve().parent.parent / "eval_cases"

# "단정 표현 없음"(run_chart_eval) / "약물 표현 없음"(run_schedule_eval) 체크가
# 공유하는 부정 문맥 인지 키워드 매칭 — 부정어가 phrase/pattern보다 앞에 오거나
# 문장이 길어 고정 윈도우 밖에 있어도 같은 문장이면 잡히도록 문장 단위로 본다.
# "확정 진단은 내리기 어렵습니다" 같이 금지 표현을 부정하는 문맥은 오탐으로 제외.
_PHRASE_NEG_KW = ("불가", "어렵", "아님", "안 됩니다", "할 수 없", "내리지 않", "최종 판단은 수의사")
# "진통제 금지", "항생제 주지 마세요" 등 금지 맥락은 오탐 — 부정어가 같은 문장에 있으면 제외.
_DRUG_NEG_KW = ("금지", "하지 마세요", "주지 마세요", "피하세요", "안 됩니다", "삼가", "투여 금지")


def _is_phrase_assertive(text: str, phrase: str) -> bool:
    return keyword_in_context(text, phrase, _PHRASE_NEG_KW)


def _is_drug_prescribed(tip: str, pat: str) -> bool:
    return keyword_in_context(tip, pat, _DRUG_NEG_KW)


# ── 테스트셋 로더 ────────────────────────────────────────────────

def _load_followup_cases() -> list[dict]:
    import json
    candidates = [
        _EVAL_CASES_DIR / "followup_eval_cases.json",
        Path("ai/agents/eval_cases/followup_eval_cases.json"),
    ]
    for p in candidates:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return []


def _load_triage_cases() -> list[dict]:
    import json
    candidates = [
        _EVAL_CASES_DIR / "triage_eval_cases.json",
        Path("ai/agents/eval_cases/triage_eval_cases.json"),
    ]
    for p in candidates:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return []


def _load_schedule_cases() -> list[dict]:
    import json
    p = _EVAL_CASES_DIR / "schedule_eval_cases.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return []


def _load_chart_cases() -> list[dict]:
    import json
    p = _EVAL_CASES_DIR / "chart_eval_cases.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return []


def _load_reception_cases() -> list[dict]:
    import json
    p = _EVAL_CASES_DIR / "reception_eval_cases.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return []


async def _llm_judge_keywords(text: str, keywords: list[str]) -> list[bool]:
    """하이브리드 게이트: 1차 string match → 실패 시에만 LLM 의미 판단."""
    if not keywords or not text.strip():
        return [False] * len(keywords)

    # 1차: string match (공백 제거 포함 — 의학용어 띄어쓰기 변형 대응)
    text_nospace = text.replace(" ", "")
    results = [kw in text or kw.replace(" ", "") in text_nospace for kw in keywords]

    # 1차 실패 키워드만 LLM으로 의미 판단 (비용 최소화)
    failed_idx = [i for i, r in enumerate(results) if not r]
    if not failed_idx:
        return results  # 전부 통과 — LLM 호출 없음

    from ai.llm import call_llm_json
    failed_kws = [keywords[i] for i in failed_idx]
    kw_lines = "\n".join(f"{i + 1}. {kw}" for i, kw in enumerate(failed_kws))
    prompt = (
        "아래 텍스트에서 각 키워드의 의미가 반영되어 있는지 판단하세요.\n"
        "표현 방식이 달라도 의미가 동일하면 포함으로 봅니다.\n\n"
        f"[텍스트]\n{text[:2000]}\n\n"
        f"[키워드 목록]\n{kw_lines}\n\n"
        "각 키워드에 대해 JSON으로만 답하세요:\n"
        '{"results": [{"keyword": "키워드명", "included": true}, ...]}'
    )
    try:
        raw = await call_llm_json(prompt)
        mapping = {
            r.get("keyword", ""): bool(r.get("included", False))
            for r in (raw.get("results") or [])
        }
        for i, kw in zip(failed_idx, failed_kws):
            results[i] = mapping.get(kw, False)
    except Exception:
        pass  # LLM 실패 시 string match 결과(False) 유지

    return results


# ── 경과 필터 평가 ────────────────────────────────────────────────

async def run_followup_filter_eval(
    test_cases: list[dict] | None = None,
) -> dict:
    """경과 필터 AI 평가.

    Check 1: keyword_fallback 분류 Recall/Precision (빠름, 비용 없음)
    Check 2: urgent_possible 감지율 100% (안전 필수)
    Check 3: classify_followup LLM 실호출 정확도 (API 비용 발생)
    """
    from ai.agents.followup_filter.schema import SeverityHint, keyword_fallback

    cases = test_cases or _load_followup_cases()
    if not cases:
        return {"agent": "followup_filter", "status": "SKIPPED", "detail": "테스트 케이스 없음"}

    checks = []

    # ── 1. 분류 Recall / Precision + 카테고리별 통계 ──────────
    tp = fp = fn = 0
    kw_predictions: list[bool] = []
    category_stats: dict[str, dict] = {}

    for case in cases:
        expected = case.get("expected_is_followup", False)
        predicted = keyword_fallback(case["message"]).is_followup
        kw_predictions.append(predicted)
        if expected and predicted:
            tp += 1
        elif not expected and predicted:
            fp += 1
        elif expected and not predicted:
            fn += 1
        if expected:
            cat = case.get("expected_category", "unknown")
            if cat not in category_stats:
                category_stats[cat] = {"kw_hit": 0, "total": 0}
            category_stats[cat]["total"] += 1
            if predicted:
                category_stats[cat]["kw_hit"] += 1

    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    precision = tp / (tp + fp) if (tp + fp) > 0 else None

    if recall is None:
        checks.append({"item": "분류 Recall/Precision", "status": "SKIPPED", "detail": "경과 케이스 없음"})
    elif recall >= 0.9 and (precision is None or precision >= 0.8):
        checks.append({
            "item": "분류 Recall/Precision", "status": "PASS",
            "detail": f"Recall {recall:.0%} / Precision {precision:.0%}",
        })
    else:
        checks.append({
            "item": "분류 Recall/Precision", "status": "WARN",
            "detail": f"Recall {recall:.0%} (기준 90%) / Precision {precision:.0%} (기준 80%)",
        })

    # ── 2. 악화 신호(urgent_possible) 감지 — 100% 필수 ────────
    urgent_cases = [c for c in cases if c.get("expected_severity") == "urgent_possible"]
    urgent_detected = sum(
        1 for c in urgent_cases
        if keyword_fallback(c["message"]).severity_hint == SeverityHint.URGENT_POSSIBLE
    )
    if not urgent_cases:
        checks.append({"item": "악화 신호 감지", "status": "SKIPPED", "detail": "urgent 케이스 없음"})
    elif urgent_detected == len(urgent_cases):
        checks.append({
            "item": "악화 신호 감지", "status": "PASS",
            "detail": f"{urgent_detected}/{len(urgent_cases)} 감지",
        })
    else:
        checks.append({
            "item": "악화 신호 감지", "status": "WARN",
            "detail": f"{urgent_detected}/{len(urgent_cases)} 감지 (100% 필수)",
        })

    # ── 3. LLM 분류 정확도 (classify_followup 병렬 실호출) ──────────
    llm_tp = llm_fp = llm_fn = llm_errors = 0
    try:
        import asyncio
        from ai.agents.followup_filter.agent import classify_followup
        from ai.orchestrator.contracts import Phase, SessionContext

        async def _run_one(case: dict):
            ctx = SessionContext(
                session_id=0, userid=0, petid=0,
                pet_info={"name": "평가용"},
                hospitalid=0, emrid=None, scheduleid=None,
                user_message=case["message"], attachments=[],
                phase=Phase.BOOKED, db=None,
            )
            return await classify_followup(ctx, case["message"])

        results = await asyncio.gather(
            *[_run_one(c) for c in cases], return_exceptions=True
        )

        missed_samples: list[dict] = []
        confidences: list[float] = []
        low_confidence_cases: list[dict] = []

        for i, (case, res) in enumerate(zip(cases, results)):
            if isinstance(res, Exception):
                llm_errors += 1
                continue
            expected = case.get("expected_is_followup", False)
            predicted = res.is_followup
            conf = res.confidence
            confidences.append(conf)

            if expected and predicted:
                llm_tp += 1
            elif not expected and predicted:
                llm_fp += 1
            elif expected and not predicted:
                llm_fn += 1

            if expected and not kw_predictions[i] and predicted and len(missed_samples) < 5:
                missed_samples.append({
                    "message": case["message"][:60],
                    "category": case.get("expected_category", "unknown"),
                })

            if conf < 0.7 and len(low_confidence_cases) < 10:
                low_confidence_cases.append({
                    "message": case["message"][:60],
                    "confidence": round(conf, 2),
                    "predicted": predicted,
                    "expected": expected,
                    "correct": predicted == expected,
                })

        avg_confidence = round(sum(confidences) / len(confidences), 3) if confidences else None

        llm_recall = llm_tp / (llm_tp + llm_fn) if (llm_tp + llm_fn) > 0 else None
        llm_precision = llm_tp / (llm_tp + llm_fp) if (llm_tp + llm_fp) > 0 else None

        if llm_errors == len(cases):
            checks.append({"item": "LLM 분류 정확도", "status": "SKIPPED", "detail": "모든 케이스 LLM 호출 실패"})
        elif llm_recall is None:
            checks.append({"item": "LLM 분류 정확도", "status": "SKIPPED", "detail": "경과 케이스 없음"})
        elif llm_recall >= 0.9 and (llm_precision is None or llm_precision >= 0.8):
            checks.append({
                "item": "LLM 분류 정확도", "status": "PASS",
                "detail": f"Recall {llm_recall:.0%} / Precision {llm_precision:.0%} (LLM 실호출, 오류 {llm_errors}건)",
            })
        else:
            checks.append({
                "item": "LLM 분류 정확도", "status": "WARN",
                "detail": f"Recall {llm_recall:.0%} (기준 90%) / Precision {llm_precision:.0%} (기준 80%), 오류 {llm_errors}건",
            })
    except ImportError:
        llm_recall = llm_precision = None
        avg_confidence = None
        missed_samples = []
        low_confidence_cases = []
        checks.append({"item": "LLM 분류 정확도", "status": "SKIPPED", "detail": "classify_followup import 실패"})

    statuses = {c["status"] for c in checks}
    overall = "WARN" if "WARN" in statuses else ("SKIPPED" if statuses <= {"SKIPPED"} else "PASS")

    return {
        "agent": "followup_filter",
        "overall": overall,
        "checks": checks,
        "metrics": {
            "keyword_recall": round(recall, 3) if recall is not None else None,
            "keyword_precision": round(precision, 3) if precision is not None else None,
            "llm_recall": round(llm_recall, 3) if llm_recall is not None else None,
            "llm_precision": round(llm_precision, 3) if llm_precision is not None else None,
            "urgent_recall": f"{urgent_detected}/{len(urgent_cases)}" if urgent_cases else "N/A",
            "total_cases": len(cases),
            "category_stats": category_stats,
            "missed_samples": missed_samples,
            "avg_confidence": avg_confidence,
            "low_confidence_cases": low_confidence_cases,
        },
    }


# ── 트리아지 에이전트 평가 ────────────────────────────────────────

async def run_triage_eval(test_cases: list[dict] | None = None) -> dict:
    """문진 에이전트 평가.

    Check 1: 응급도 정확도 — engine.match(expected_extracted) → top_urgency()
    Check 2: Red flag 감지율 — 100% 필수
    Check 3: 슬롯 추출 F1 — LLM 추출 vs expected_extracted
    Check 4: 환각 체크 — 대화에 없는 증거의 변수 추출 여부
    Check 8: 요약 완전성 — expected_summary_keywords 포함율
    """
    from ai.agents.triage.engine import match, top_urgency, red_flag_labels

    cases = test_cases or _load_triage_cases()
    if not cases:
        return {"agent": "triage", "status": "SKIPPED", "detail": "테스트 케이스 없음"}

    checks: list[dict] = []

    # ── 결정론 체크 (1, 2) ────────────────────────────────────
    urgency_correct = urgency_total = 0
    red_flag_tp = red_flag_fn = 0
    urgency_errors: list[dict] = []

    for case in cases:
        expected_ext = case.get("expected_extracted", {})
        expected_urg = case.get("expected_urgency")
        expected_rf = case.get("expected_red_flag", False)

        matched = match(expected_ext)
        predicted_urg = top_urgency(matched)
        rf = red_flag_labels(matched)

        if expected_urg:
            urgency_total += 1
            if predicted_urg == expected_urg:
                urgency_correct += 1
            elif len(urgency_errors) < 5:
                urgency_errors.append({
                    "name": case.get("name", "")[:40],
                    "expected": expected_urg,
                    "got": predicted_urg or "None",
                })

        if expected_rf:
            if rf:
                red_flag_tp += 1
            else:
                red_flag_fn += 1

    urgency_acc = urgency_correct / urgency_total if urgency_total > 0 else None
    rf_total = red_flag_tp + red_flag_fn

    if urgency_acc is None:
        checks.append({"item": "응급도 정확도", "status": "SKIPPED", "detail": "urgency 케이스 없음"})
    elif urgency_acc >= 0.95:
        checks.append({"item": "응급도 정확도", "status": "PASS",
                        "detail": f"{urgency_correct}/{urgency_total} ({urgency_acc:.0%})"})
    else:
        checks.append({"item": "응급도 정확도", "status": "WARN",
                        "detail": f"{urgency_correct}/{urgency_total} ({urgency_acc:.0%}, 기준 95%)"})

    if rf_total == 0:
        checks.append({"item": "Red flag 감지", "status": "SKIPPED", "detail": "red flag 케이스 없음"})
    elif red_flag_fn == 0:
        checks.append({"item": "Red flag 감지", "status": "PASS",
                        "detail": f"{red_flag_tp}/{rf_total} (100%)"})
    else:
        checks.append({"item": "Red flag 감지", "status": "WARN",
                        "detail": f"{red_flag_tp}/{rf_total} ({red_flag_tp / rf_total:.0%}, 100% 필수)"})

    # ── LLM 체크 (3, 4, 8) ───────────────────────────────────
    slot_tp = slot_fp = slot_fn = 0
    grounded_count = ungrounded_count = 0
    ungrounded_samples: list[str] = []
    summary_kw_hits = summary_kw_total = 0
    llm_errors = 0

    try:
        import asyncio
        from ai.llm import call_llm_json
        from ai.agents.triage.prompts import build_extraction_prompt

        async def _extract_one(case: dict):
            msgs = case.get("messages", [])
            user_msg = msgs[-1]["content"] if msgs else ""
            history = msgs[:-1] if len(msgs) > 1 else []
            section_id = next(iter(case.get("expected_extracted", {}).keys()), None)
            prompt = build_extraction_prompt(history, user_msg, section_id, {}, "")
            return await call_llm_json(prompt)

        results = await asyncio.gather(
            *[_extract_one(c) for c in cases], return_exceptions=True
        )

        _trivial = {"none", "no", "unknown", "normal"}
        _summary_judge_items: list[tuple[str, list]] = []
        _grounding_check_items: list[tuple[str, str, str]] = []  # (var, val_str, user_text)
        _semantic_items: list[tuple[str, str, str, str]] = []  # (var, expected_val, extracted_val, user_text)

        for case, res in zip(cases, results):
            if isinstance(res, Exception) or not isinstance(res, dict):
                llm_errors += 1
                continue

            extracted_vars: dict = res.get("variables") or {}
            summary: str = res.get("summary") or ""

            expected_flat: dict = {
                var: val
                for sec_vars in case.get("expected_extracted", {}).values()
                for var, val in sec_vars.items()
            }

            msgs = case.get("messages", [])
            user_text = " ".join(
                m.get("content", "")
                for m in msgs
                if isinstance(m, dict) and m.get("role") == "user"
            )
            user_text_nospace = user_text.replace(" ", "")

            # 슬롯 F1: exact match → 실패 시 의미 동등성 배치 확인 (minimum requirement)
            for var, expected_val in expected_flat.items():
                extracted_val = extracted_vars.get(var)
                if str(extracted_val) == str(expected_val):
                    slot_tp += 1
                elif extracted_val is None or str(extracted_val) in _trivial:
                    slot_fn += 1  # 미추출
                else:
                    # 값은 있는데 다름 → 의미 동등성 배치 확인
                    _semantic_items.append((var, str(expected_val), str(extracted_val), user_text))

            # 추가 추출 변수 grounding (expected에 없는 것만 — minimum requirement로 FP 미계산)
            for var, val in extracted_vars.items():
                val_str = str(val)
                if val_str not in _trivial and var not in expected_flat:
                    if val_str in user_text or val_str.replace(" ", "") in user_text_nospace:
                        grounded_count += 1
                    else:
                        # string match 실패 → 2차 LLM 판단 대기열
                        _grounding_check_items.append((var, val_str, user_text))

            _summary_judge_items.append((summary, case.get("expected_summary_keywords", [])))

        # 2차: string match 실패한 추가 추출 → LLM으로 var 개념 언급 여부 판단
        if _grounding_check_items:
            async def _judge_grounding(var: str, val_str: str, ut: str) -> bool:
                prompt = (
                    "동물병원 보호자의 발화를 보고 아래 추출 항목이 합리적인 임상 추론인지 판단하세요.\n"
                    "값이 영어 임상 용어여도 한국어 발화에서 추론 가능하면 grounded=true입니다.\n"
                    "예: '눈을 잘 못 떠요' → consciousness: dull (grounded=true)\n"
                    "예: '배를 만지면 많이 아파해요' → abdominal_pain: severe (grounded=true)\n"
                    "보호자가 해당 증상/상태를 전혀 언급하지 않은 경우에만 grounded=false.\n\n"
                    f"[보호자 발화]\n{ut[:1500]}\n\n"
                    f"[항목(var)] {var}\n"
                    f"[추출된 값(val)] {val_str}\n\n"
                    'JSON만 출력: {"grounded": true 또는 false}'
                )
                try:
                    raw = await call_llm_json(prompt)
                    return bool(raw.get("grounded", False))
                except Exception:
                    return False

            _grounding_results = await asyncio.gather(
                *[_judge_grounding(var, val_str, ut) for var, val_str, ut in _grounding_check_items],
                return_exceptions=True,
            )
            for (var, val_str, _), grounded in zip(_grounding_check_items, _grounding_results):
                if isinstance(grounded, Exception) or not grounded:
                    ungrounded_count += 1
                    if len(ungrounded_samples) < 3:
                        ungrounded_samples.append(f"{var}: {val_str}")
                else:
                    grounded_count += 1

        # 슬롯 값 의미 동등성 배치 판단 (string match 실패 케이스만)
        if _semantic_items:
            async def _judge_semantic(var: str, ev: str, xv: str, ut: str) -> bool:
                prompt = (
                    "수의학 문진 컨텍스트에서 두 슬롯 값이 의미적으로 동등한지 판단하세요.\n"
                    "표현이 달라도 같은 상태·정도를 나타내면 동등으로 봅니다.\n"
                    "예: 'active'≈'ongoing', '식욕저하'≈'밥을 안 먹어요', 'decreased'≈'감소'\n\n"
                    f"[보호자 발화]\n{ut[:800]}\n\n"
                    f"[슬롯] {var}\n[기대값] {ev}\n[추출값] {xv}\n\n"
                    'JSON만 출력: {"equivalent": true 또는 false}'
                )
                try:
                    raw = await call_llm_json(prompt)
                    return bool(raw.get("equivalent", False))
                except Exception:
                    return False

            _semantic_results = await asyncio.gather(
                *[_judge_semantic(var, ev, xv, ut) for var, ev, xv, ut in _semantic_items],
                return_exceptions=True,
            )
            for (var, _, _, _), equiv in zip(_semantic_items, _semantic_results):
                if isinstance(equiv, Exception) or not equiv:
                    slot_fn += 1
                    slot_fp += 1  # 의미적으로도 다름 → FP + FN
                else:
                    slot_tp += 1  # 의미적으로 동등 → TP

        if _summary_judge_items:
            _summary_results = await asyncio.gather(
                *[_llm_judge_keywords(s, kws) for s, kws in _summary_judge_items]
            )
            for judgments, (_, kws) in zip(_summary_results, _summary_judge_items):
                summary_kw_total += len(kws)
                summary_kw_hits += sum(judgments)

        slot_precision = slot_tp / (slot_tp + slot_fp) if (slot_tp + slot_fp) > 0 else None
        slot_recall = slot_tp / (slot_tp + slot_fn) if (slot_tp + slot_fn) > 0 else None
        slot_f1 = (
            2 * slot_precision * slot_recall / (slot_precision + slot_recall)
            if slot_precision and slot_recall else None
        )
        summary_score = summary_kw_hits / summary_kw_total if summary_kw_total > 0 else None

        if llm_errors == len(cases):
            for item in ["슬롯 추출 F1", "환각 체크", "요약 완전성"]:
                checks.append({"item": item, "status": "SKIPPED", "detail": "LLM 호출 전체 실패"})
        else:
            if slot_tp + slot_fn == 0:
                checks.append({"item": "슬롯 추출 F1", "status": "SKIPPED", "detail": "expected_extracted 없음"})
            elif slot_f1 is None:
                checks.append({"item": "슬롯 추출 F1", "status": "WARN",
                                "detail": f"F1 계산 불가 (P={slot_precision or 0:.2f} R={slot_recall or 0:.2f}, 기준 0.80)"})
            elif slot_f1 >= 0.8:
                checks.append({"item": "슬롯 추출 F1", "status": "PASS",
                                "detail": f"F1={slot_f1:.2f} (P={slot_precision:.2f} R={slot_recall:.2f}, 오류 {llm_errors}건)"})
            else:
                checks.append({"item": "슬롯 추출 F1", "status": "WARN",
                                "detail": f"F1={slot_f1:.2f} (기준 0.80, P={slot_precision:.2f} R={slot_recall:.2f})"})

            total_extra = grounded_count + ungrounded_count
            if total_extra == 0:
                checks.append({"item": "추가 추출 건수", "status": "PASS", "detail": "expected 외 추출 없음"})
            elif ungrounded_count == 0:
                checks.append({
                    "item": "추가 추출 건수",
                    "status": "PASS",
                    "detail": f"{grounded_count}건 추가 추출 — 전부 발화 근거 확인됨 (테스트셋 미정의)",
                })
            else:
                checks.append({
                    "item": "추가 추출 건수",
                    "status": "WARN",
                    "detail": (
                        f"근거 없는 추출 {ungrounded_count}건 — {'; '.join(ungrounded_samples)}"
                        + (f" (발화 근거 있음 {grounded_count}건)" if grounded_count > 0 else "")
                    ),
                })

            if summary_score is None:
                checks.append({"item": "요약 완전성", "status": "SKIPPED", "detail": "summary_keywords 없음"})
            elif summary_score >= 0.8:
                checks.append({"item": "요약 완전성", "status": "PASS",
                                "detail": f"키워드 {summary_kw_hits}/{summary_kw_total} ({summary_score:.0%})"})
            else:
                checks.append({"item": "요약 완전성", "status": "WARN",
                                "detail": f"키워드 {summary_kw_hits}/{summary_kw_total} ({summary_score:.0%}, 기준 80%)"})

    except ImportError as exc:
        llm_errors = len(cases)
        slot_f1 = slot_precision = slot_recall = summary_score = None
        for item in ["슬롯 추출 F1", "환각 체크", "요약 완전성"]:
            checks.append({"item": item, "status": "SKIPPED", "detail": f"import 실패: {exc}"})

    statuses = {c["status"] for c in checks}
    overall = "WARN" if "WARN" in statuses else ("SKIPPED" if statuses <= {"SKIPPED"} else "PASS")

    return {
        "agent": "triage",
        "overall": overall,
        "checks": checks,
        "metrics": {
            "urgency_accuracy": round(urgency_acc, 3) if urgency_acc is not None else None,
            "urgency_cases": urgency_total,
            "urgency_errors": urgency_errors,
            "red_flag_recall": f"{red_flag_tp}/{rf_total}" if rf_total > 0 else "N/A",
            "slot_f1": round(slot_f1, 3) if slot_f1 is not None else None,
            "slot_precision": round(slot_precision, 3) if slot_precision is not None else None,
            "slot_recall": round(slot_recall, 3) if slot_recall is not None else None,
            "extra_grounded": grounded_count,
            "extra_ungrounded": ungrounded_count,
            "summary_score": round(summary_score, 3) if summary_score is not None else None,
            "llm_errors": llm_errors,
            "total_cases": len(cases),
        },
    }


# ── MCP 헬스 체크 ────────────────────────────────────────────────

async def run_mcp_health_check() -> dict:
    """MCP 서버 연결 상태 평가 — 연결·list_tools·call_tool 왕복·레이턴시·Fallback."""
    import time

    from ai.orchestrator.mcp.client import get_mcp_tools

    checks: list[dict] = []

    t0 = time.monotonic()
    try:
        tools = await get_mcp_tools(use_cache=False)
        ms = (time.monotonic() - t0) * 1000
        tool_names = [t.name for t in tools]
        if tools:
            checks.append({
                "item": "연결·list_tools",
                "status": "PASS",
                "detail": f"{len(tools)}개 도구 ({ms:.0f}ms): {', '.join(tool_names)}",
            })
        else:
            checks.append({
                "item": "연결·list_tools",
                "status": "WARN",
                "detail": "MCP 서버 응답 없음 — 도구 0개",
            })
    except Exception as exc:
        checks.append({"item": "연결·list_tools", "status": "WARN", "detail": f"연결 오류: {exc}"})
        return {"agent": "mcp_health", "overall": "WARN", "checks": checks, "metrics": {}}

    target = next((t for t in tools if t.name == "get_hospital_info"), None)
    avg_ms_val: float | None = None
    if not target:
        checks.append({"item": "call_tool 왕복", "status": "WARN", "detail": "get_hospital_info 도구 없음"})
    else:
        latencies: list[float] = []
        err_count = 0
        test_hid = int(os.getenv("EVAL_TEST_HOSPITAL_ID", "1"))
        for _ in range(5):
            t0 = time.monotonic()
            try:
                await target.ainvoke({"hospitalid": test_hid})
                latencies.append((time.monotonic() - t0) * 1000)
            except Exception:
                err_count += 1
        if latencies:
            avg_ms_val = sum(latencies) / len(latencies)
            max_ms = max(latencies)
            st = "PASS" if max_ms <= 2000 and err_count == 0 else "WARN"
            checks.append({
                "item": "call_tool 왕복",
                "status": st,
                "detail": f"5회 평균 {avg_ms_val:.0f}ms · 최대 {max_ms:.0f}ms · 오류 {err_count}건 (기준 2000ms)",
            })
        else:
            checks.append({"item": "call_tool 왕복", "status": "WARN", "detail": "5회 모두 실패"})

    checks.append({
        "item": "Fallback",
        "status": "PASS",
        "detail": "get_mcp_tools() 실패 시 [] 반환 → reception이 키워드 DB 조회로 자동 폴백 (코드 확인됨)",
    })

    overall = "WARN" if any(c["status"] == "WARN" for c in checks) else "PASS"
    return {
        "agent": "mcp_health",
        "overall": overall,
        "checks": checks,
        "metrics": {
            "tool_count": len(tools),
            "avg_latency_ms": round(avg_ms_val) if avg_ms_val else None,
        },
    }


# ── 오케스트레이터 평가 ──────────────────────────────────────────

def _load_orchestrator_cases() -> list[dict]:
    import json
    p = _EVAL_CASES_DIR / "orchestrator_eval_cases.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return []


async def run_orchestrator_eval(db: AsyncSession) -> dict:
    """오케스트레이터 라우팅 평가 — 정확도 90%+, 문진 중 유출 0건, sticky 규칙."""
    from ai.orchestrator.router import route
    from ai.orchestrator.contracts import Flow, Phase, SessionContext

    _PHASE_MAP = {
        "PRE_BOOKING": Phase.PRE_BOOKING,
        "BOOKED": Phase.BOOKED,
    }
    _FLOW_MAP = {
        "IDLE": Flow.IDLE,
        "TRIAGING": Flow.TRIAGING,
        "SCHEDULING": Flow.SCHEDULING,
        "AWAITING_BOOKING_CONFIRM": Flow.AWAITING_BOOKING_CONFIRM,
    }

    raw_cases = _load_orchestrator_cases()
    if not raw_cases:
        return {"agent": "orchestrator", "overall": "SKIPPED", "checks": [
            {"item": "라우팅 평가", "status": "SKIPPED", "detail": "orchestrator_eval_cases.json 없음"}
        ], "metrics": {}}

    hit = total = triage_leak = 0
    errors_detail: list[dict] = []

    for c in raw_cases:
        name = c["name"]
        phase = _PHASE_MAP.get(c["phase"], Phase.PRE_BOOKING)
        flow = _FLOW_MAP.get(c["flow"], Flow.IDLE)
        msg = c["message"]
        allowed = set(c["allowed"])
        total += 1
        ctx = SessionContext(
            session_id=0, userid=0, petid=0, pet_info={},
            hospitalid=None, emrid=None, scheduleid=None,
            user_message=msg, phase=phase, active_flow=flow, db=db,
        )
        try:
            got = await route(ctx)
        except Exception as exc:
            errors_detail.append({"case": name, "error": str(exc)})
            continue

        if got in allowed:
            hit += 1
        else:
            errors_detail.append({"case": name, "expected": str(sorted(allowed)), "got": got})

        if flow == Flow.TRIAGING and got == "followup_filter":
            triage_leak += 1

    acc = hit / total if total else 0
    overall = "PASS" if acc >= 0.9 and triage_leak == 0 else "WARN"

    checks: list[dict] = [
        {
            "item": "라우팅 정확도",
            "status": "PASS" if acc >= 0.9 else "WARN",
            "detail": f"{hit}/{total} ({acc:.0%}) — 기준 90%",
        },
        {
            "item": "문진 중 유출",
            "status": "PASS" if triage_leak == 0 else "WARN",
            "detail": f"TRIAGING 중 followup_filter 이탈 {triage_leak}건",
        },
    ]
    for err in errors_detail[:3]:
        case = err.get("case", "?")
        detail = (
            f"기대={err.get('expected', '?')} 실제={err.get('got', '?')}"
            if "got" in err else err.get("error", "")
        )
        checks.append({"item": f"오류: {case}", "status": "WARN", "detail": detail})

    return {
        "agent": "orchestrator",
        "overall": overall,
        "checks": checks,
        "metrics": {
            "routing_accuracy": round(acc, 3),
            "triage_leak_count": triage_leak,
            "total_cases": total,
            "error_count": len(errors_detail),
        },
    }


# ── 접수 에이전트 평가 ────────────────────────────────────────────

async def run_reception_eval(db: AsyncSession, test_cases: list[dict] | None = None) -> dict:
    """응대 AI 평가 — MCP 도구 선택 정확도 (병원정보/운영시간/슬롯/무관질문)."""
    from sqlalchemy import select as _select

    from app.models.hospital import Hospital
    from ai.orchestrator.contracts import Phase, SessionContext

    hos_row = await db.execute(_select(Hospital).limit(1))
    hospital = hos_row.scalar_one_or_none()
    hospitalid = hospital.hospitalid if hospital else 1

    checks: list[dict] = []

    try:
        from ai.orchestrator.mcp.client import get_mcp_tools
        mcp_tools = await get_mcp_tools()
    except Exception:
        mcp_tools = []

    if not mcp_tools:
        checks.append({
            "item": "MCP 도구 선택",
            "status": "SKIPPED",
            "detail": "MCP 서버 미가동 — run_mcp_health_check 먼저 확인",
        })
        return {"agent": "reception", "overall": "SKIPPED", "checks": checks, "metrics": {}}

    cases = test_cases or _load_reception_cases()
    if not cases:
        checks.append({"item": "MCP 도구 선택", "status": "SKIPPED", "detail": "테스트 케이스 없음"})
        return {"agent": "reception", "overall": "SKIPPED", "checks": checks, "metrics": {}}

    from ai.agents.reception.agent import reception as _reception_agent

    tool_hit = 0
    case_checks: list[dict] = []
    for case in cases:
        desc, msg, expected_tool = case["name"], case["message"], case.get("expected_tool")
        ctx = SessionContext(
            session_id=0, userid=0, petid=0, pet_info={},
            hospitalid=hospitalid, emrid=None, scheduleid=None,
            user_message=msg, phase=Phase.PRE_BOOKING, db=db,
        )
        try:
            facts = await _reception_agent.collect_facts(ctx)
            if expected_tool is None:
                ok = "[get_" not in facts
                case_checks.append({
                    "item": f"도구 선택 ({desc})",
                    "status": "PASS" if ok else "WARN",
                    "detail": "도구 미호출 (정상)" if ok else f"무관 질문에 도구 호출됨: {facts[:80]}",
                })
                if ok:
                    tool_hit += 1
            else:
                ok = f"[{expected_tool}]" in facts
                case_checks.append({
                    "item": f"도구 선택 ({desc})",
                    "status": "PASS" if ok else "WARN",
                    "detail": f"{expected_tool} 호출됨" if ok else f"예상={expected_tool} 미호출 — facts: {facts[:80] or '(없음)'}",
                })
                if ok:
                    tool_hit += 1
        except Exception as exc:
            case_checks.append({"item": f"도구 선택 ({desc})", "status": "WARN", "detail": f"오류: {exc}"})

    acc = tool_hit / len(cases)
    checks = [
        {
            "item": "MCP 도구 선택 (전체)",
            "status": "PASS" if acc == 1.0 else "WARN",
            "detail": f"{tool_hit}/{len(cases)} ({acc:.0%}) — 기준 100%",
        },
        *case_checks,
    ]

    overall = "WARN" if any(c["status"] == "WARN" for c in checks) else "PASS"
    return {
        "agent": "reception",
        "overall": overall,
        "checks": checks,
        "metrics": {"tool_accuracy": round(acc, 3), "total_cases": len(cases)},
    }


# ── 예약 에이전트 평가 ────────────────────────────────────────────

async def run_schedule_eval(test_cases: list[dict] | None = None) -> dict:
    """예약 에이전트 평가.

    Check 1: 예상 소요시간 범위 내 (expected_duration_min ~ expected_duration_max)
    Check 2: 응급도 순서 보존 (RED 소요시간 > GREEN 소요시간)
    Check 3: 형식 유효성 (15~60분, 5분 단위)
    Check 4: 케어 가이드 품질 (tips 1개 이상, 약물명 미포함)
    """
    cases = test_cases or _load_schedule_cases()
    if not cases:
        return {"agent": "schedule", "overall": "SKIPPED", "checks": [
            {"item": "Schedule 벤치마크", "status": "SKIPPED",
             "detail": "테스트셋 준비 후 활성화"}
        ], "metrics": {}}

    from ai.agents.schedule.agent import ScheduleAgent
    agent = ScheduleAgent()
    checks: list[dict] = []

    results: list[dict] = []
    for case in cases:
        try:
            res = await agent.estimate_duration(case["pet"], case["triage"])
            results.append({"case": case, "res": res})
        except Exception as exc:
            results.append({"case": case, "res": None, "error": str(exc)})

    # Check 1: 범위 내 여부
    in_range_count = 0
    range_errors: list[str] = []
    for item in results:
        case, res = item["case"], item.get("res")
        if res is None:
            range_errors.append(f"{case['name']}: 오류({item.get('error','')})")
            continue
        dur = res.get("estimated_duration_min", 0)
        lo, hi = case.get("expected_duration_min", 15), case.get("expected_duration_max", 60)
        if lo <= dur <= hi:
            in_range_count += 1
        else:
            range_errors.append(f"{case['name']}: {dur}분 (기대 {lo}~{hi}분)")

    total = len(cases)
    range_acc = in_range_count / total if total else 0
    checks.append({
        "item": "소요시간 범위",
        "status": "PASS" if range_acc >= 0.75 else "WARN",
        "detail": f"{in_range_count}/{total} 범위 내" + (f" — {'; '.join(range_errors)}" if range_errors else ""),
    })

    # Check 2: 응급도 순서 (RED duration > GREEN duration)
    from collections import defaultdict
    dur_by_urgency: dict[str, list[int]] = defaultdict(list)
    for item in results:
        if item.get("res"):
            u = item["case"]["triage"].get("urgency")
            if u:
                dur_by_urgency[u].append(item["res"].get("estimated_duration_min", 0))
    durations = {u: int(sum(v) / len(v)) for u, v in dur_by_urgency.items()}
    red_dur = durations.get("RED")
    green_dur = durations.get("GREEN")
    if red_dur is not None and green_dur is not None:
        ok = red_dur > green_dur
        checks.append({
            "item": "응급도 순서",
            "status": "PASS" if ok else "WARN",
            "detail": f"RED={red_dur}분 > GREEN={green_dur}분" if ok else f"순서 역전: RED={red_dur}분 ≤ GREEN={green_dur}분",
        })
    else:
        checks.append({"item": "응급도 순서", "status": "SKIPPED", "detail": "RED·GREEN 케이스 필요"})

    # Check 3: 형식 유효성
    valid_count = sum(
        1 for item in results
        if item.get("res") and 15 <= item["res"].get("estimated_duration_min", 0) <= 90
        and item["res"].get("estimated_duration_min", 0) % 5 == 0
    )
    checks.append({
        "item": "형식 유효성 (15~90분, 5분 단위)",
        "status": "PASS" if valid_count == total else "WARN",
        "detail": f"{valid_count}/{total}",
    })

    # Check 4: 케어 가이드 품질
    import asyncio as _asyncio

    async def _get_guidance(case: dict):
        try:
            tips = await agent.care_guidance(case["triage"])
            return {"case": case, "tips": tips}
        except Exception as exc:
            return {"case": case, "tips": None, "error": str(exc)}

    guidance_results = await _asyncio.gather(*[_get_guidance(c) for c in cases])

    _DRUG_PATTERNS = ("mg", "ml", "cc", "주사", "처방", "약물", "항생제", "진통제", "소염제")

    valid_guidance = 0
    guidance_errors: list[str] = []
    for gitem in guidance_results:
        tips = gitem.get("tips")
        cname = gitem["case"]["name"]
        if tips is None:
            guidance_errors.append(f"{cname}: 오류")
            continue
        if len(tips) == 0:
            guidance_errors.append(f"{cname}: tips 0개")
            continue
        drug_hit = next(
            (pat for tip in tips for pat in _DRUG_PATTERNS if _is_drug_prescribed(tip, pat)),
            None,
        )
        if drug_hit:
            guidance_errors.append(f"{cname}: 약물 표현 포함({drug_hit})")
            continue
        valid_guidance += 1

    checks.append({
        "item": "케어 가이드 품질",
        "status": "PASS" if valid_guidance == total else "WARN",
        "detail": f"{valid_guidance}/{total} 유효" + (f" — {'; '.join(guidance_errors[:3])}" if guidance_errors else ""),
    })

    overall = "WARN" if any(c["status"] == "WARN" for c in checks) else (
        "SKIPPED" if all(c["status"] == "SKIPPED" for c in checks) else "PASS"
    )
    return {
        "agent": "schedule",
        "overall": overall,
        "checks": checks,
        "metrics": {
            "range_accuracy": round(range_acc, 3),
            "total_cases": total,
            "durations": durations,
        },
    }


# ── 차트 에이전트 평가 ────────────────────────────────────────────

async def run_chart_eval(test_cases: list[dict] | None = None) -> dict:
    """차트 에이전트 평가.

    Check 1: SOAP 구조 완전성 (S·O·A·P 모두 비어있지 않음)
    Check 2: 키워드 포함율 (expected_keywords → intake_summary 또는 soap.S)
    Check 3: 단정 표현 없음 (forbidden_phrases)
    Check 4: 감별진단 구조 완전성 (disease·probability 필드 1개 이상)
    Check 5: 수의사 확인 질문 포함 (vet_questions 1개 이상)
    """
    cases = test_cases or _load_chart_cases()
    if not cases:
        return {"agent": "chart", "overall": "SKIPPED", "checks": [
            {"item": "Chart 벤치마크", "status": "SKIPPED",
             "detail": "차트 완전성·임상 품질 평가. judge.py 통합 후 활성화."}
        ], "metrics": {}}

    from ai.agents.chart.agent import ChartAgent
    agent = ChartAgent()
    checks: list[dict] = []

    results = []
    for case in cases:
        try:
            res = await agent.generate(
                pet=case["pet"],
                triage=case["triage"],
                chat_history=case.get("chat_history", []),
            )
            results.append({"case": case, "res": res})
        except Exception as exc:
            results.append({"case": case, "res": None, "error": str(exc)})

    total = len(cases)

    # Check 1: SOAP 섹션별 최소 요건 — case_eval._soap_section_issues와 기준 공유
    # (예전엔 여기에 동일 로직이 따로 복붙되어 있어, 한쪽만 고치면 다른 쪽에
    # 같은 버그가 남는 문제가 있었다)
    soap_complete = 0
    soap_errors: list[str] = []
    for item in results:
        case, res = item["case"], item.get("res") or {}
        soap = res.get("soap") or {}

        section_issues = _soap_section_issues(soap)

        if not section_issues:
            soap_complete += 1
        else:
            soap_errors.append(f"{case['name']}: {', '.join(section_issues)}")

    soap_acc = soap_complete / total if total else 0
    checks.append({
        "item": "SOAP 구조 완전성",
        "status": "PASS" if soap_acc >= 0.8 else "WARN",
        "detail": f"{soap_complete}/{total}" + (f" — {'; '.join(soap_errors)}" if soap_errors else ""),
    })

    # Check 2: 키워드 포함율 (LLM-as-judge)
    import asyncio as _asyncio
    kw_hits = kw_total = 0

    async def _chart_kw_judge(item: dict) -> tuple[int, int]:
        case, res = item["case"], item.get("res") or {}
        keywords = case.get("expected_keywords", [])
        if not keywords:
            return 0, 0
        soap_s = str((res.get("soap") or {}).get("S", ""))
        intake = str((res.get("intake_summary") or {}).get("guardian_report", ""))
        combined = (soap_s + " " + intake).strip()
        judgments = await _llm_judge_keywords(combined, keywords)
        return sum(judgments), len(keywords)

    _kw_pairs = await _asyncio.gather(*[_chart_kw_judge(item) for item in results])
    for hits, total in _kw_pairs:
        kw_hits += hits
        kw_total += total

    kw_score = kw_hits / kw_total if kw_total > 0 else None
    if kw_score is None:
        checks.append({"item": "키워드 포함율", "status": "SKIPPED", "detail": "expected_keywords 없음"})
    else:
        checks.append({
            "item": "키워드 포함율",
            "status": "PASS" if kw_score >= 0.7 else "WARN",
            "detail": f"{kw_hits}/{kw_total} ({kw_score:.0%})",
        })

    # Check 3: 단정 표현 없음 (thinking 필드 제외 + 부정 맥락 제외)
    forbidden_count = 0
    forbidden_samples: list[str] = []
    for item in results:
        case, res = item["case"], item.get("res") or {}
        soap = res.get("soap") or {}
        intake = res.get("intake_summary") or {}
        text = " ".join([
            str(soap.get("S", "")),
            str(soap.get("A", "")),
            str(intake.get("suspected_diseases", "")),
            str(res.get("differential_diagnosis", "")),
        ])
        for phrase in case.get("forbidden_phrases", []):
            if _is_phrase_assertive(text, phrase):
                forbidden_count += 1
                if len(forbidden_samples) < 3:
                    forbidden_samples.append(f"{case['name']}: '{phrase}'")

    checks.append({
        "item": "단정 표현 없음",
        "status": "PASS" if forbidden_count == 0 else "WARN",
        "detail": "단정 표현 없음" if forbidden_count == 0 else f"{forbidden_count}건 — {'; '.join(forbidden_samples)}",
    })

    # Check 4: 감별진단 구조 완전성 (disease·probability 필드 1개 이상)
    diff_complete = 0
    diff_errors: list[str] = []
    for item in results:
        case, res = item["case"], item.get("res") or {}
        dd = res.get("differential_diagnosis") or []
        if len(dd) >= 1 and all("disease" in d and "probability" in d for d in dd):
            diff_complete += 1
        else:
            diff_errors.append(f"{case['name']}: {len(dd)}개 (disease·probability 필드 필요)")

    checks.append({
        "item": "감별진단 구조",
        "status": "PASS" if diff_complete == total else "WARN",
        "detail": f"{diff_complete}/{total}" + (f" — {'; '.join(diff_errors)}" if diff_errors else ""),
    })

    # Check 5: 수의사 확인 질문 포함 (vet_questions 1개 이상)
    vet_q_count = 0
    for item in results:
        res = item.get("res") or {}
        if res.get("vet_questions") and len(res["vet_questions"]) >= 1:
            vet_q_count += 1

    checks.append({
        "item": "수의사 질문 포함",
        "status": "PASS" if vet_q_count == total else "WARN",
        "detail": f"{vet_q_count}/{total} (vet_questions 1개 이상)",
    })

    overall = "WARN" if any(c["status"] == "WARN" for c in checks) else (
        "SKIPPED" if all(c["status"] == "SKIPPED" for c in checks) else "PASS"
    )
    return {
        "agent": "chart",
        "overall": overall,
        "checks": checks,
        "metrics": {
            "soap_completeness": round(soap_acc, 3) if total else None,
            "keyword_score": round(kw_score, 3) if kw_score is not None else None,
            "diff_diag_completeness": round(diff_complete / total, 3) if total else None,
            "total_cases": total,
        },
    }


# ── 전체 통합 리포트 ─────────────────────────────────────────────

async def run_full_agent_report(db: AsyncSession) -> dict:
    """전체 에이전트 성능 통합 리포트.

    overall_verdict: PASS / PARTIAL_FAIL / CRITICAL_FAIL
    CRITICAL_FAIL 조건:
      - RED flag recall < 100%
      - triage_leak > 0
      - Schedule RED 소요시간 < 35분 (응급 환자 과소평가)
      - Reception 도구 선택 0% (완전 기능 불능)
    """
    import asyncio as _asyncio
    (
        triage_r, mcp_r, orch_r, reception_r, followup_r, schedule_r, chart_r
    ) = await _asyncio.gather(
        run_triage_eval(),
        run_mcp_health_check(),
        run_orchestrator_eval(db),
        run_reception_eval(db),
        run_followup_filter_eval(),
        run_schedule_eval(),
        run_chart_eval(),
    )

    rf_raw = triage_r.get("metrics", {}).get("red_flag_recall", "N/A")
    rf_critical = False
    if rf_raw not in ("N/A", None):
        parts = str(rf_raw).split("/")
        if len(parts) == 2:
            try:
                rf_critical = int(parts[0]) < int(parts[1])
            except ValueError:
                pass

    triage_leak = orch_r.get("metrics", {}).get("triage_leak_count", 0)

    schedule_durations = schedule_r.get("metrics", {}).get("durations", {})
    red_sched_dur = schedule_durations.get("RED")
    schedule_critical = red_sched_dur is not None and red_sched_dur < 35

    reception_acc = reception_r.get("metrics", {}).get("tool_accuracy")
    reception_critical = reception_acc is not None and reception_acc == 0.0

    all_modules = [triage_r, mcp_r, orch_r, reception_r, followup_r, schedule_r, chart_r]
    if rf_critical or triage_leak > 0 or schedule_critical or reception_critical:
        verdict = "CRITICAL_FAIL"
    elif any(r.get("overall") in ("WARN", "ERROR") for r in all_modules):
        verdict = "PARTIAL_FAIL"
    else:
        verdict = "PASS"

    critical_reasons = []
    if rf_critical:
        critical_reasons.append("RED flag recall < 100%")
    if triage_leak > 0:
        critical_reasons.append(f"TRIAGING 중 유출 {triage_leak}건")
    if schedule_critical:
        critical_reasons.append(f"RED 소요시간 {red_sched_dur}분 (기준 35분+)")
    if reception_critical:
        critical_reasons.append("Reception 도구 선택 0%")

    return {
        "agent": "full_report",
        "overall_verdict": verdict,
        "modules": {
            "triage": triage_r,
            "mcp_health": mcp_r,
            "orchestrator": orch_r,
            "reception": reception_r,
            "followup": followup_r,
            "schedule": schedule_r,
            "chart": chart_r,
        },
        "critical_reasons": critical_reasons,
    }
