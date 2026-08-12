"""여러 채점 함수가 공유하는, 부정 문맥을 인지하는 키워드 매칭.

기존 방식(`_is_phrase_assertive`, `_is_drug_prescribed`, `_check_soap_sections`의
A/P 체크)은 키워드 뒤 고정 길이(20~30자) 윈도우 안에서만 부정어를 찾았다. 그
결과 부정어가 키워드보다 앞에 오거나, 같은 문장이라도 윈도우 밖에 있으면
놓쳤다. 문장 단위로 바꿔 순서·거리에 관계없이 같은 문장 안의 부정 문맥을 잡는다.

완벽한 자연어 이해는 아니다(문장 안에 여러 절이 있으면 무관한 절의 부정어에
영향을 받을 수 있음) — Rule 체크로서의 최소 개선이며, 더 정교한 의미 판단이
필요한 곳은 하이브리드 게이트(1차 매칭 실패 시 LLM)를 쓴다.
"""
from __future__ import annotations

import re

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+|\n+")


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def keyword_in_context(text: str, keyword: str, negations: tuple[str, ...]) -> bool:
    """text 안에 keyword가 부정되지 않은 문맥으로 등장하면 True.

    keyword가 여러 문장에 걸쳐 등장할 수 있으므로, 부정 문맥이 아닌 문장이
    하나라도 있으면 True (전체가 부정 문맥일 때만 False).
    """
    if keyword not in text:
        return False
    for sentence in split_sentences(text):
        if keyword in sentence and not any(neg in sentence for neg in negations):
            return True
    return False
