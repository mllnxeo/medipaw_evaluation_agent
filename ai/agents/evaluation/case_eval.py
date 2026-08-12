"""케이스 단위 평가 — scheduleid 하나로 DB를 직접 조회해 triage/schedule/chart 검증.

  Check 1 (Triage):   1A 응급도정합성 · 1B 응급도판단
                      1C 컨텍스트연속성 · 1D 완료신호 · 1E 대화품질(LLM)
  Check 2 (Schedule): 2A 예약타이밍 · 2B 근무시간 · 2C 빈슬롯 · 2D 핸드오프수신
  Check 3 (Chart):    구조체크 1~4단계(rule) → 임상품질 5단계(LLM)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_history import ChatHistory
from app.models.doctor import Doctor
from app.models.guardian import Guardian
from app.models.pet import Pet
from app.models.report import Report
from app.models.schedule import Schedule
from app.models.triage_result import TriageResult
from app.models.validation_result import ValidationResult
from app.models.vet_schedule import HospitalWeeklySchedule, VetWeeklySchedule
from app.crud.schedule import has_time_overlap
from app.utils.timezone import KST, to_kst
from ai.agents.evaluation.text_match import keyword_in_context

logger = logging.getLogger("ai.agents.evaluation.case_eval")


# ── 상수 ────────────────────────────────────────────────────────

LOW_URGENCY_THRESHOLD = 4
URGENCY_MAX_DAYS: dict[int, int] = {1: 0, 2: 0, 3: 2, 4: 3, 5: 3}


# ── 유틸 ────────────────────────────────────────────────────────


def _scan_red_flags(text: str) -> list[str]:
    """vet_triage.json 기준으로 보호자 발화에서 red flag 감지. 감지된 flag label 반환."""
    try:
        from ai.agents.triage.engine import _kb
        flags = _kb().get("red_flags", {}).get("flags", [])
    except Exception:
        return []

    text_nospace = text.replace(" ", "")
    found: list[str] = []
    for flag in flags:
        keywords = flag.get("keywords", [])
        if any(k in text or k in text_nospace for k in keywords):
            found.append(flag.get("label", flag.get("id", "?")))
    return found


def _module_status(checks: list[dict]) -> str:
    statuses = {c["status"] for c in checks}
    if "WARN" in statuses:
        return "WARN"
    if "ERROR" in statuses:
        return "ERROR"
    if statuses <= {"SKIPPED"}:
        return "SKIPPED"
    return "PASS"


# ── 데이터 로딩 ─────────────────────────────────────────────────

async def _load_data(scheduleid: int, db: AsyncSession) -> dict | None:
    schedule = await db.get(Schedule, scheduleid)
    if not schedule or schedule.deleted_at is not None:
        logger.warning("[Evaluation] scheduleid=%s 없음 또는 삭제됨", scheduleid)
        return None

    emrid = schedule.emrid
    doctorid = schedule.doctorid

    guardian = await db.get(Guardian, emrid)
    pet = await db.get(Pet, guardian.petid) if guardian else None

    triage_row = await db.execute(
        select(TriageResult)
        .where(TriageResult.emrid == emrid)
        .order_by(TriageResult.id.desc())
        .limit(1)
    )
    triage = triage_row.scalar_one_or_none()

    report_row = await db.execute(
        select(Report).where(Report.scheduleid == scheduleid).limit(1)
    )
    report = report_row.scalar_one_or_none()

    chat_row = await db.execute(
        select(ChatHistory)
        .where(ChatHistory.emrid == emrid)
        .order_by(ChatHistory.id.desc())
        .limit(1)
    )
    chat_history = chat_row.scalar_one_or_none()

    doctor = await db.get(Doctor, doctorid)

    return {
        "schedule": schedule,
        "pet": pet,
        "triage": triage,
        "report": report,
        "chat_history": chat_history,
        "doctor": doctor,
        "emrid": emrid,
    }


# ── Check 1 — Triage ────────────────────────────────────────────

async def validate_triage(
    triage: TriageResult | None,
    chat_history: ChatHistory | None,
) -> dict:
    if triage is None:
        skipped = {"status": "SKIPPED", "detail": "triage 없음"}
        return {
            "status": "SKIPPED",
            "checks": [
                {**skipped, "item": "응급도 정합성"},
                {**skipped, "item": "응급도 판단"},
                {**skipped, "item": "컨텍스트 연속성"},
                {**skipped, "item": "완료 신호"},
            ],
        }

    checks = [
        _check_1a(triage, chat_history),
        _check_1b(triage),
        await _check_1c(triage, chat_history),
        _check_1d(triage),
    ]
    return {"status": _module_status(checks), "checks": checks}


def _check_1a(triage: TriageResult, chat_history: ChatHistory | None) -> dict:
    """1A: 보호자 발화 기준 응급 표현 vs urgency_level_num (외부 시선)."""
    if chat_history is None:
        return {"item": "응급도 정합성", "status": "SKIPPED", "detail": "chat_history 없음"}

    messages = chat_history.messages or []
    user_texts = [
        m.get("content", "")
        for m in messages
        if isinstance(m, dict) and m.get("role") == "user"
    ]
    if not user_texts:
        return {"item": "응급도 정합성", "status": "SKIPPED", "detail": "보호자 발화 없음"}

    signals = _scan_red_flags(" ".join(user_texts))

    try:
        urgency_num = int(triage.urgency_level_num)
    except (TypeError, ValueError):
        urgency_num = 5

    if signals and urgency_num >= LOW_URGENCY_THRESHOLD:
        return {
            "item": "응급도 정합성",
            "status": "WARN",
            "detail": (
                f"응급 표현 감지({', '.join(signals)}) 됐으나 "
                f"응급도 {urgency_num}(낮음)으로 책정"
            ),
        }
    if signals:
        return {
            "item": "응급도 정합성",
            "status": "PASS",
            "detail": f"응급 표현 감지({', '.join(signals)}) — 응급도 {urgency_num}와 일치",
        }
    return {"item": "응급도 정합성", "status": "PASS", "detail": "응급 표현 미감지"}


def _check_1b(triage: TriageResult) -> dict:
    """1B: 에이전트가 정리한 chief_complaint가 red flag인데 urgency_num이 낮으면 내부 모순."""
    chief = (triage.chief_complaint or "").strip()
    if not chief:
        return {"item": "응급도 판단", "status": "SKIPPED", "detail": "chief_complaint 없음"}

    signals = _scan_red_flags(chief)

    try:
        urgency_num = int(triage.urgency_level_num)
    except (TypeError, ValueError):
        return {"item": "응급도 판단", "status": "SKIPPED", "detail": "urgency_level_num 파싱 실패"}

    if signals and urgency_num >= LOW_URGENCY_THRESHOLD:
        return {
            "item": "응급도 판단",
            "status": "WARN",
            "detail": (
                f"주증상 '{chief}'이 응급 신호({signals[0]})에 해당하나 "
                f"응급도 {urgency_num}(낮음)으로 판정 — 내부 모순"
            ),
        }
    return {
        "item": "응급도 판단",
        "status": "PASS",
        "detail": f"주증상 '{chief}' — 응급도 {urgency_num} 판정 일치",
    }


async def _check_1c(triage: TriageResult, chat_history: ChatHistory | None) -> dict:
    """1C: 추출 슬롯이 보호자 발화에 근거하는지 확인 (하이브리드: string match → LLM 의미 판단)."""
    if chat_history is None:
        return {"item": "컨텍스트 연속성", "status": "SKIPPED", "detail": "chat_history 없음"}

    messages = chat_history.messages or []
    user_text = " ".join(
        m.get("content", "")
        for m in messages
        if isinstance(m, dict) and m.get("role") == "user"
    )
    if not user_text:
        return {"item": "컨텍스트 연속성", "status": "SKIPPED", "detail": "보호자 발화 없음"}

    keywords = triage.symptom_keywords or []
    if not keywords:
        return {"item": "컨텍스트 연속성", "status": "PASS", "detail": "증상 키워드 없음 — 연속성 N/A"}

    # 1차: string match (공백 제거 포함 — 의학용어 띄어쓰기 변형 대응)
    user_nospace = user_text.replace(" ", "")
    hit_flags = [kw in user_text or kw.replace(" ", "") in user_nospace for kw in keywords]

    # 1차 실패 키워드만 LLM으로 의미 판단 ("식욕부진" ≈ "밥을 안 먹어요" 유형 대응)
    failed_idx = [i for i, h in enumerate(hit_flags) if not h]
    if failed_idx:
        failed_kws = [keywords[i] for i in failed_idx]
        try:
            from ai.llm import call_llm_json
            kw_lines = "\n".join(f"{j + 1}. {kw}" for j, kw in enumerate(failed_kws))
            prompt = (
                "보호자의 일상 발화가 아래 의학 증상 키워드와 같은 증상을 나타내는지 판단하세요.\n"
                "보호자는 의학 용어를 쓰지 않으므로 일상 표현도 동일 증상으로 봅니다.\n"
                "예: '숨이 가빠요' = '호흡곤란', '밥을 안 먹어요' = '식욕부진', '움직일 때만 힘들어해요' = '운동불내성'\n"
                "AI가 해당 증상을 보호자 발화로부터 도출할 수 있으면 included=true로 판단하세요.\n\n"
                f"[보호자 발화]\n{user_text[:1500]}\n\n"
                f"[의학 증상 키워드]\n{kw_lines}\n\n"
                'JSON만 출력: {"results": [{"keyword": "키워드명", "included": true}, ...]}'
            )
            raw = await call_llm_json(prompt)
            mapping = {
                r.get("keyword", ""): bool(r.get("included", False))
                for r in (raw.get("results") or [])
            }
            for i, kw in zip(failed_idx, failed_kws):
                hit_flags[i] = mapping.get(kw, False)
        except Exception as exc:
            logger.warning("[Evaluation] 1C LLM 의미 판단 실패: %s", exc)
            # LLM 실패 시 string match 결과(False) 유지

    hit = sum(hit_flags)
    ratio = hit / len(keywords)

    if ratio >= 0.7:
        return {
            "item": "컨텍스트 연속성",
            "status": "PASS",
            "detail": f"증상 키워드 {hit}/{len(keywords)}개 발화에서 확인됨 (의미 포함 판단 포함)",
        }
    return {
        "item": "컨텍스트 연속성",
        "status": "WARN",
        "detail": f"증상 키워드 {hit}/{len(keywords)}개만 발화 확인 — 추출 근거 불충분",
    }


def _check_1d(triage: TriageResult) -> dict:
    """1D: 문진 완료 신호 확인 (DB 필드 완전성으로 추론)."""
    missing = []
    if not triage.urgency_level:
        missing.append("urgency_level")
    if not triage.chief_complaint:
        missing.append("chief_complaint")
    if not triage.symptom_summary:
        missing.append("symptom_summary")

    if missing:
        return {
            "item": "완료 신호",
            "status": "WARN",
            "detail": f"미설정 필드: {', '.join(missing)} — 문진 완료 불확실",
        }
    return {
        "item": "완료 신호",
        "status": "PASS",
        "detail": (
            f"urgency={triage.urgency_level}({triage.urgency_level_num}) · "
            f"chief_complaint={triage.chief_complaint[:30]!r}"
        ),
    }


async def _check_1e(triage: TriageResult, chat_history: ChatHistory | None) -> dict:
    """1E: 문진 대화 품질 LLM 평가 — overall 집계 제외, conversation_status로만 노출."""
    from ai.llm import call_llm_json

    if not chat_history or not (chat_history.messages or []):
        return {"item": "대화 품질", "status": "SKIPPED", "detail": "대화 기록 없음"}

    messages = chat_history.messages or []
    recent = messages[-20:]
    convo = "\n".join(
        f"{m.get('role', '?')}: {(m.get('content') or '')[:200]}"
        for m in recent
        if isinstance(m, dict)
    )

    triage_info = f"응급도={triage.urgency_level}({triage.urgency_level_num})"
    if triage.chief_complaint:
        triage_info += f", 주증상={triage.chief_complaint}"

    prompt = (
        "너는 동물병원 AI 문진 품질 평가자야. 아래 문진 대화를 보고 4가지 항목을 0~10점으로 평가해.\n\n"
        f"[최종 문진 결과] {triage_info}\n\n"
        f"[문진 대화]\n{convo}\n\n"
        "[평가 항목]\n"
        "1. completeness(완전성): 증상·발병시기·심각도를 충분히 파악했는가?\n"
        "2. question_efficiency(질문 효율): 중복 없이 핵심만 물었는가?\n"
        "3. response_consistency(응답 일관성): 봇 응답이 앞 대화와 일관되는가?\n"
        "4. structuring_quality(구조화 품질): 증상을 체계적으로 정리했는가?\n\n"
        "모두 7.0 이상 → PASS 기준.\n"
        'JSON만 출력: {"completeness": 8, "question_efficiency": 7, "response_consistency": 9, "structuring_quality": 8, "comment": "한 줄 요약"}'
    )

    try:
        out = await call_llm_json(prompt)
        keys = ("completeness", "question_efficiency", "response_consistency", "structuring_quality")
        scores = {k: float(out.get(k, 0)) for k in keys}
        comment = out.get("comment", "")
        avg = sum(scores.values()) / len(scores)
        low = [k for k, v in scores.items() if v < 7.0]

        # 집계 제외 항목이므로 WARN 대신 INFO 사용 — UI에서 중립 색상으로 표시 가능
        status = "INFO" if low else "PASS"
        detail = (
            f"평균 {avg:.1f}/10 · 아쉬운 항목: {', '.join(low)} | {comment}"
            if low
            else f"평균 {avg:.1f}/10 | {comment}"
        )
        return {"item": "대화 품질", "status": status, "detail": detail, "scores": scores}
    except Exception as exc:
        logger.warning("[Evaluation] 1E LLM 실패: %s", exc)
        return {"item": "대화 품질", "status": "SKIPPED", "detail": f"LLM 평가 실패: {exc}"}


# ── Check 2 — Schedule ──────────────────────────────────────────

async def validate_schedule(
    schedule: Schedule,
    triage: TriageResult | None,
    doctor: Doctor | None,
    db: AsyncSession,
) -> dict:
    checks = []

    if not schedule.confirmed_time:
        for item in ["예약 타이밍", "근무시간", "빈 슬롯"]:
            checks.append({"item": item, "status": "SKIPPED", "detail": "confirmed_time 미확정"})
    else:
        checks.append(await _check_2a(schedule, triage, doctor, db))
        checks.append(await _check_2b(schedule, doctor, db))
        checks.append(await _check_2c(schedule, db))

    checks.append(_check_2d(schedule, triage))

    return {"status": _module_status(checks), "checks": checks}


async def _has_same_day_slots(
    schedule: Schedule,
    doctor: Doctor | None,
    db: AsyncSession,
) -> bool | None:
    created = to_kst(schedule.created_at)
    dow = created.weekday()

    vet_row = await db.execute(
        select(VetWeeklySchedule).where(
            VetWeeklySchedule.doctorid == schedule.doctorid,
            VetWeeklySchedule.day_of_week == dow,
        )
    )
    work = vet_row.scalar_one_or_none()

    if work is None and doctor is not None and doctor.hospitalid is not None:
        hosp_row = await db.execute(
            select(HospitalWeeklySchedule).where(
                HospitalWeeklySchedule.hospitalid == doctor.hospitalid,
                HospitalWeeklySchedule.day_of_week == dow,
            )
        )
        work = hosp_row.scalar_one_or_none()

    if work is None or not work.is_open:
        return False
    if not work.start_time or not work.end_time:
        return None

    # 접속 시각 이후 잔여 운영 시간만 계산 (하루 전체가 아닌 접속 시점 기준)
    effective_start = max(work.start_time, created.time())
    if effective_start >= work.end_time:
        return False  # 이미 마감 후 접속 → 당일 슬롯 없음

    remaining_min = int(
        (datetime.combine(created.date(), work.end_time)
         - datetime.combine(created.date(), effective_start)).total_seconds() / 60
    )

    # 점심 시간이 잔여 구간 안에 걸치면 그만큼 차감
    if work.lunch_start and work.lunch_end:
        overlap_start = max(effective_start, work.lunch_start)
        overlap_end = min(work.end_time, work.lunch_end)
        if overlap_start < overlap_end:
            remaining_min -= int(
                (datetime.combine(created.date(), overlap_end)
                 - datetime.combine(created.date(), overlap_start)).total_seconds() / 60
            )

    # 접속 시각 이후에 이미 잡힌 예약만 차감 (과거 예약은 이미 선택 불가)
    close_dt = datetime.combine(created.date(), work.end_time).replace(tzinfo=KST)
    booked_rows = await db.execute(
        select(Schedule).where(
            Schedule.doctorid == schedule.doctorid,
            Schedule.confirmed_time >= created,
            Schedule.confirmed_time < close_dt,
            Schedule.scheduleid != schedule.scheduleid,
            Schedule.deleted_at.is_(None),
        )
    )
    booked_min = sum(s.duration_min or 0 for s in booked_rows.scalars().all())

    return (remaining_min - booked_min) >= (schedule.duration_min or 30)


async def _check_2a(
    schedule: Schedule,
    triage: TriageResult | None,
    doctor: Doctor | None,
    db: AsyncSession,
) -> dict:
    """2A: 응급도 대비 예약 타이밍."""
    if triage is None:
        return {"item": "예약 타이밍", "status": "SKIPPED", "detail": "triage 없어 urgency 알 수 없음"}
    try:
        urgency_num = int(triage.urgency_level_num)
    except (TypeError, ValueError):
        return {"item": "예약 타이밍", "status": "SKIPPED", "detail": "urgency_level_num 파싱 실패"}

    max_days = URGENCY_MAX_DAYS.get(urgency_num, 3)
    confirmed = to_kst(schedule.confirmed_time)
    created = to_kst(schedule.created_at)
    days_gap = (confirmed.date() - created.date()).days

    if days_gap > max_days:
        had_slots = await _has_same_day_slots(schedule, doctor, db)
        if had_slots is False:
            return {
                "item": "예약 타이밍",
                "status": "PASS",
                "detail": f"응급도 {urgency_num}: 당일 슬롯 없어 {days_gap}일 후 최선 배정",
            }
        detail = f"응급도 {urgency_num} 기준 최대 {max_days}일 이내여야 하나 {days_gap}일 후 예약"
        if had_slots is True:
            detail += " (사용자 선택)"
        return {"item": "예약 타이밍", "status": "WARN", "detail": detail}

    return {
        "item": "예약 타이밍",
        "status": "PASS",
        "detail": f"응급도 {urgency_num} 기준 {days_gap}일 후 예약 (기준 {max_days}일 이내)",
    }


async def _check_2b(
    schedule: Schedule,
    doctor: Doctor | None,
    db: AsyncSession,
) -> dict:
    """2B: 근무시간 준수."""
    confirmed = to_kst(schedule.confirmed_time)
    dow = confirmed.weekday()

    vet_row = await db.execute(
        select(VetWeeklySchedule).where(
            VetWeeklySchedule.doctorid == schedule.doctorid,
            VetWeeklySchedule.day_of_week == dow,
        )
    )
    work = vet_row.scalar_one_or_none()

    if work is None:
        if doctor is None or doctor.hospitalid is None:
            return {"item": "근무시간", "status": "SKIPPED", "detail": "근무표 없고 병원 정보 없음"}
        hosp_row = await db.execute(
            select(HospitalWeeklySchedule).where(
                HospitalWeeklySchedule.hospitalid == doctor.hospitalid,
                HospitalWeeklySchedule.day_of_week == dow,
            )
        )
        work = hosp_row.scalar_one_or_none()

    if work is None:
        return {"item": "근무시간", "status": "SKIPPED", "detail": "근무표 미등록"}
    if not work.is_open:
        return {"item": "근무시간", "status": "WARN", "detail": "휴무일에 예약됨"}

    appt_time = confirmed.time()
    appt_end = (confirmed + timedelta(minutes=schedule.duration_min)).time()

    issues = []
    if work.start_time and appt_time < work.start_time:
        issues.append(f"근무 시작({work.start_time}) 전 예약")
    if work.end_time and appt_end > work.end_time:
        issues.append(f"근무 종료({work.end_time}) 후 넘어감")
    if work.lunch_start and work.lunch_end:
        if appt_time < work.lunch_end and appt_end > work.lunch_start:
            issues.append(f"점심({work.lunch_start}~{work.lunch_end})과 겹침")

    if issues:
        return {"item": "근무시간", "status": "WARN", "detail": " / ".join(issues)}
    return {"item": "근무시간", "status": "PASS", "detail": "근무시간 내 예약"}


async def _check_2c(schedule: Schedule, db: AsyncSession) -> dict:
    """2C: 빈 슬롯 실제 검증."""
    end = schedule.confirmed_end_time or (
        schedule.confirmed_time + timedelta(minutes=schedule.duration_min)
    )
    overlap = await has_time_overlap(
        db,
        schedule.doctorid,
        schedule.confirmed_time,
        end,
        exclude_schedule_id=schedule.scheduleid,
    )
    if overlap:
        return {"item": "빈 슬롯", "status": "WARN", "detail": "예약 시간대에 다른 예약 존재 (충돌 감지)"}
    return {"item": "빈 슬롯", "status": "PASS", "detail": "충돌 없음"}


def _check_2d(schedule: Schedule, triage: TriageResult | None) -> dict:
    """2D: 문진→예약 핸드오프 수신 확인 (DB emrid 일치로 추론)."""
    if triage is None:
        return {"item": "핸드오프 수신", "status": "SKIPPED", "detail": "triage 없음 — 수신 여부 불명"}

    if schedule.emrid != triage.emrid:
        return {
            "item": "핸드오프 수신",
            "status": "WARN",
            "detail": (
                f"schedule.emrid({schedule.emrid}) ≠ triage.emrid({triage.emrid}) "
                "— 환자 불일치 의심"
            ),
        }
    return {
        "item": "핸드오프 수신",
        "status": "PASS",
        "detail": f"emrid={schedule.emrid} 일치 — triage→schedule 연결 정상 (추론)",
    }


# ── Check 3 — Chart ─────────────────────────────────────────────

async def _check_chart_quality(
    triage: TriageResult | None,
    draft: dict,
    intake: dict,
) -> dict:
    """5단계: LLM으로 차트 임상 품질 평가 — triage 결과와 일관성 체크."""
    from ai.llm import call_llm_json

    soap = draft.get("soap") or {}
    differential = draft.get("differential_diagnosis") or []

    chart_snippet = {
        "intake_summary": intake,
        "soap_S": soap.get("S", ""),
        "soap_A": soap.get("A", ""),
        "differential_diagnosis": differential[:5],
    }
    triage_context = (
        {
            "urgency_level": triage.urgency_level,
            "urgency_level_num": triage.urgency_level_num,
            "chief_complaint": triage.chief_complaint or "",
        }
        if triage
        else {}
    )

    prompt = (
        "너는 동물병원 AI 차트 검토자야. AI가 생성한 차트 초안의 임상 품질을 평가한다.\n\n"
        f"[트리아지 결과]\n{json.dumps(triage_context, ensure_ascii=False)}\n\n"
        f"[AI 차트 초안]\n{json.dumps(chart_snippet, ensure_ascii=False)}\n\n"
        "[평가 기준]\n"
        "1. SOAP A(Assessment)가 트리아지 응급도와 크게 모순되지 않는가?\n"
        "2. 주요 증상이 차트에 반영되어 있는가?\n"
        "3. 감별 진단이 증상에 근거가 있는가?(지어낸 병명·무관한 진단 없는가?)\n"
        "4. 임상적으로 명백히 잘못된 내용이 없는가?\n\n"
        "판정 기준: 위 4가지 중 2개 이상 문제가 있을 때만 WARN. 1개 정도 아쉬운 점은 PASS로 처리.\n"
        'JSON만 출력: {"result": "PASS" 또는 "WARN", "detail": "판단 이유 한 문장"}'
    )

    for attempt in range(2):
        try:
            out = await call_llm_json(prompt)
            result = (out.get("result") or "").upper()
            detail = out.get("detail") or ""
            if result in ("PASS", "WARN"):
                return {"item": "임상 품질", "status": result, "detail": detail}
        except Exception as exc:
            logger.warning("[Evaluation] Chart LLM 품질 평가 시도 %d 실패: %s", attempt + 1, exc)

    return {"item": "임상 품질", "status": "SKIPPED", "detail": "LLM 평가 실패"}


_A_KEYWORDS = ("의심", "가능성", "감별", "추정")
_P_KEYWORDS = ("검사", "처치", "재진", "모니터링")
# A/P는 "단정하지 않고 계획을 제시했는가"를 보는 체크라, 키워드가 그 자체를
# 부정하는 문맥("검사는 필요 없습니다")에 등장하면 요건을 충족한 것으로 보지 않는다.
_SOAP_NEG_KW = ("필요 없", "불필요", "해당 없음", "없습니다", "없음")


def _soap_section_issues(soap: dict) -> list[str]:
    """SOAP 섹션별 최소 요건 미달 항목 목록 (agent_bench.run_chart_eval과 공유).

    S: 30자 이상 — 주증상·경과를 쓰면 한 줄 이상
    O: '내원' 포함 — 차트 프롬프트가 "내원 시 확인 필요를 명시하고" 명시
    A: 추정 표현 포함(부정 문맥 제외) — 확정 진단 금지 지침에 따라 의심/가능성/감별/추정 중 하나 필수
    P: 계획 표현 포함(부정 문맥 제외) — 권장 검사·처치·재진·모니터링 중 하나 필수
    """
    issues = []

    s_text = str(soap.get("S", "")).strip()
    if len(s_text) < 30:
        issues.append("S(주증상·경과 미흡)")

    o_text = str(soap.get("O", "")).strip()
    if "내원" not in o_text:
        issues.append("O(신체검사 항목 미언급)")

    a_text = str(soap.get("A", "")).strip()
    if not a_text or not any(keyword_in_context(a_text, kw, _SOAP_NEG_KW) for kw in _A_KEYWORDS):
        issues.append("A(추정·감별 표현 없음)")

    p_text = str(soap.get("P", "")).strip()
    if not p_text or not any(keyword_in_context(p_text, kw, _SOAP_NEG_KW) for kw in _P_KEYWORDS):
        issues.append("P(다음 단계 계획 없음)")

    return issues


def _check_soap_sections(soap: dict) -> dict:
    """SOAP 섹션별 최소 요건 체크 (rule-based). 세부 기준은 `_soap_section_issues` 참고."""
    issues = _soap_section_issues(soap)
    if not issues:
        return {"item": "SOAP 섹션 완전성", "status": "PASS", "detail": "S/O/A/P 최소 요건 충족"}
    return {
        "item": "SOAP 섹션 완전성",
        "status": "WARN",
        "detail": f"미흡 섹션: {', '.join(issues)}",
    }


async def validate_chart(
    triage: TriageResult | None,
    report: Report | None,
) -> dict:
    if report is None:
        return {
            "status": "SKIPPED",
            "checks": [{"item": "정합성", "status": "SKIPPED", "detail": "차트 미생성"}],
        }

    draft = report.ai_draft_json

    if not isinstance(draft, dict):
        return {
            "status": "WARN",
            "checks": [{"item": "정합성", "status": "WARN", "detail": "ai_draft_json이 dict 아님"}],
        }

    intake = draft.get("intake_summary")
    if not isinstance(intake, dict):
        return {
            "status": "WARN",
            "checks": [{"item": "정합성", "status": "WARN", "detail": "intake_summary 없음 (차트 구조 이상)"}],
        }

    if not (intake.get("key_symptoms") or []):
        return {
            "status": "WARN",
            "checks": [{"item": "정합성", "status": "WARN", "detail": "key_symptoms 비어있음 (증상 미기록)"}],
        }

    soap_check = _check_soap_sections(draft.get("soap") or {})
    quality_check = await _check_chart_quality(triage, draft, intake)
    checks = [soap_check, quality_check]
    return {"status": _module_status(checks), "checks": checks}


# ── 결과 조립 ───────────────────────────────────────────────────

def _calc_completeness(triage_v: dict) -> float | None:
    """triage 체크 4개를 가중 평균해 문진 완전성 점수(0~10) 산출.

    완료 신호(40%) — urgency/chief_complaint/symptom_summary 필드 완전성
    컨텍스트 연속성(30%) — 추출 슬롯이 보호자 발화에 근거하는지
    응급도 정합성(15%) — 보호자 발화 vs urgency_level_num
    응급도 판단(15%) — chief_complaint vs urgency_level_num 내부 일관성
    PASS=1.0, WARN=0.5, SKIPPED=제외
    """
    _WEIGHTS = {
        "완료 신호": 0.40,
        "컨텍스트 연속성": 0.30,
        "응급도 정합성": 0.15,
        "응급도 판단": 0.15,
    }
    _STATUS_SCORE = {"PASS": 1.0, "WARN": 0.5}

    total_w = weighted = 0.0
    for c in triage_v.get("checks", []):
        w = _WEIGHTS.get(c.get("item", ""))
        s = _STATUS_SCORE.get(c.get("status", ""))
        if w and s is not None:
            total_w += w
            weighted += w * s

    if total_w == 0:
        return None
    return round((weighted / total_w) * 10, 1)


def _build_result(
    triage_v: dict,
    schedule_v: dict,
    chart_v: dict,
    conversation_v: dict | None = None,
) -> dict:
    checks = {"triage": triage_v, "schedule": schedule_v, "chart": chart_v}

    all_statuses = [
        c["status"]
        for module in checks.values()
        for c in module.get("checks", [])
    ]
    # ERROR도 WARN과 함께 ATTENTION으로 묶는다. overall에 별도의 "ERROR" 값을
    # 새로 두려면 프론트(EvalPanel.tsx)의 OverallStatus 타입·집계 로직까지
    # 같이 바꿔야 하는데, 그건 공통 CheckResult 스키마로 통일하는 Phase 5의
    # 몫이다. 지금은 "모듈이 죽었는데 OK로 보이는" 버그만 최소 수정한다 —
    # 개별 체크의 ERROR 상태 자체는 checks 안에 그대로 남아 있어 확인 가능.
    overall = "ATTENTION" if ("WARN" in all_statuses or "ERROR" in all_statuses) else "OK"

    completeness_score = _calc_completeness(triage_v)

    # SOAP 섹션 완전성 / 임상 품질 중 하나라도 WARN이면, "몇 점을 깎을지"는
    # 아직 근거가 없으므로 None("아직 근거 있는 점수를 계산할 수 없음")을
    # 반환한다. consistency_score의 실제 감점 폭은 Phase 6에서 golden
    # dataset 실측 기반으로 설계할 예정 — 그 전까지는 둘 다 PASS일 때만
    # 기존 값(10.0)을 그대로 쓴다.
    consistency_score = None
    _consistency_statuses = [
        c["status"]
        for c in chart_v.get("checks", [])
        if c.get("item") in ("정합성", "SOAP 섹션 완전성", "임상 품질")
    ]
    if _consistency_statuses and all(s == "PASS" for s in _consistency_statuses):
        consistency_score = 10.0

    warn_items = [
        c["item"]
        for module in checks.values()
        for c in module.get("checks", [])
        if c["status"] == "WARN"
    ]
    summary = (
        f"수의사 검토 권고: {', '.join(warn_items)}"
        if warn_items
        else "특이 검증 이슈 없음"
    )

    return {
        "overall": overall,
        "checks": checks,
        "completeness_score": completeness_score,
        "consistency_score": consistency_score,
        "summary": summary,
        "conversation_status": conversation_v,
    }


# ── DB 저장 (upsert) ────────────────────────────────────────────

async def _save_result(
    scheduleid: int,
    emrid: int,
    result: dict,
    db: AsyncSession,
) -> None:
    existing = await db.execute(
        select(ValidationResult).where(ValidationResult.scheduleid == scheduleid)
    )
    row = existing.scalar_one_or_none()

    score_breakdown = {"conversation": result.get("conversation_status")} if result.get("conversation_status") else None

    if row:
        row.overall = result["overall"]
        row.checks = result["checks"]
        row.completeness_score = result.get("completeness_score")
        row.consistency_score = result["consistency_score"]
        row.summary = result["summary"]
        row.score_breakdown = score_breakdown
    else:
        db.add(ValidationResult(
            emrid=emrid,
            scheduleid=scheduleid,
            overall=result["overall"],
            checks=result["checks"],
            completeness_score=None,
            consistency_score=result["consistency_score"],
            summary=result["summary"],
            score_breakdown=score_breakdown,
        ))

    await db.commit()
    logger.info("[Evaluation] 저장 scheduleid=%s overall=%s", scheduleid, result["overall"])


# ── 진입점 ────────────────────────────────────────────────────────

async def run_case_evaluation(scheduleid: int, db: AsyncSession) -> dict:
    """케이스 평가 진입점. scheduleid 하나로 triage/schedule/chart 검증."""
    logger.info("[Evaluation] 시작 scheduleid=%s", scheduleid)

    data = await _load_data(scheduleid, db)
    if data is None:
        return {"agent": "evaluation", "scheduleid": scheduleid, "error": "schedule 없음"}

    schedule: Schedule = data["schedule"]
    triage: TriageResult | None = data["triage"]
    report: Report | None = data["report"]
    chat_history: ChatHistory | None = data["chat_history"]
    doctor: Doctor | None = data["doctor"]
    emrid: int = data["emrid"]

    try:
        triage_v = await validate_triage(triage, chat_history)
    except Exception as exc:
        logger.exception("[Evaluation] Check 1 오류 scheduleid=%s", scheduleid)
        triage_v = {
            "status": "ERROR",
            "checks": [{"item": "모듈 오류", "status": "ERROR", "detail": str(exc)}],
        }

    try:
        schedule_v = await validate_schedule(schedule, triage, doctor, db)
    except Exception as exc:
        logger.exception("[Evaluation] Check 2 오류 scheduleid=%s", scheduleid)
        schedule_v = {
            "status": "ERROR",
            "checks": [{"item": "모듈 오류", "status": "ERROR", "detail": str(exc)}],
        }

    try:
        chart_v = await validate_chart(triage, report)
    except Exception as exc:
        logger.exception("[Evaluation] Check 3 오류 scheduleid=%s", scheduleid)
        chart_v = {
            "status": "ERROR",
            "checks": [{"item": "모듈 오류", "status": "ERROR", "detail": str(exc)}],
        }

    try:
        conversation_v = await _check_1e(triage, chat_history)
    except Exception as exc:
        logger.warning("[Evaluation] 1E 오류 scheduleid=%s: %s", scheduleid, exc)
        conversation_v = {"item": "대화 품질", "status": "SKIPPED", "detail": str(exc)}

    result = _build_result(triage_v, schedule_v, chart_v, conversation_v)
    await _save_result(scheduleid, emrid, result, db)

    logger.info("[Evaluation] 완료 scheduleid=%s overall=%s", scheduleid, result["overall"])
    return {"agent": "evaluation", "scheduleid": scheduleid, **result}
