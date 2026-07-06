from __future__ import annotations

from datetime import date
from typing import Optional

import holidays as holidays_lib

# 병동 기준 공휴일 = 법정공휴일 + 아래 추가 휴일.
# 제헌절(7/17)은 2008년부터 법정공휴일은 아니지만 이 병동은 휴일로 카운트한다
# (오프 목표일수 계산에 포함 — 사용자 확정 사항).
_WARD_EXTRA_MONTH_DAY = {(7, 17)}


def get_month_holidays(
    year: int,
    month: int,
    extra: Optional[set[date]] = None,
    exclude: Optional[set[date]] = None,
) -> set[date]:
    """병동 기준 공휴일(법정 + 병동 추가 휴일)을 계산해 해당 월의 날짜 집합을 반환.

    extra: 라이브러리가 놓친 임시/대체공휴일 등을 수동으로 추가
    exclude: 잘못 포함된 날짜를 수동으로 제외
    """
    kr_holidays = holidays_lib.KR(years=year, categories=("public",))
    result = {d for d in kr_holidays if d.year == year and d.month == month}
    result |= {
        date(year, m, dd) for (m, dd) in _WARD_EXTRA_MONTH_DAY if m == month
    }
    if extra:
        result |= {d for d in extra if d.year == year and d.month == month}
    if exclude:
        result -= exclude
    return result
