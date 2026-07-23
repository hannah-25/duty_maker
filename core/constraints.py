from __future__ import annotations

from datetime import date, timedelta

from ortools.sat.python import cp_model

from core.models import (
    DayRequirement,
    DutyRequest,
    ExceptionRequest,
    Nurse,
    NurseLevel,
    ShiftType,
)

# 근무 배정 변수 카테고리. 연차(AL)도 모델 변수로 직접 다룬다:
# O는 월간 목표 개수로 고정되는 정규 휴무이며, AL은 별도 연차 휴식이다.
MODEL_SHIFTS = (ShiftType.D, ShiftType.E, ShiftType.N, ShiftType.S, ShiftType.O, ShiftType.AL)

# 소프트 벌점 가중치 (상대적 우선순위가 중요)
WEIGHT_TIER3_EXCEPTION = 1000
WEIGHT_DUTY_REQUEST = 5000
WEIGHT_TARGET_STAFFING = 30  # 목표 인원 미달 1명당
MONDAY_TARGET_MULTIPLIER = 3  # 월요일 목표 미달 가중 (최우선)
WEIGHT_N_ISOLATED = 35
WEIGHT_S_DAILY = 30  # 하루 S 2명 이상
WEIGHT_NIGHT_SOFT_CONSECUTIVE = 25
WEIGHT_NIGHT_OFF_RETURN = 25  # 나이트 후 휴식이 끝난 첫 근무가 다시 나이트인 패턴 회피
WEIGHT_WORKDAY_STREAK = 25  # 연속 근무 5일 이상 (기본 3~4일 선호)
WEIGHT_OFF_STREAK = 25  # 연속 오프 4일 이상 (2~3일씩 분산 선호)
WEIGHT_WEEKEND_OFF_MIN = 70  # 토·일 통주말 오프 최소 월 1회 (전원 커버)
WEIGHT_WEEKEND_OFF_PREF = 15  # 통주말 오프 2회 이상이면 이상적 (약)
WEIGHT_ISOLATED_WORKDAY = 20
WEIGHT_EXCLUDED_SHIFT = 20
WEIGHT_SENIOR_E = 20  # 시니어 같은 날 이브닝 2명 이상
WEIGHT_S_USAGE = 15
WEIGHT_NEW_JUNIOR_OVERLAP = 12
WEIGHT_AL_EXCESS = 10
WEIGHT_AL_BALANCE = 40  # 연차를 균등하게 — 최대 연차 인원 최소화  # 연차 1인 1개 초과분
WEIGHT_TRINITY_A_PAIR_SHORTFALL = 30_000
WEIGHT_TRINITY_A_PAIR_CONCENTRATION = 8_000

# 병동별 제약 설정 기본값 — 병동마다 다르게 켜고 끌 수 있다.
# (월간 오프 목표는 항상 적용되는 규칙이라 설정에 없음.
#  월 나이트 상한은 명단의 개인 N상한으로 대체되어 별도 설정이 없음.)
# 근무별 차지 가능자 최소 인원 (평일/주말 각각). 모든 근무엔 charge_placement로
# 최소 1명이 이미 보장되므로, 이 값은 "그 이상"을 요구할 때만 의미가 있다.
DEFAULT_WARD_SETTINGS = {
    "use_s_shift": True,
    "weekday_charge_D": 2,
    "weekday_charge_E": 1,
    "weekday_charge_N": 1,
    "weekend_charge_D": 1,
    "weekend_charge_E": 1,
    "weekend_charge_N": 1,
}


def merge_ward_settings(settings: dict | None) -> dict:
    merged = dict(DEFAULT_WARD_SETTINGS)
    if settings:
        # 병동별 추가 제약 플래그도 보존한다. 기본 설정 키만 복사하면
        # 트리니티 A 전용 같은 솔버 옵션이 모델에 도달하지 못한다.
        merged.update({key: value for key, value in settings.items() if value is not None})
    return merged


class ScheduleModel:
    """CP-SAT 모델 + 변수 + 제약조건을 함께 관리하는 빌더."""

    def __init__(
        self,
        nurses: list[Nurse],
        current_days: list[date],
        lookback_days: list[date],
        history: dict[tuple[str, date], ShiftType],
        requirements: dict[date, DayRequirement],
        off_target: dict[str, int],
        use_assumptions: bool = False,
        settings: dict | None = None,
    ):
        self.model = cp_model.CpModel()
        self.nurses = nurses
        self.nurse_by_name = {n.name: n for n in nurses}
        self.current_days = current_days
        self.lookback_days = lookback_days
        self.all_days = lookback_days + current_days
        self.history = history
        self.requirements = requirements
        self.off_target = off_target
        self.settings = merge_ward_settings(settings)
        # use_assumptions=False(기본): 모든 Tier1을 무조건 하드로 적용, presolve가 완전히
        # 동작해 훨씬 빠르고 좋은 해를 찾음 (일반적인 생성 경로).
        # use_assumptions=True: 각 규칙을 assumption 리터럴로 감싸 Infeasible 원인 진단이
        # 가능하지만, OR-Tools가 "assumption 존재시 모든 실행가능해 보존"을 위해 presolve를
        # 제한하므로 훨씬 느리고 최적화 품질이 떨어짐 -> Infeasible 판정 시에만 별도로 사용.
        self.use_assumptions = use_assumptions

        self.shift_vars: dict[tuple[str, date], dict[ShiftType, cp_model.IntVar]] = {}
        self.penalties: list[tuple[str, int, object]] = []  # (category, weight, var/expr)
        self.assumptions: dict[str, cp_model.IntVar] = {}
        self._lookback_set = set(lookback_days)

        self._build_variables()

    # ---------------------------------------------------------- variables --
    def _build_variables(self):
        for nurse in self.nurses:
            for day in self.current_days:
                vs = {
                    s: self.model.NewBoolVar(f"{nurse.name}_{day.isoformat()}_{s.value}")
                    for s in MODEL_SHIFTS
                }
                self.model.Add(sum(vs.values()) == 1)
                self.shift_vars[(nurse.name, day)] = vs

    def val(self, nurse_name: str, day: date, shift: ShiftType):
        """day가 현재월(변수)이면 BoolVar, 과거(lookback)면 0/1 정수를 반환."""
        key = (nurse_name, day)
        if key in self.shift_vars:
            return self.shift_vars[key][shift]
        assigned = self.history.get(key, ShiftType.O)
        return 1 if assigned == shift else 0

    def rest_val(self, nurse_name: str, day: date):
        """휴식(O 또는 연차) 여부. 현재월이면 선형식(O+AL), lookback이면 0/1 상수."""
        key = (nurse_name, day)
        if key in self.shift_vars:
            vs = self.shift_vars[key]
            return vs[ShiftType.O] + vs[ShiftType.AL]
        assigned = self.history.get(key, ShiftType.O)
        return 1 if assigned in (ShiftType.O, ShiftType.AL) else 0

    def _n_status(self, nurse_name: str, day: date):
        """해당 날짜의 N 여부. 현재월이면 BoolVar, lookback이면 0/1 상수, 그 외(다음달 등)는 None."""
        key = (nurse_name, day)
        if key in self.shift_vars:
            return self.shift_vars[key][ShiftType.N]
        if day in self._lookback_set:
            return 1 if self.history.get(key) == ShiftType.N else 0
        return None  # 범위 밖 (알 수 없음)

    def _assumption(self, category: str):
        """진단 모드가 아니면 None(무조건 하드 적용), 진단 모드면 assumption 리터럴 반환."""
        if not self.use_assumptions:
            return None
        if category not in self.assumptions:
            self.assumptions[category] = self.model.NewBoolVar(f"assume_{category}")
        return self.assumptions[category]

    @staticmethod
    def _enforce(constraint, *lits):
        """None이 아닌 리터럴에 대해서만 OnlyEnforceIf 적용 (진단모드 아니면 전부 None -> 무조건 적용)."""
        active = [lit for lit in lits if lit is not None]
        if active:
            constraint.OnlyEnforceIf(active)

    # ------------------------------------------------------------ Tier 1 --
    def add_tier1_hard_constraints(self):
        self._rule_n_then_2off()
        self._rule_e_then_d_forbidden()
        self._rule_max_consecutive_workdays()
        self._rule_max_consecutive_nights()
        self._rule_allowed_shifts()
        self._rule_n_monthly_cap()
        self._rule_night_balance()
        self._rule_night_dedicated()
        self._rule_staffing_range()
        self._rule_charge_placement()
        self._rule_charge_minimum()
        self._rule_senior_same_shift_cap()
        self._rule_s_enabled()
        self._rule_s_eligibility()
        self._rule_weekday_only()
        self._rule_al_target()
        self._rule_off_cap()
        self._rule_helpers()

    def add_fixed_assignments(
        self,
        assignments: dict[tuple[str, date], ShiftType],
        *,
        require_change_from: dict[tuple[str, date], ShiftType] | None = None,
    ) -> None:
        """Freeze cells while keeping all month-wide constraints active.

        In diagnostic mode the frozen cells are grouped under one assumption so
        an infeasible partial regeneration can report that the selected region
        is too small, instead of returning an opaque solver status.
        """
        lit = self._assumption("fixed_assignments")
        for key, shift in assignments.items():
            if key not in self.shift_vars:
                continue
            self._enforce(self.model.Add(self.shift_vars[key][shift] == 1), lit)

        if require_change_from:
            change_terms = [
                1 - self.shift_vars[key][shift]
                for key, shift in require_change_from.items()
                if key in self.shift_vars
            ]
            if change_terms:
                self._enforce(self.model.Add(sum(change_terms) >= 1), lit)

    def _rule_helpers(self):
        """외부 병동 헬퍼의 근무를 고정한다.

        - 연차는 쓰지 않는다 (비근무일은 빈칸=O).
        - 모드 A(helper_shifts): 지정 날짜·듀티를 고정, 나머지 날은 O(빈칸).
        - 모드 B(helper_workdays): 월 총 근무일수만 고정, 어느 날 무슨 듀티인지는 솔버가 결정.
        안전 제약(나이트 후 휴식·연속근무 상한·가능 듀티 등)은 일반 규칙에서 함께 적용된다.
        """
        lit = self._assumption("helpers")
        work_shifts = (ShiftType.D, ShiftType.E, ShiftType.N, ShiftType.S)
        for nurse in self.nurses:
            if not nurse.is_helper:
                continue
            for day in self.current_days:
                self._enforce(self.model.Add(self.val(nurse.name, day, ShiftType.AL) == 0), lit)
            if nurse.helper_workdays is not None:
                worked = sum(
                    self.val(nurse.name, day, s) for day in self.current_days for s in work_shifts
                )
                self._enforce(self.model.Add(worked == int(nurse.helper_workdays)), lit)
            else:
                for day in self.current_days:
                    if day in nurse.helper_shifts:
                        self._enforce(
                            self.model.Add(self.val(nurse.name, day, nurse.helper_shifts[day]) == 1),
                            lit,
                        )
                    else:
                        self._enforce(self.model.Add(self.val(nurse.name, day, ShiftType.O) == 1), lit)

    def _rule_n_then_2off(self):
        """나이트 블록이 끝나면(N 다음날이 N이 아니면) 그 후 2일은 반드시 휴식(O/연차).

        N N X X 처럼 연속 나이트는 허용된다 (연속 상한 3일은 _rule_max_consecutive_nights 담당).
        매 N마다 다음날 오프를 강제하면 연속 나이트 자체가 금지되므로 반드시 "블록 종료" 시점에만
        적용해야 한다. 블록이 월말을 넘어가는지는 알 수 없으므로 그 경우는 건너뛰고,
        다음 달 생성 시 lookback 이력을 통해 이어서 처리된다.

        주의: 상태값은 int(과거 확정값) 또는 BoolVar(현재월 변수)일 수 있다. ortools 변수는
        `==`/`if`가 파이썬 bool이 아닌 제약식 객체를 만들므로 isinstance로 상수 여부를 판별한다.
        """
        lit = self._assumption("n_then_2off")
        for nurse in self.nurses:
            for day in self.all_days:
                cur = self._n_status(nurse.name, day)
                if isinstance(cur, int) and cur == 0:
                    continue
                nxt = self._n_status(nurse.name, day + timedelta(days=1))
                if nxt is None:
                    continue  # 블록이 월말 너머로 이어지는지 판단 불가
                if isinstance(nxt, int) and nxt == 1:
                    continue  # 블록 계속 (둘 다 과거 확정 N)
                conds = [lit]
                if not isinstance(cur, int):
                    conds.append(cur)
                if not isinstance(nxt, int):
                    conds.append(nxt.Not())
                for offset in (1, 2):
                    target = day + timedelta(days=offset)
                    if (nurse.name, target) not in self.shift_vars:
                        continue
                    rest_t = self.rest_val(nurse.name, target)
                    self._enforce(self.model.Add(rest_t == 1), *conds)

    def _rule_e_then_d_forbidden(self):
        lit = self._assumption("e_then_d")
        for nurse in self.nurses:
            for day in self.all_days:
                e_val = self.val(nurse.name, day, ShiftType.E)
                is_const = isinstance(e_val, int)
                if is_const and e_val == 0:
                    continue
                next_day = day + timedelta(days=1)
                if (nurse.name, next_day) not in self.shift_vars:
                    continue
                d_next = self.val(nurse.name, next_day, ShiftType.D)
                s_next = self.val(nurse.name, next_day, ShiftType.S)
                if is_const:  # e_val == 1로 확정된 과거 데이터
                    self._enforce(self.model.Add(d_next == 0), lit)
                    self._enforce(self.model.Add(s_next == 0), lit)
                else:
                    self._enforce(self.model.Add(d_next == 0), e_val, lit)
                    self._enforce(self.model.Add(s_next == 0), e_val, lit)

    def _rule_max_consecutive_workdays(self, window: int = 6):
        lit = self._assumption("max_consecutive_workdays")
        for nurse in self.nurses:
            for i in range(len(self.all_days) - window + 1):
                win = self.all_days[i : i + window]
                if not any((nurse.name, d) in self.shift_vars for d in win):
                    continue
                rest_sum = sum(self.rest_val(nurse.name, d) for d in win)
                # 연속 6일 중 최소 1일은 휴식 (= 연속근무 5일 이하와 동치)
                self._enforce(self.model.Add(rest_sum >= 1), lit)

    def _rule_max_consecutive_nights(self, window: int = 4, max_n: int = 3):
        lit = self._assumption("max_consecutive_nights")
        for nurse in self.nurses:
            for i in range(len(self.all_days) - window + 1):
                win = self.all_days[i : i + window]
                if not any((nurse.name, d) in self.shift_vars for d in win):
                    continue
                n_sum = sum(self.val(nurse.name, d, ShiftType.N) for d in win)
                self._enforce(self.model.Add(n_sum <= max_n), lit)

    def _rule_allowed_shifts(self):
        lit = self._assumption("allowed_shifts")
        duty_shifts = (ShiftType.D, ShiftType.E, ShiftType.N)
        for nurse in self.nurses:
            allowed = nurse.allowed_shifts or set(duty_shifts)
            for day in self.current_days:
                for shift in duty_shifts:
                    if shift not in allowed:
                        self._enforce(self.model.Add(self.val(nurse.name, day, shift) == 0), lit)

    def _n_eligible(self, nurse: Nurse) -> bool:
        """월 N 개수 범위 규칙의 적용 대상인지 (일반 나이트 가능 인원).

        헬퍼와 나이트 전담은 제외 — 전담은 _rule_night_dedicated가 개수를 고정한다.
        """
        return (
            ShiftType.N in (nurse.allowed_shifts or set())
            and nurse.max_n_hard > 0
            and not nurse.is_helper
            and not nurse.is_night_dedicated
        )

    def _rule_n_monthly_cap(self):
        """일반 나이트 가능 인원(전담 제외)은 월 N 개수가 개인 N상한(max_n_hard) 이하.

        하한은 두지 않는다 — 나이트 인력이 적으면 그 인원에게 자연스럽게 몰리는 게 맞고,
        분배는 일별 인원 요건(staffing_range)이 알아서 만든다.
        """
        lit = self._assumption("n_monthly_cap")
        for nurse in self.nurses:
            if not self._n_eligible(nurse):
                continue
            total_n = sum(self.val(nurse.name, d, ShiftType.N) for d in self.current_days)
            self._enforce(self.model.Add(total_n <= nurse.max_n_hard), lit)

    def _rule_night_balance(self, maximum_gap: int = 2):
        """Keep monthly N counts within ``maximum_gap`` for general N-capable nurses.

        Helpers and N-dedicated staff are deliberately excluded: helpers have a
        separately fixed workload and dedicated staff have a separately fixed N
        quota.  Nurses unable to work N are also outside this comparison.
        """
        eligible = [nurse for nurse in self.nurses if self._n_eligible(nurse)]
        if len(eligible) < 2:
            return
        lit = self._assumption("night_balance")
        totals = {
            nurse.name: sum(self.val(nurse.name, day, ShiftType.N) for day in self.current_days)
            for nurse in eligible
        }
        for first in eligible:
            for second in eligible:
                if first.name == second.name:
                    continue
                self._enforce(
                    self.model.Add(totals[first.name] - totals[second.name] <= maximum_gap),
                    lit,
                )

    def _rule_night_dedicated(self):
        """나이트 전담(N만 가능한 본원 간호사): 월 N 개수를 개인 상한(max_n_hard)만큼 고정하고,
        나머지 날은 전부 오프(O). 연차는 쓰지 않는다.
        (예: N상한 16 & 31일 -> N 16개 + O 15개.)
        """
        lit = self._assumption("night_dedicated")
        for nurse in self.nurses:
            if not nurse.is_night_dedicated:
                continue
            total_n = sum(self.val(nurse.name, d, ShiftType.N) for d in self.current_days)
            self._enforce(self.model.Add(total_n == nurse.max_n_hard), lit)
            for day in self.current_days:
                self._enforce(self.model.Add(self.val(nurse.name, day, ShiftType.AL) == 0), lit)

    def _rule_staffing_range(self):
        """일별 인원 하드 범위: 하한 ≤ 인원 ≤ 상한.

        S는 데이(주간) 계열 보조 근무이므로 D 인원에만 포함하고 E에는 넣지 않는다.
        따라서 E 하한(예: 주말 2명)은 순수 이브닝 근무자 수로 충족해야 한다.
        상한(인원기준 maximum)으로 하루 근무 인원을 제한한다.
        """
        lit = self._assumption("staffing_range")
        for day in self.current_days:
            req = self.requirements[day]
            d_total = sum(self.val(n.name, day, ShiftType.D) for n in self.nurses)
            e_total = sum(self.val(n.name, day, ShiftType.E) for n in self.nurses)
            n_total = sum(self.val(n.name, day, ShiftType.N) for n in self.nurses)
            s_total = sum(self.val(n.name, day, ShiftType.S) for n in self.nurses)
            self._enforce(self.model.Add(d_total + s_total >= req.D.minimum), lit)
            self._enforce(self.model.Add(d_total + s_total <= req.D.maximum), lit)
            self._enforce(self.model.Add(e_total >= req.E.minimum), lit)
            self._enforce(self.model.Add(e_total <= req.E.maximum), lit)
            self._enforce(self.model.Add(n_total >= req.N.minimum), lit)
            self._enforce(self.model.Add(n_total <= req.N.maximum), lit)

    def _rule_charge_placement(self):
        # S는 차지 요건 대상에서 제외 (S 근무 시간대는 이미 D 또는 E 차지간호사가 있고,
        # S는 차지불가자만 배정 가능하므로 요건을 걸면 구조적으로 항상 모순).
        lit = self._assumption("charge_placement")
        for day in self.current_days:
            for shift in (ShiftType.D, ShiftType.E, ShiftType.N):
                all_vars = [self.val(n.name, day, shift) for n in self.nurses]
                charge_vars = [self.val(n.name, day, shift) for n in self.nurses if n.can_charge]
                has_any = self.model.NewBoolVar(f"has_any_{day.isoformat()}_{shift.value}")
                self.model.AddMaxEquality(has_any, all_vars)
                if charge_vars:
                    has_charge = self.model.NewBoolVar(f"has_charge_{day.isoformat()}_{shift.value}")
                    self.model.AddMaxEquality(has_charge, charge_vars)
                else:
                    has_charge = 0
                self._enforce(self.model.Add(has_charge >= has_any), lit)

    def _rule_charge_minimum(self):
        """각 근무(D/E/N)에 차지 가능 인력을 최소 N명 배치한다 (평일·주말·근무별 병동 설정).

        인원이 없는 근무(상한 0)에는 적용하지 않도록 근무 상한으로 캡을 씌운다.
        """
        lit = self._assumption("charge_minimum")
        for day in self.current_days:
            prefix = "weekend" if day.weekday() >= 5 else "weekday"
            req = self.requirements[day]
            caps = {ShiftType.D: req.D.maximum, ShiftType.E: req.E.maximum, ShiftType.N: req.N.maximum}
            for shift in (ShiftType.D, ShiftType.E, ShiftType.N):
                minimum = min(self.settings[f"{prefix}_charge_{shift.value}"], caps[shift])
                if minimum <= 0:
                    continue
                charge_n = sum(
                    self.val(n.name, day, shift) for n in self.nurses if n.can_charge
                )
                self._enforce(self.model.Add(charge_n >= minimum), lit)

    def _rule_senior_same_shift_cap(self, maximum: int = 2):
        """시니어(책임급) 데이 최대 2명. 이브닝은 소프트(_soft_senior_e_cap)."""
        lit = self._assumption("senior_same_shift_cap")
        seniors = [n for n in self.nurses if n.level == NurseLevel.SENIOR_CHARGE]
        if not seniors:
            return
        for day in self.current_days:
            senior_d = sum(self.val(n.name, day, ShiftType.D) for n in seniors)
            self._enforce(self.model.Add(senior_d <= maximum), lit)

    def _rule_s_eligibility(self):
        """S는 차지 불가능한 저연차 간호사만 배정 가능."""
        lit = self._assumption("s_eligibility")
        for nurse in self.nurses:
            if nurse.level in (NurseLevel.JUNIOR, NurseLevel.NEW_JUNIOR):
                continue
            for day in self.current_days:
                self._enforce(self.model.Add(self.val(nurse.name, day, ShiftType.S) == 0), lit)

    def _rule_s_enabled(self):
        """S 미사용 병동에서는 누구에게도 S를 배정하지 않는다."""
        if self.settings.get("use_s_shift", True):
            return
        lit = self._assumption("s_enabled")
        for nurse in self.nurses:
            for day in self.current_days:
                self._enforce(self.model.Add(self.val(nurse.name, day, ShiftType.S) == 0), lit)

    def _rule_weekday_only(self):
        """평일만 근무자는 주말 무조건 휴식 (2026-07-06 소프트→하드 승격)."""
        lit = self._assumption("weekday_only")
        for nurse in self.nurses:
            if not nurse.weekday_only:
                continue
            for day in self.current_days:
                if day.weekday() < 5:
                    continue
                self._enforce(self.model.Add(self.rest_val(nurse.name, day) == 1), lit)

    def _rule_al_target(self):
        lit = self._assumption("al_target")
        for nurse in self.nurses:
            if nurse.al_target is None:
                continue
            al_count = sum(self.val(nurse.name, d, ShiftType.AL) for d in self.current_days)
            self._enforce(self.model.Add(al_count == nurse.al_target), lit)

    def _rule_off_cap(self):
        """개인별 O 개수는 목표 오프일수와 정확히 일치해야 한다.

        헬퍼와 나이트 전담은 제외한다 — 헬퍼는 비근무일이 곧 빈칸(O)이고, 나이트 전담은
        나이트 외 날이 전부 오프라 목표 오프일수를 훨씬 넘기는 게 정상이다.
        (이 규칙은 병동과 무관하게 항상 적용된다.)
        """
        lit = self._assumption("off_cap")
        for nurse in self.nurses:
            if nurse.is_helper or nurse.is_night_dedicated:
                continue
            target = self.off_target.get(nurse.name, 0)
            o_count = sum(self.val(nurse.name, d, ShiftType.O) for d in self.current_days)
            # The monthly OFF target is a Tier 1 hard constraint.  Annual leave
            # is separate rest time and must never be used in place of an OFF.
            self._enforce(self.model.Add(o_count == target), lit)

    def apply_assumptions(self):
        """(진단 모드 전용) 모든 Tier1 카테고리를 True로 가정 (Infeasible 원인 진단용)."""
        if not self.use_assumptions:
            return
        lits = list(self.assumptions.values())
        if lits:
            self.model.AddAssumptions(lits)

    # ------------------------------------------------------------ Tier 2 --
    def add_tier2_soft_constraints(self, duty_requests: list[DutyRequest] | None = None):
        duty_requests = duty_requests or []
        extra_al_allowance = self._extra_al_allowance(duty_requests)
        self._soft_target_staffing()
        self._soft_avoid_isolated_night()
        self._soft_s_daily_cap()
        self._soft_senior_e_cap()
        self._soft_night_consecutive_preference()
        self._soft_avoid_night_after_night_off()
        self._soft_workday_streak()
        self._soft_off_streak()
        self._soft_weekend_off_pair()
        self._soft_avoid_isolated_workday()
        self._soft_excluded_shift_preference()
        self._soft_minimize_s_usage()
        self._soft_avoid_new_junior_overlap()
        self._soft_al_excess(extra_al_allowance)
        self._soft_al_balance()
        self._soft_trinity_a_pair_overlap()

    def _soft_target_staffing(self):
        """목표 인원은 최대한 맞추되, 하한~상한만 하드로 적용한다."""
        for day in self.current_days:
            req = self.requirements[day]
            weight = WEIGHT_TARGET_STAFFING * (
                MONDAY_TARGET_MULTIPLIER if day.weekday() == 0 else 1
            )
            d_total = sum(self.val(n.name, day, ShiftType.D) for n in self.nurses)
            e_total = sum(self.val(n.name, day, ShiftType.E) for n in self.nurses)
            n_total = sum(self.val(n.name, day, ShiftType.N) for n in self.nurses)
            s_total = sum(self.val(n.name, day, ShiftType.S) for n in self.nurses)
            for label, actual, target in (
                ("D", d_total + s_total, req.D.target),
                ("E", e_total, req.E.target),
                ("N", n_total, req.N.target),
            ):
                if target <= 0:
                    continue
                shortfall = self.model.NewIntVar(
                    0, target, f"target_shortfall_{day.isoformat()}_{label}"
                )
                self.model.Add(shortfall >= target - actual)
                self.penalties.append(("target_staffing_shortfall", weight, shortfall))

    def _soft_avoid_isolated_night(self):
        """나이트는 왠만하면 2~3일씩 붙여서 배정하고, 단독 1일짜리 나이트는 피한다."""
        for nurse in self.nurses:
            for day in self.current_days:
                next_day = day + timedelta(days=1)
                if (nurse.name, next_day) not in self.shift_vars:
                    continue  # 다음달로 넘어가는 경계라 판단 불가
                prev_day = day - timedelta(days=1)
                prev_n = self.val(nurse.name, prev_day, ShiftType.N)
                cur_n = self.val(nurse.name, day, ShiftType.N)
                next_n = self.val(nurse.name, next_day, ShiftType.N)
                isolated = self.model.NewIntVar(0, 1, f"n_isolated_{nurse.name}_{day.isoformat()}")
                self.model.Add(isolated >= cur_n - prev_n - next_n)
                self.penalties.append(("n_isolated_night", WEIGHT_N_ISOLATED, isolated))

    def _soft_s_daily_cap(self, max_per_day: int = 1):
        """하루 S는 최대 1명을 선호 (초과분에 벌점)."""
        for day in self.current_days:
            s_total = sum(self.val(n.name, day, ShiftType.S) for n in self.nurses)
            excess = self.model.NewIntVar(0, len(self.nurses), f"s_daily_excess_{day.isoformat()}")
            self.model.Add(excess >= s_total - max_per_day)
            self.penalties.append(("s_daily", WEIGHT_S_DAILY, excess))

    def _soft_senior_e_cap(self, maximum: int = 1):
        """시니어(책임급)가 같은 날 이브닝에 몰리지 않게 선호 (초과분에 벌점)."""
        seniors = [n for n in self.nurses if n.level == NurseLevel.SENIOR_CHARGE]
        if not seniors:
            return
        for day in self.current_days:
            senior_e = sum(self.val(n.name, day, ShiftType.E) for n in seniors)
            excess = self.model.NewIntVar(0, len(seniors), f"senior_e_excess_{day.isoformat()}")
            self.model.Add(excess >= senior_e - maximum)
            self.penalties.append(("senior_e", WEIGHT_SENIOR_E, excess))

    def _soft_night_consecutive_preference(self, window: int = 3):
        for nurse in self.nurses:
            if nurse.n_soft_consecutive_limit is None or nurse.n_soft_consecutive_limit >= 3:
                continue  # 하드 상한(3일)과 동일하므로 별도 벌점 불필요
            limit = nurse.n_soft_consecutive_limit
            for i in range(len(self.all_days) - window + 1):
                win = self.all_days[i : i + window]
                if not any((nurse.name, d) in self.shift_vars for d in win):
                    continue
                n_sum = sum(self.val(nurse.name, d, ShiftType.N) for d in win)
                viol = self.model.NewIntVar(0, window, f"n_soft_viol_{nurse.name}_{i}")
                self.model.Add(viol >= n_sum - limit)
                self.penalties.append(("night_soft_consecutive", WEIGHT_NIGHT_SOFT_CONSECUTIVE, viol))

    def _soft_avoid_night_after_night_off(self):
        """나이트 뒤 휴식이 끝난 첫 근무가 다시 N인 패턴을 피한다.

        N O...O N (O에는 연차 포함)에서 마지막 N은 휴식 뒤의 첫 근무이므로
        벌점을 준다. 나이트 블록 종료 뒤 2일 휴식은 Tier 1에서 이미 보장하며,
        이 규칙은 휴식이 더 길어지는 경우도 함께 다룬다.
        """
        for nurse in self.nurses:
            for start_index, start_day in enumerate(self.all_days[:-1]):
                before_night = self.val(nurse.name, start_day, ShiftType.N)
                for end_index in range(start_index + 2, len(self.all_days)):
                    end_day = self.all_days[end_index]
                    if (nurse.name, end_day) not in self.shift_vars:
                        continue
                    rest_days = self.all_days[start_index + 1 : end_index]
                    terms = [
                        before_night,
                        *(self.rest_val(nurse.name, day) for day in rest_days),
                        self.val(nurse.name, end_day, ShiftType.N),
                    ]
                    violation = self.model.NewBoolVar(
                        f"night_off_return_{nurse.name}_{start_day.isoformat()}_{end_day.isoformat()}"
                    )
                    self.model.Add(violation >= sum(terms) - (len(terms) - 1))
                    self.penalties.append(("night_off_return", WEIGHT_NIGHT_OFF_RETURN, violation))

    def _soft_workday_streak(self, window: int = 5):
        """연속 근무 5일 이상에 벌점 (기본 3~4일 선호). 6일 이상은 하드로 금지된다.

        5일 창에 휴식이 하나도 없으면(= 5일 연속 근무) 벌점 1. 4일 연속은 어떤 5일
        창에도 휴식이 1일 이상 있어 벌점이 없다.

        예외: ① 평일만 근무자는 주말이 강제 휴식이라 월~금 5연속이 자연스러워 제외.
        ② 5일 창에 나이트가 하나라도 있으면 벌점 면제 (나이트 포함 5연속은 허용).
        """
        for nurse in self.nurses:
            if nurse.weekday_only or nurse.is_helper:
                continue
            for i in range(len(self.all_days) - window + 1):
                win = self.all_days[i : i + window]
                if not any((nurse.name, d) in self.shift_vars for d in win):
                    continue
                rest_sum = sum(self.rest_val(nurse.name, d) for d in win)
                n_sum = sum(self.val(nurse.name, d, ShiftType.N) for d in win)
                viol = self.model.NewIntVar(0, 1, f"workday_streak_{nurse.name}_{i}")
                self.model.Add(viol >= 1 - rest_sum - n_sum)
                self.penalties.append(("workday_streak", WEIGHT_WORKDAY_STREAK, viol))

    def _soft_off_streak(self, window: int = 4):
        """오프(휴식)가 4일 이상 연속되면 벌점 (2~3일씩 분산 선호).

        4일 창에 휴식이 4일이면(= 4연속 오프) 벌점 1. 3일 연속 오프는 어떤 4일 창에도
        근무일이 1일 이상 있어 벌점이 없다. 휴식은 O/연차 모두 포함.
        """
        for nurse in self.nurses:
            if nurse.is_helper:
                continue
            for i in range(len(self.all_days) - window + 1):
                win = self.all_days[i : i + window]
                if not any((nurse.name, d) in self.shift_vars for d in win):
                    continue
                rest_sum = sum(self.rest_val(nurse.name, d) for d in win)
                viol = self.model.NewIntVar(0, 1, f"off_streak_{nurse.name}_{i}")
                self.model.Add(viol >= rest_sum - (window - 1))
                self.penalties.append(("off_streak", WEIGHT_OFF_STREAK, viol))

    def _soft_weekend_off_pair(self):
        """토·일 통주말 오프를 월 최소 1회(강)·2회(약) 갖도록 유도한다.

        각 토-일 쌍에 대해 ① 금요일이 나이트가 아니고(금 N이면 토 아침 퇴근이라
        온전한 휴식이 아님) ② 토·일 둘 다 휴식(O/연차)이면 통주말 오프 1회로 센다.
        월 합계가 1에 못 미치면 강한 벌점, 2에 못 미치면 약한 벌점.
        평일만 근무자는 주말이 늘 휴식이라 제외한다.
        """
        day_set = set(self.current_days)
        pairs = [
            (sat, sat + timedelta(days=1))
            for sat in self.current_days
            if sat.weekday() == 5 and (sat + timedelta(days=1)) in day_set
        ]
        if not pairs:
            return
        for nurse in self.nurses:
            if nurse.weekday_only or nurse.is_helper:
                continue
            both_vars = []
            for sat, sun in pairs:
                both = self.model.NewBoolVar(f"wkoff_{nurse.name}_{sat.isoformat()}")
                self.model.Add(both <= self.rest_val(nurse.name, sat))
                self.model.Add(both <= self.rest_val(nurse.name, sun))
                # 금요일 나이트면 토요일 아침 퇴근 — 통주말 오프로 인정하지 않는다.
                n_fri = self.val(nurse.name, sat - timedelta(days=1), ShiftType.N)
                self.model.Add(both <= 1 - n_fri)
                both_vars.append(both)
            count = sum(both_vars)
            short_min = self.model.NewIntVar(0, 1, f"wkoff_min_{nurse.name}")
            self.model.Add(short_min >= 1 - count)
            self.penalties.append(("weekend_off_min", WEIGHT_WEEKEND_OFF_MIN, short_min))
            short_pref = self.model.NewIntVar(0, 2, f"wkoff_pref_{nurse.name}")
            self.model.Add(short_pref >= 2 - count)
            self.penalties.append(("weekend_off_pref", WEIGHT_WEEKEND_OFF_PREF, short_pref))

    def _soft_avoid_isolated_workday(self):
        """Rest-work-rest patterns are allowed, but discouraged."""
        for nurse in self.nurses:
            if nurse.is_helper:
                continue
            for day in self.current_days:
                next_day = day + timedelta(days=1)
                if (nurse.name, next_day) not in self.shift_vars:
                    continue
                prev_rest = self.rest_val(nurse.name, day - timedelta(days=1))
                cur_work = 1 - self.rest_val(nurse.name, day)
                next_rest = self.rest_val(nurse.name, next_day)
                isolated = self.model.NewIntVar(
                    0, 1, f"isolated_workday_{nurse.name}_{day.isoformat()}"
                )
                self.model.Add(isolated >= prev_rest + cur_work + next_rest - 2)
                self.penalties.append(("isolated_workday", WEIGHT_ISOLATED_WORKDAY, isolated))

    def _soft_excluded_shift_preference(self):
        for nurse in self.nurses:
            for shift in nurse.excluded_shifts:
                if shift in (ShiftType.O, ShiftType.AL):
                    continue
                for day in self.current_days:
                    self.penalties.append(
                        ("excluded_shift", WEIGHT_EXCLUDED_SHIFT, self.val(nurse.name, day, shift))
                    )

    def _soft_minimize_s_usage(self):
        """S는 D/E 인원을 못 채울 때 쓰는 보조 근무이므로 사용 자체에 가벼운 벌점을 둔다.
        단 잉여 흡수 시에는 overstaffing(D/E 초과) 벌점이 더 커서 S가 선택된다."""
        for nurse in self.nurses:
            for day in self.current_days:
                self.penalties.append(("s_usage", WEIGHT_S_USAGE, self.val(nurse.name, day, ShiftType.S)))

    def _soft_avoid_new_junior_overlap(self):
        new_juniors = [n for n in self.nurses if n.is_new_junior]
        if len(new_juniors) < 2:
            return
        for day in self.current_days:
            new_junior_working = sum(
                self.val(n.name, day, s)
                for n in new_juniors
                for s in (ShiftType.D, ShiftType.E, ShiftType.N, ShiftType.S)
            )
            overlap = self.model.NewIntVar(
                0, len(new_juniors), f"new_junior_overlap_{day.isoformat()}"
            )
            self.model.Add(overlap >= new_junior_working - 1)
            self.penalties.append(("new_junior_overlap", WEIGHT_NEW_JUNIOR_OVERLAP, overlap))

    def _soft_al_excess(self, extra_allowance: dict[str, int] | None = None):
        """연차는 1인당 월 1개 가이드라인 — 초과분에 가벼운 벌점 (고르게 분배 유도)."""
        for nurse in self.nurses:
            al_count = sum(self.val(nurse.name, d, ShiftType.AL) for d in self.current_days)
            excess = self.model.NewIntVar(0, len(self.current_days), f"al_excess_{nurse.name}")
            self.model.Add(excess >= al_count - (1 + (extra_allowance or {}).get(nurse.name, 0)))
            self.penalties.append(("al_excess", WEIGHT_AL_EXCESS, excess))

    def _soft_al_balance(self):
        """연차를 되도록 균등하게 — 개인 최대 연차 개수를 최소화한다.

        연차가 한두 사람에게 몰리지 않도록, 가장 많이 쓴 사람의 연차 개수(max)에
        벌점을 걸어 전체를 평평하게 만든다. al_target(강제 연차)이 있는 사람은 제외.
        """
        free = [n for n in self.nurses if n.al_target is None and not n.is_helper]
        if len(free) < 2:
            return
        max_al = self.model.NewIntVar(0, len(self.current_days), "al_max")
        for nurse in free:
            al_count = sum(self.val(nurse.name, d, ShiftType.AL) for d in self.current_days)
            self.model.Add(max_al >= al_count)
        self.penalties.append(("al_balance", WEIGHT_AL_BALANCE, max_al))

    def _soft_trinity_a_pair_overlap(self):
        """Prefer a distributed shared-duty pattern for the Trinity A pair."""
        if not self.settings.get("trinity_a_pair_overlap"):
            return
        first_name, second_name = "우창희", "정해주"
        nurse_names = {nurse.name for nurse in self.nurses}
        if first_name not in nurse_names or second_name not in nurse_names:
            return

        shared_days = []
        working_shifts = (ShiftType.D, ShiftType.E, ShiftType.N, ShiftType.S)
        for day in self.current_days:
            first_work = self.model.NewBoolVar(f"trinity_a_first_work_{day.isoformat()}")
            second_work = self.model.NewBoolVar(f"trinity_a_second_work_{day.isoformat()}")
            self.model.AddMaxEquality(
                first_work,
                [self.val(first_name, day, shift) for shift in working_shifts],
            )
            self.model.AddMaxEquality(
                second_work,
                [self.val(second_name, day, shift) for shift in working_shifts],
            )
            shared = self.model.NewBoolVar(f"trinity_a_shared_{day.isoformat()}")
            self.model.AddBoolAnd([first_work, second_work]).OnlyEnforceIf(shared)
            self.model.AddBoolOr([first_work.Not(), second_work.Not(), shared])
            shared_days.append((day, shared))

        overlap_count = sum(shared for _, shared in shared_days)
        shortfall = self.model.NewIntVar(0, 8, "trinity_a_pair_shortfall")
        self.model.Add(shortfall >= 8 - overlap_count)
        self.penalties.append(("trinity_a_pair_shortfall", WEIGHT_TRINITY_A_PAIR_SHORTFALL, shortfall))

        midpoint = len(self.current_days) // 2
        early_count = sum(shared for _, shared in shared_days[:midpoint])
        late_count = sum(shared for _, shared in shared_days[midpoint:])
        early_excess = self.model.NewIntVar(0, len(self.current_days), "trinity_a_pair_early_excess")
        late_shortfall = self.model.NewIntVar(0, 4, "trinity_a_pair_late_shortfall")
        self.model.Add(early_excess >= early_count - 4)
        self.model.Add(late_shortfall >= 4 - late_count)
        self.penalties.append(("trinity_a_pair_early_excess", WEIGHT_TRINITY_A_PAIR_CONCENTRATION, early_excess))
        self.penalties.append(("trinity_a_pair_late_shortfall", WEIGHT_TRINITY_A_PAIR_CONCENTRATION, late_shortfall))

    # ------------------------------------------------------------ Tier 3 --
    @staticmethod
    def _extra_al_allowance(duty_requests: list[DutyRequest]) -> dict[str, int]:
        allowance: dict[str, int] = {}
        for req in duty_requests:
            if getattr(req, "kind", "prefer") == "prefer" and req.requested_shift in (ShiftType.O, ShiftType.AL):
                allowance[req.nurse_name] = allowance.get(req.nurse_name, 0) + req.priority
        return allowance

    def add_duty_requests(self, duty_requests: list[DutyRequest]):
        for req in duty_requests:
            if getattr(req, "decision", "force") == "ignore":
                continue
            if (req.nurse_name, req.day) not in self.shift_vars:
                continue
            if req.requested_shift in (ShiftType.O, ShiftType.AL):
                satisfied = self.rest_val(req.nurse_name, req.day)
            else:
                satisfied = self.val(req.nurse_name, req.day, req.requested_shift)
            if getattr(req, "decision", "force") == "force":
                if getattr(req, "kind", "prefer") == "avoid":
                    self.model.Add(satisfied == 0)
                else:
                    self.model.Add(satisfied == 1)
                continue
            violation = self.model.NewBoolVar(
                f"duty_request_violation_{req.nurse_name}_{req.day.isoformat()}"
            )
            if getattr(req, "kind", "prefer") == "avoid":
                self.model.Add(violation == satisfied)
            else:
                self.model.Add(violation == 1 - satisfied)
            self.penalties.append(("duty_request", WEIGHT_DUTY_REQUEST * req.priority, violation))

    def add_tier3_exceptions(self, exceptions: list[ExceptionRequest]):
        for exc in exceptions:
            if (exc.nurse_name, exc.day) not in self.shift_vars:
                continue
            satisfied = self.val(exc.nurse_name, exc.day, exc.forced_shift)
            violation = self.model.NewBoolVar(
                f"exc_violation_{exc.nurse_name}_{exc.day.isoformat()}"
            )
            self.model.Add(violation == 1 - satisfied)
            self.penalties.append(("exception_request", WEIGHT_TIER3_EXCEPTION, violation))

    # -------------------------------------------------------------- misc --
    def objective_terms(self):
        return [weight * var for _, weight, var in self.penalties]
