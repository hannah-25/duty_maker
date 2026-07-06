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
# O는 목표 오프일수까지의 정규 휴무, AL은 그 초과분(오프 상한 하드에 막힌 잉여 휴식).
MODEL_SHIFTS = (ShiftType.D, ShiftType.E, ShiftType.N, ShiftType.S, ShiftType.O, ShiftType.AL)

# 소프트 벌점 가중치 (상대적 우선순위가 중요)
WEIGHT_TIER3_EXCEPTION = 1000
WEIGHT_DUTY_REQUEST = 750
WEIGHT_OFF_SHORTFALL = 500  # O가 목표 미달 (실행불가 회피용 최후수단)
WEIGHT_TARGET_STAFFING = 30  # 목표인원(D4/E3) 미달, 1명당
MONDAY_TARGET_MULTIPLIER = 3  # 월요일 목표 미달 가중 (최우선)
WEIGHT_N_ISOLATED = 35
WEIGHT_NIGHT_SOFT_CONSECUTIVE = 25
WEIGHT_ISOLATED_WORKDAY = 20
WEIGHT_EXCLUDED_SHIFT = 20
WEIGHT_S_USAGE = 15
WEIGHT_NEW_JUNIOR_OVERLAP = 12
WEIGHT_AL_EXCESS = 10  # 연차 1인 1개 초과분

# 나이트 가능 인원의 월 N 개수 하드 범위 (병동 기본값)
N_MONTHLY_RANGE_DEFAULT = (6, 8)


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
        n_monthly_range: tuple[int, int] = N_MONTHLY_RANGE_DEFAULT,
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
        self.n_monthly_range = n_monthly_range
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
        self._rule_e_rest_d_forbidden()
        self._rule_max_consecutive_workdays()
        self._rule_max_consecutive_nights()
        self._rule_allowed_shifts()
        self._rule_n_monthly_range()
        self._rule_staffing_range()
        self._rule_charge_placement()
        self._rule_weekday_charge_minimum()
        self._rule_senior_same_shift_cap()
        self._rule_s_eligibility()
        self._rule_s_daily_cap()
        self._rule_weekday_only()
        self._rule_off_cap()

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

    def _rule_e_rest_d_forbidden(self):
        """E → 휴식 1일 → D/S 금지 (하루만 쉬고 데이 출근 불가. 이틀 이상 쉬면 허용).

        선형화: E[d] + 휴식[d+1] + D[d+2] ≤ 2 (셋 다 참이면 위반).
        휴식은 O/연차 모두 포함. 값이 과거 상수여도 동일 부등식이 성립한다.
        """
        lit = self._assumption("e_rest_d")
        for nurse in self.nurses:
            for day in self.all_days:
                e_val = self.val(nurse.name, day, ShiftType.E)
                if isinstance(e_val, int) and e_val == 0:
                    continue
                day2 = day + timedelta(days=2)
                if (nurse.name, day2) not in self.shift_vars:
                    continue
                rest_mid = self.rest_val(nurse.name, day + timedelta(days=1))
                if isinstance(rest_mid, int) and rest_mid == 0:
                    continue
                d_next2 = self.val(nurse.name, day2, ShiftType.D)
                s_next2 = self.val(nurse.name, day2, ShiftType.S)
                self._enforce(self.model.Add(e_val + rest_mid + d_next2 <= 2), lit)
                self._enforce(self.model.Add(e_val + rest_mid + s_next2 <= 2), lit)

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
        """월 N 개수 범위 규칙의 적용 대상인지 (나이트 가능 인원)."""
        return ShiftType.N in (nurse.allowed_shifts or set()) and nurse.max_n_hard > 0

    def _rule_n_monthly_range(self):
        """나이트 가능 인원은 월 N 개수가 병동 기본범위(6~8) 안이어야 함.

        개인별 상한(max_n_hard)이 더 낮으면 그 값이 상한이 되고, 하한도 그에 맞춰 내려간다.
        완벽한 균등 분배는 요구하지 않는다 (범위 안이기만 하면 됨).
        """
        lit = self._assumption("n_monthly_range")
        lo, hi = self.n_monthly_range
        for nurse in self.nurses:
            if not self._n_eligible(nurse):
                continue
            upper = min(hi, nurse.max_n_hard)
            lower = min(lo, upper)
            total_n = sum(self.val(nurse.name, d, ShiftType.N) for d in self.current_days)
            self._enforce(self.model.Add(total_n >= lower), lit)
            self._enforce(self.model.Add(total_n <= upper), lit)

    def _rule_staffing_range(self):
        """일별 인원 하드 범위: 하한 ≤ D+S/E+S ≤ 상한, N은 하한=상한이면 정확히 고정.

        상한이 핵심: 하한만 두면 잉여 인력이 벌점 사각지대(월말 등)에 덤핑되어
        N 4~6명인 날이 생기는 문제가 실측으로 확인됨.
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
            self._enforce(self.model.Add(e_total + s_total >= req.E.minimum), lit)
            self._enforce(self.model.Add(e_total + s_total <= req.E.maximum), lit)
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

    def _rule_weekday_charge_minimum(self, minimum: int = 2):
        lit = self._assumption("weekday_charge_minimum")
        for day in self.current_days:
            charge_d = sum(
                self.val(n.name, day, ShiftType.D)
                for n in self.nurses
                if n.can_charge
            )
            self._enforce(self.model.Add(charge_d >= minimum), lit)

    def _rule_senior_same_shift_cap(self, maximum: int = 2):
        lit = self._assumption("senior_same_shift_cap")
        seniors = [n for n in self.nurses if n.level == NurseLevel.SENIOR_CHARGE]
        if not seniors:
            return
        for day in self.current_days:
            for shift in (ShiftType.D, ShiftType.E):
                senior_count = sum(self.val(n.name, day, shift) for n in seniors)
                self._enforce(self.model.Add(senior_count <= maximum), lit)
            senior_n = sum(self.val(n.name, day, ShiftType.N) for n in seniors)
            self._enforce(self.model.Add(senior_n == 1), lit)

    def _rule_s_eligibility(self):
        """S는 차지 불가능한 저연차 간호사만 배정 가능."""
        lit = self._assumption("s_eligibility")
        for nurse in self.nurses:
            if nurse.level in (NurseLevel.JUNIOR, NurseLevel.NEW_JUNIOR):
                continue
            for day in self.current_days:
                self._enforce(self.model.Add(self.val(nurse.name, day, ShiftType.S) == 0), lit)

    def _rule_s_daily_cap(self, max_per_day: int = 1):
        """하루에 S는 최대 1명만 배정."""
        lit = self._assumption("s_daily_cap")
        for day in self.current_days:
            s_total = sum(self.val(n.name, day, ShiftType.S) for n in self.nurses)
            self._enforce(self.model.Add(s_total <= max_per_day), lit)

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

    def _rule_off_cap(self):
        """개인별 O 개수는 목표 오프일수를 초과 불가 — 초과 휴식은 연차(AL)로만."""
        lit = self._assumption("off_cap")
        for nurse in self.nurses:
            target = self.off_target.get(nurse.name, 0)
            o_count = sum(self.val(nurse.name, d, ShiftType.O) for d in self.current_days)
            self._enforce(self.model.Add(o_count <= target), lit)

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
        self._soft_off_shortfall()
        self._soft_target_staffing()
        self._soft_avoid_isolated_night()
        self._soft_night_consecutive_preference()
        self._soft_avoid_isolated_workday()
        self._soft_excluded_shift_preference()
        self._soft_minimize_s_usage()
        self._soft_avoid_new_junior_overlap()
        self._soft_al_excess(extra_al_allowance)

    def _soft_off_shortfall(self):
        """O가 목표 오프일수에 못 미치면 매우 무거운 벌점 (실행불가 회피용 최후수단)."""
        for nurse in self.nurses:
            target = self.off_target.get(nurse.name, 0)
            o_count = sum(self.val(nurse.name, d, ShiftType.O) for d in self.current_days)
            shortfall = self.model.NewIntVar(0, len(self.current_days), f"off_shortfall_{nurse.name}")
            self.model.Add(shortfall >= target - o_count)
            self.penalties.append(("off_shortfall", WEIGHT_OFF_SHORTFALL, shortfall))

    def _soft_target_staffing(self):
        """매일(주말 포함) 목표인원(D4/E3) 달성 유도. 월요일 가중치 최상."""
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
                ("E", e_total + s_total, req.E.target),
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

    def _soft_avoid_isolated_workday(self):
        """Rest-work-rest patterns are allowed, but discouraged."""
        for nurse in self.nurses:
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
        """S는 D/E 인원을 못 채울 때만 쓰는 보조 근무이므로, 사용 자체에 벌점을 두어
        가능하면 D/E만으로 채우도록 유도한다."""
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

    # ------------------------------------------------------------ Tier 3 --
    @staticmethod
    def _extra_al_allowance(duty_requests: list[DutyRequest]) -> dict[str, int]:
        allowance: dict[str, int] = {}
        for req in duty_requests:
            if req.requested_shift in (ShiftType.O, ShiftType.AL):
                allowance[req.nurse_name] = allowance.get(req.nurse_name, 0) + req.priority
        return allowance

    def add_duty_requests(self, duty_requests: list[DutyRequest]):
        for req in duty_requests:
            if (req.nurse_name, req.day) not in self.shift_vars:
                continue
            if req.requested_shift in (ShiftType.O, ShiftType.AL):
                satisfied = self.rest_val(req.nurse_name, req.day)
            else:
                satisfied = self.val(req.nurse_name, req.day, req.requested_shift)
            violation = self.model.NewBoolVar(
                f"duty_request_violation_{req.nurse_name}_{req.day.isoformat()}"
            )
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
