"""생성된 근무표를 솔버와 독립적으로 전수 검증하는 모듈.

솔버가 "생성했다"는 것과 "규칙을 지켰다"는 것은 별개이므로, 생성 직후 반드시
이 검증기를 통과시켜 위반 리포트를 함께 확인한다 (데모 스크립트/테스트/UI 공용).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

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
    settings: dict | None = None,
) -> ValidationReport:
    from core.constraints import merge_ward_settings

    cfg = merge_ward_settings(settings)
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
        # 하한~상한 하드 범위 검증. S는 데이 보조라 D에만 포함, E는 순수 이브닝만.
        if not (req.D.minimum <= cnt[ShiftType.D] + cnt[ShiftType.S] <= req.D.maximum):
            v.append(f"{d}: D+S={cnt[ShiftType.D]}+{cnt[ShiftType.S]} (허용 {req.D.minimum}~{req.D.maximum})")
        if not (req.E.minimum <= cnt[ShiftType.E] <= req.E.maximum):
            v.append(f"{d}: E={cnt[ShiftType.E]} (허용 {req.E.minimum}~{req.E.maximum})")
        if not (req.N.minimum <= cnt[ShiftType.N] <= req.N.maximum):
            v.append(f"{d}: N={cnt[ShiftType.N]} (허용 {req.N.minimum}~{req.N.maximum})")

    # --- 차지 배치 (D/E/N, S 제외) -----------------------------------------
    for d in days:
        for s in (ShiftType.D, ShiftType.E, ShiftType.N):
            assigned = [n for n in nurses if shift(n.name, d) == s]
            if assigned and not any(n.can_charge for n in assigned):
                v.append(f"{d} {s.value}: 차지가능자 없음")

    # --- S 자격 -------------------------------------------------------------
    if not cfg.get("use_s_shift", True):
        for n in nurses:
            for d in days:
                if shift(n.name, d) == ShiftType.S:
                    v.append(f"{n.name} {d}: S 미사용 설정에서 S 배정")
    for n in nurses:
        if n.level in (NurseLevel.JUNIOR, NurseLevel.NEW_JUNIOR):
            continue
        for d in days:
            if shift(n.name, d) == ShiftType.S:
                v.append(f"{n.name} {d}: S 배정 자격 없음 (액팅만/신규만 가능)")

    # --- 개인별 규칙 ---------------------------------------------------------
    seniors = [n for n in nurses if n.level == NurseLevel.SENIOR_CHARGE]
    for d in days:
        # 근무별 차지 최소 N명 (평일·주말·D/E/N 각각 병동 설정). 인원이 적은 근무엔
        # 실제 배정 인원까지만 요구 (빈 근무는 위반 아님).
        prefix = "weekend" if d.weekday() >= 5 else "weekday"
        for shift_t in (ShiftType.D, ShiftType.E, ShiftType.N):
            total_on = sum(1 for n in nurses if shift(n.name, d) == shift_t)
            charge_min = min(cfg[f"{prefix}_charge_{shift_t.value}"], total_on)
            if charge_min <= 0:
                continue
            charge_c = sum(1 for n in nurses if n.can_charge and shift(n.name, d) == shift_t)
            if charge_c < charge_min:
                v.append(f"{d} {shift_t.value}: charge-capable staff {charge_c} < {charge_min}")
        if seniors:
            # 데이는 최대 2명(하드), 이브닝·나이트는 검증 제외.
            senior_d = sum(1 for n in seniors if shift(n.name, d) == ShiftType.D)
            if senior_d > 2:
                v.append(f"{d} D: senior staff {senior_d} > 2")

    for n in nurses:
        if getattr(n, "is_helper", False):
            continue  # 헬퍼는 오프·연차·나이트월범위 등 개인 규칙 대상이 아님
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

        # 가능한 듀티
        n_count = seq.count(ShiftType.N)
        allowed = n.allowed_shifts or {ShiftType.D, ShiftType.E, ShiftType.N}
        bad = [s for s in seq if s in (ShiftType.D, ShiftType.E, ShiftType.N) and s not in allowed]
        if bad:
            v.append(f"{n.name}: 가능 듀티 밖 근무 {len(bad)}건 배정")

        # 나이트 전담: N 개수는 개인 상한만큼 고정
        if getattr(n, "is_night_dedicated", False):
            if n_count != n.max_n_hard:
                v.append(f"{n.name}: 나이트 전담 N {n_count}개 (고정 {n.max_n_hard}개여야 함)")
        # 일반 나이트 가능 인원: 월 N 개수는 개인 N상한 이하 (하한 없음)
        elif ShiftType.N in allowed and n.max_n_hard > 0:
            if n_count > n.max_n_hard:
                v.append(f"{n.name}: 월 N {n_count}개 (개인 상한 {n.max_n_hard} 초과)")

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
        # 나이트 전담은 나이트 외 날이 전부 오프라 월간 오프 목표 대상이 아니다.
        if not getattr(n, "is_night_dedicated", False) and o_count != target:
            v.append(f"{n.name}: O {o_count}개 != 목표 {target}개")

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
        and daily_counts[d][ShiftType.E] >= requirements[d].E.target
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
        and requirements[d].E.minimum <= daily_counts[d][ShiftType.E] <= requirements[d].E.maximum
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
        if getattr(n, "is_helper", False):
            continue
        seq = [shift(n.name, d) for d in days]
        allowed = n.allowed_shifts or {ShiftType.D, ShiftType.E, ShiftType.N}
        if any(s in (ShiftType.D, ShiftType.E, ShiftType.N) and s not in allowed for s in seq):
            allowed_violators.append(n.name)
        if getattr(n, "is_night_dedicated", False):
            if seq.count(ShiftType.N) != n.max_n_hard:
                n_range_violators.append(f"{n.name}(N {seq.count(ShiftType.N)})")
        elif ShiftType.N in allowed and n.max_n_hard > 0:
            if seq.count(ShiftType.N) > n.max_n_hard:
                n_range_violators.append(f"{n.name}(N {seq.count(ShiftType.N)})")
        if not getattr(n, "is_night_dedicated", False):
            o_count = seq.count(ShiftType.O)
            target = off_target.get(n.name, 0)
            if o_count != target:
                off_cap_violators.append(f"{n.name}(O {o_count}개)")
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
    add_check("월 나이트 개수", "전체", "개인 N 상한 이하 (전담은 상한만큼 고정)", agg(n_range_violators), not n_range_violators)
    add_check("오프 개수", "전체", "O = 목표 오프일수", agg(off_cap_violators), not off_cap_violators)

    return report
