from datetime import date

from core.holidays_kr import get_month_holidays


def test_constitution_day_included_as_ward_holiday():
    # 제헌절(7/17)은 법정공휴일은 아니지만 병동 기준으로는 휴일로 카운트 (오프 목표에 포함)
    result = get_month_holidays(2026, 7)
    assert date(2026, 7, 17) in result


def test_known_public_holidays_included():
    assert date(2026, 1, 1) in get_month_holidays(2026, 1)
    assert date(2026, 5, 5) in get_month_holidays(2026, 5)
    assert date(2026, 12, 25) in get_month_holidays(2026, 12)


def test_manual_extra_and_exclude_overrides():
    extra = {date(2026, 7, 20)}
    exclude = {date(2026, 1, 1)}
    result = get_month_holidays(2026, 7, extra=extra)
    assert date(2026, 7, 20) in result
    result2 = get_month_holidays(2026, 1, exclude=exclude)
    assert date(2026, 1, 1) not in result2
