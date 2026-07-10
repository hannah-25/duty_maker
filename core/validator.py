"""생성된 근무표를 솔버와 독립적으로 전수 검증하는 모듈.

솔버가 "생성했다"는 것과 "규칙을 지켰다"는 것은 별개이므로, 생성 직후 반드시
이 검증기를 통과시켜 위반 리포트를 함께 확인한다 (데모 스크립트/테스트/UI 공용).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from core.constraints import N_MONTHLY_RANGE_DEFAULT
from core.models import (
    DayRequirement,
    Nurse,
    NurseLevel,
    ShiftType,
    month_dates,
)

WORKING = (ShiftType.D, ShiftType.E, ShiftType.N, ShiftType.S)
REST = (ShiftType.O, ShiftType.AL)


@dataclass
class ValidationReport:
    violations: list[str] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)
    # 사용자 입력 제약별 반영 여부 체크리스트 (UI 표시용)
    checklist: list[dict[str, object]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def summary(self) -> str:
        lines = []
        if self.ok:
            lines.append("[검증 통과] 모든 하드 규칙 준수")
        else:
            lines.append(f"[검증 실패] 위반 {len(self.violations)}건:")
            lines.extend(f"  - {v}" for v in self.violations)
        for key, value in self.stats.items():
            lines.append(f"  {key}: {value}")
        return "\n".join(lines)


def validate_schedule(
    nurses: list[Nurse],
    year: int,
    month: int,
    assignments: dict[tuple[str, date], ShiftType],
    requirements: dict[date, DayRequirement],
    off_target: dict[str, int],
    n_monthly_range: tuple[int, int] = N_MONTHLY_RANGE_DEFAULT,
) -> ValidationReport:
    report = ValidationReport()
    days = month_dates(year, month)
    day_set = set(days)
    v = report.violations

    def shift(nurse_name: str, d: date):
        return assignments.get((nurse_name, d))

    # --- 배정 완전성 -------------------------------------------------------
    for n in nurses:
        for d in days:
            if shift(n.name, d) is None:
                v.append(f"{n.name} {d}: 배정 없음")

    # --- 일별 인원 (하드 범위) ---------------------------------------------
    daily_counts = {}
    for d in days:
        req = requirements[d]
        cnt = {s: sum(1 for n in nurses if shift(n.name, d) == s) for s in WORKING}
        daily_counts[d] = cnt
        if not (req.D.minimum <= cnt[ShiftType.D] + cnt[ShiftType.S] <= req.D.maximum):
            v.append(f"{d}: D+S={cnt[ShiftType.D]}+{cnt[ShiftType.S]} (허용 {req.D.minimum}~{req.D.maximum})")
        if not (req.E.minimum <= cnt[ShiftType.E] + cnt[ShiftType.S] <= req.E.maximum):
            v.append(f"{d}: E+S={cnt[ShiftType.E]}+{cnt[ShiftType.S]} (허용 {req.E.minimum}~{req.E.maximum})")
        if not (req.N.minimum <= cnt[ShiftType.N] <= req.N.maximum):
            v.append(f"{d}: N={cnt[ShiftType.N]} (허용 {req.N.minimum}~{req.N.maximum})")
        if cnt[ShiftType.S] > 1:
            v.append(f"{d}: S {cnt[ShiftType.S]}명 (하루 최대 1명)")

    # --- 차지 배치 (D/E/N, S 제외) -----------------------------------------
    for d in days:
        for s in (ShiftType.D, ShiftType.E, ShiftType.N):
            assigned = [n for n in nurses if shift(n.name, d) == s]
            if assigned and not any(n.can_charge for n in assigned):
                v.append(f"{d} {s.value}: 차지가능자 없음")

    # --- S 자격 -------------------------------------------------------------
    for n in nurses:
        if n.level in (NurseLevel.JUNIOR, NurseLevel.NEW_JUNIOR):
            continue
        for d in days:
            if shift(n.name, d) == ShiftType.S:
                v.append(f"{n.name} {d}: S 배정 자격 없음 (액팅만/신규만 가능)")

    # --- 개인별 규칙 ---------------------------------------------------------
    seniors = [n for n in nurses if n.level == NurseLevel.SENIOR_CHARGE]
    for d in days:
        charge_d = sum(
            1
            for n in nurses
            if n.can_charge and shift(n.name, d) == ShiftType.D
        )
        if charge_d < 2:
            v.append(f"{d}: D charge-capable staff {charge_d} < 2")
        if seniors:
            for s in (ShiftType.D, ShiftType.E):
                senior_count = sum(1 for n in seniors if shift(n.name, d) == s)
                if senior_count > 2:
                    v.append(f"{d} {s.value}: senior staff {senior_count} > 2")
            senior_n = sum(1 for n in seniors if shift(n.name, d) == ShiftType.N)
            if senior_n != 1:
                v.append(f"{d} N: senior staff {senior_n} != 1")

    lo, hi = n_monthly_range
    for n in nurses:
        seq = [shift(n.name, d) for d in days]

        # 연속근무 5일 이하
        consecutive = 0
        for s in seq:
            if s in REST:
                consecutive = 0
            else:
                consecutive += 1
                if consecutive > 5:
                    v.append(f"{n.name}: 연속근무 {consecutive}일 (최대 5일)")
                    break

        # 나이트 연속 3일 이하 + 블록 종료 후 2일 휴식
        i = 0
        while i < len(seq):
            if seq[i] != ShiftType.N:
                i += 1
                continue
            block_start = i
            while i < len(seq) and seq[i] == ShiftType.N:
                i += 1
            block_len = i - block_start
            if block_len > 3:
                v.append(f"{n.name}: 나이트 {block_len}일 연속 (최대 3일)")
            if i < len(seq):  # 블록이 월내에서 끝남 -> 이후 2일 휴식
                for off in range(2):
                    j = i + off
                    if j < len(seq) and seq[j] not in REST:
                        v.append(f"{n.name} {days[j]}: 나이트 블록 종료 후 2일 휴식 위반 ({seq[j].value})")

        # E 후 D/S 불가
        for k in range(len(seq) - 1):
            if seq[k] == ShiftType.E and seq[k + 1] in (ShiftType.D, ShiftType.S):
                v.append(f"{n.name} {days[k + 1]}: E 다음날 {seq[k + 1].value} 배정 금지")

        # E → 휴식 1일 → D/S 불가 (하루만 쉬고 데이 출근 금지)
        for k in range(len(seq) - 2):
            if (
                seq[k] == ShiftType.E
                and seq[k + 1] in REST
                and seq[k + 2] in (ShiftType.D, ShiftType.S)
            ):
                v.append(f"{n.name} {days[k + 2]}: E→휴식→{seq[k + 2].value} 배정 금지")

        # 가능한 듀티
        n_count = seq.count(ShiftType.N)
        allowed = n.allowed_shifts or {ShiftType.D, ShiftType.E, ShiftType.N}
        bad = [s for s in seq if s in (ShiftType.D, ShiftType.E, ShiftType.N) and s not in allowed]
        if bad:
            v.append(f"{n.name}: 가능 듀티 밖 근무 {len(bad)}건 배정")

        # 월 N 개수 범위 (나이트 가능 인원만)
        if ShiftType.N in allowed and n.max_n_hard > 0:
            upper = min(hi, n.max_n_hard)
            lower = min(lo, upper)
            if not (lower <= n_count <= upper):
                v.append(f"{n.name}: 월 N {n_count}개 (허용 {lower}~{upper})")

        # 평일만 근무자 주말 휴식
        if n.weekday_only:
            for d in days:
                if d.weekday() >= 5 and shift(n.name, d) not in REST:
                    v.append(f"{n.name} {d}: 평일만 근무자인데 주말 근무 배정")

        # 오프 상한
        o_count = seq.count(ShiftType.O)
        al_count = seq.count(ShiftType.AL)
        if n.al_target is not None and al_count != n.al_target:
            v.append(f"{n.name}: 연차 {al_count}개 != 목표 {n.al_target}개")
        target = off_target.get(n.name, 0)
        if o_count > target:
            v.append(f"{n.name}: O {o_count}개 > 목표 {target}개 (초과분은 연차여야 함)")

    # --- 통계 ----------------------------------------------------------------
    per_nurse = {}
    for n in nurses:
        seq = [shift(n.name, d) for d in days]
        target = off_target.get(n.name, 0)
        al_count = seq.count(ShiftType.AL)
        per_nurse[n.name] = {
            "근무": sum(1 for s in seq if s in WORKING),
            "N": seq.count(ShiftType.N),
            "O": seq.count(ShiftType.O),
            "연차": al_count,
            "연차목표": "-" if n.al_target is None else n.al_target,
            "오프편차": seq.count(ShiftType.O) - target,
        }
    report.stats["개인별"] = per_nurse
    report.stats["연차 총계"] = sum(p["연차"] for p in per_nurse.values())
    target_hit = sum(
        1
        for d in days
        if daily_counts[d][ShiftType.D] + daily_counts[d][ShiftType.S] >= requirements[d].D.target
        and daily_counts[d][ShiftType.E] + daily_counts[d][ShiftType.S] >= requirements[d].E.target
    )
    report.stats["D/E 목표 달성일"] = f"{target_hit}/{len(days)}"

    # --- 제약 반영 체크리스트 -------------------------------------------------
    def add_check(item: str, subject: str, expected: str, actual: str, ok: bool):
        report.checklist.append(
            {"항목": item, "대상": subject, "기준(입력)": expected, "실제": actual, "반영": ok}
        )

    staffing_ok = sum(
        1
        for d in days
        if requirements[d].D.minimum <= daily_counts[d][ShiftType.D] + daily_counts[d][ShiftType.S] <= requirements[d].D.maximum
        and requirements[d].E.minimum <= daily_counts[d][ShiftType.E] + daily_counts[d][ShiftType.S] <= requirements[d].E.maximum
        and requirements[d].N.minimum <= daily_counts[d][ShiftType.N] <= requirements[d].N.maximum
    )
    add_check(
        "일별 인원 기준", "전체", "D/E/N 하한~상한",
        f"{staffing_ok}/{len(days)}일 충족", staffing_ok == len(days),
    )

    allowed_violators: list[str] = []
    n_range_violators: list[str] = []
    off_cap_violators: list[str] = []
    for n in nurses:
        seq = [shift(n.name, d) for d in days]
        allowed = n.allowed_shifts or {ShiftType.D, ShiftType.E, ShiftType.N}
        if any(s in (ShiftType.D, ShiftType.E, ShiftType.N) and s not in allowed for s in seq):
            allowed_violators.append(n.name)
        if ShiftType.N in allowed and n.max_n_hard > 0:
            upper = min(hi, n.max_n_hard)
            lower = min(lo, upper)
            n_count = seq.count(ShiftType.N)
            if not (lower <= n_count <= upper):
                n_range_violators.append(f"{n.name}(N {n_count})")
        if seq.count(ShiftType.O) > off_target.get(n.name, 0):
            off_cap_violators.append(n.name)
        if n.al_target is not None:
            al_count = seq.count(ShiftType.AL)
            add_check(
                "연차 목표", n.name, f"{n.al_target}개",
                f"{al_count}개", al_count == n.al_target,
            )
        if n.weekday_only:
            weekend_work = sum(
                1 for d, s in zip(days, seq) if d.weekday() >= 5 and s not in REST
            )
            add_check(
                "평일만 근무", n.name, "주말 근무 금지",
                "위반 없음" if weekend_work == 0 else f"주말 근무 {weekend_work}건",
                weekend_work == 0,
            )

    def agg(names: list[str]) -> str:
        return "위반 없음" if not names else "위반: " + ", ".join(names)

    add_check("가능 듀티", "전체", "간호사별 가능 듀티만 배정", agg(allowed_violators), not allowed_violators)
    add_check("월 나이트 개수", "전체", f"{lo}~{hi}개 & 개인 N 상한 이하", agg(n_range_violators), not n_range_violators)
    add_check("오프 상한", "전체", "O ≤ 목표 오프일수 (초과 휴식은 연차)", agg(off_cap_violators), not off_cap_violators)

    return report
