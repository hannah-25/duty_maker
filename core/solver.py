from __future__ import annotations

from datetime import date
from time import monotonic
from typing import Optional

from ortools.sat.python import cp_model

from core.constraints import (
    DEFAULT_WARD_SETTINGS,
    RELAXATION_CATEGORIES,
    RELAXATION_FOUR_CONSECUTIVE_N,
    RELAXATION_N_AFTER_ONE_OFF,
    RELAXATION_NOD,
    RELAXATION_OFF_CAP,
    RELAXATION_WEEKDAY_WEEKEND,
    ScheduleModel,
)
from core.models import (
    DayRequirement,
    DutyRequest,
    ExceptionRequest,
    Nurse,
    ScheduleResult,
    ShiftType,
    lookback_dates,
    month_dates,
)


def generate_schedule(
    nurses: list[Nurse],
    year: int,
    month: int,
    requirements: dict[date, DayRequirement],
    off_target: dict[str, int],
    history: Optional[dict[tuple[str, date], ShiftType]] = None,
    exceptions: Optional[list[ExceptionRequest]] = None,
    duty_requests: Optional[list[DutyRequest]] = None,
    time_limit_seconds: float = 30.0,
    settings: dict | None = None,
    fixed_assignments: Optional[dict[tuple[str, date], ShiftType]] = None,
    require_change_from: Optional[dict[tuple[str, date], ShiftType]] = None,
    relaxed_off_cap_nurses: frozenset[str] | None = None,
    relaxed_n_then_1off_nurses: frozenset[str] | None = None,
    relaxed_nod_nurses: frozenset[str] | None = None,
    relaxed_four_consecutive_n_nurses: frozenset[str] | None = None,
    relaxed_weekday_weekend_nurses: frozenset[str] | None = None,
    n_rest_days: int = 2,
) -> ScheduleResult:
    """한 달치 근무표를 생성한다.

    history: (간호사이름, 날짜) -> ShiftType. 이전 달 마지막 5일 이력 (없으면 O로 간주).
    off_target: 간호사이름 -> 이번달 목표 오프일수 (주말 + 병동 공휴일 수).
    settings: 병동별 제약 설정 (DEFAULT_WARD_SETTINGS 참고).
    relaxed_*_nurses / n_rest_days: 생성이 infeasible일 때 관리자가 이번 한 번만
        고른 완화 옵션 (기본값 = 기존 하드 제약 그대로). 진단·워밍스타트 모델에는 적용하지
        않는다 — 완화가 부족했을 때도 다음 진단이 전체 하드 규칙 기준으로 정확해야 한다.

    월 나이트 개수는 명단의 개인 N상한(max_n_hard)으로만 제한된다(하한 없음).
    하루 근무 인원은 인원기준 상한(staffing_range)으로 제한된다.
    """
    merged_settings = {
        **DEFAULT_WARD_SETTINGS,
        **{k: v for k, v in (settings or {}).items() if v is not None},
    }
    current_days = month_dates(year, month)
    lb_days = lookback_dates(year, month, n=5)
    history = history or {}
    exceptions = exceptions or []
    duty_requests = duty_requests or []
    active_duty_requests = [
        req for req in duty_requests if getattr(req, "decision", "force") != "ignore"
    ]

    # 1차: assumption 없이 전부 무조건 하드로 적용 (presolve 완전 동작, 훨씬 빠르고 좋은 해).
    sm = ScheduleModel(
        nurses, current_days, lb_days, history, requirements, off_target,
        use_assumptions=False, settings=merged_settings,
        relaxed_off_cap_nurses=relaxed_off_cap_nurses or frozenset(),
        relaxed_n_then_1off_nurses=relaxed_n_then_1off_nurses or frozenset(),
        relaxed_nod_nurses=relaxed_nod_nurses or frozenset(),
        relaxed_four_consecutive_n_nurses=relaxed_four_consecutive_n_nurses or frozenset(),
        relaxed_weekday_weekend_nurses=relaxed_weekday_weekend_nurses or frozenset(),
        n_rest_days=n_rest_days,
    )
    sm.add_tier1_hard_constraints()
    sm.add_fixed_assignments(fixed_assignments or {}, require_change_from=require_change_from)
    sm.add_tier2_soft_constraints(active_duty_requests)
    sm.add_duty_requests(active_duty_requests)
    sm.add_tier3_exceptions(exceptions)

    if not _apply_feasible_assignment_hint(
        sm,
        nurses,
        current_days,
        lb_days,
        history,
        requirements,
        off_target,
        merged_settings,
        active_duty_requests,
        fixed_assignments or {},
        require_change_from,
        time_limit_seconds,
    ):
        _apply_n_cluster_hint(sm, nurses, current_days, requirements)

    # 일회성 완화는 "큰 가중치" 하나에 의존하지 않고, 각 단계를 잠근 뒤 다음
    # 목표를 푼다. 오프 감소 → N-O-D → 그 밖의 완화 → 기존 품질 순서가 보장된다.
    deadline = monotonic() + time_limit_seconds
    stages = (
        frozenset({RELAXATION_OFF_CAP}),
        frozenset({RELAXATION_NOD}),
        frozenset({
            RELAXATION_N_AFTER_ONE_OFF,
            RELAXATION_FOUR_CONSECUTIVE_N,
            RELAXATION_WEEKDAY_WEEKEND,
        }),
    )
    solver: cp_model.CpSolver | None = None
    status: int | None = None
    for categories in stages:
        terms = sm.relaxation_terms(categories)
        if not terms:
            continue
        expression = sum(terms)
        solver, status = _solve_objective(sm, expression, deadline)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            break
        # OPTIMAL이면 해당 단계의 최솟값을, 시간 제한으로 FEASIBLE이면 현재까지
        # 발견한 최선의 상한을 고정한다. 어느 경우에도 이후 단계가 앞선 완화를
        # 더 많이 쓰지는 못한다.
        sm.model.Add(expression <= solver.Value(expression))

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) or status is None:
        solver, status = _solve_objective(
            sm, sum(sm.objective_terms(include_relaxations=False)), deadline
        )

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # 2차: 정말 Infeasible인 경우에만, 원인 진단을 위해 assumption 모드로 재구성해서 재시도.
        # (assumption을 쓰면 presolve가 제한돼 매번 쓰기엔 느리므로 이 경로에서만 사용)
        diag_sm = ScheduleModel(
            nurses, current_days, lb_days, history, requirements, off_target,
            use_assumptions=True, settings=merged_settings,
        )
        diag_sm.add_tier1_hard_constraints()
        diag_sm.add_fixed_assignments(
            fixed_assignments or {}, require_change_from=require_change_from
        )
        # 강제(force) 듀티 신청도 하드 제약이라, 그게 원인일 수 있다는 걸 진단에 포함한다.
        diag_sm.add_duty_requests(active_duty_requests)
        diag_sm.apply_assumptions()
        diag_solver = cp_model.CpSolver()
        diag_solver.parameters.max_time_in_seconds = min(time_limit_seconds, 30.0)
        diag_status = diag_solver.Solve(diag_sm.model)
        if diag_status == cp_model.INFEASIBLE:
            return ScheduleResult(
                feasible=False,
                infeasible_categories=_diagnose_infeasibility(diag_solver, diag_sm),
            )
        return ScheduleResult(feasible=False, infeasible_categories=[f"solver_status_{status}"])

    assignments = _extract_assignments(solver, sm, nurses, current_days)
    soft_violations = _summarize_soft_violations(solver, sm)
    relaxation_actual_nurses, relaxation_cells = _extract_relaxation_events(solver, sm)
    honored_duty_requests, dropped_duty_requests = _split_duty_requests(
        assignments, active_duty_requests
    )

    return ScheduleResult(
        feasible=True,
        assignments=assignments,
        soft_violations=soft_violations,
        dropped_duty_requests=dropped_duty_requests,
        honored_duty_requests=honored_duty_requests,
        objective_value=solver.ObjectiveValue(),
        relaxations={
            "off_cap": sorted(relaxed_off_cap_nurses or ()),
            "n_then_1off": sorted(relaxed_n_then_1off_nurses or ()),
            "nod": sorted(relaxed_nod_nurses or ()),
            "four_consecutive_n": sorted(relaxed_four_consecutive_n_nurses or ()),
            "weekday_weekend": sorted(relaxed_weekday_weekend_nurses or ()),
        },
        relaxation_usage={
            category: amount
            for category, amount in soft_violations.items()
            if category in RELAXATION_CATEGORIES and amount
        },
        relaxation_actual_nurses=relaxation_actual_nurses,
        relaxation_cells=relaxation_cells,
    )


def _solve_objective(
    sm: ScheduleModel, expression, deadline: float
) -> tuple[cp_model.CpSolver, int]:
    """Solve the current model with one lexicographic objective stage."""
    sm.model.Minimize(expression)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.1, deadline - monotonic())
    solver.parameters.num_search_workers = 8
    return solver, solver.Solve(sm.model)


def _build_n_cluster_hint(
    nurses: list[Nurse], current_days: list[date], requirements: dict[date, DayRequirement]
) -> dict[tuple[str, date], int]:
    """N을 2~3일 블록으로 몰아주는 그리디 초안을 만들어 솔버 워밍스타트 힌트로 제공한다.

    간호사 배치는 서로 바꿔치기 가능한 대칭성이 커서 기본 탐색이 고립된 나이트를
    잘 피하지 못하는 문제가 있어, 완벽하지 않아도 "몰아주는 방향"의 초기해를 던져줘서
    솔버가 그 방향으로 개선해나가도록 유도한다.
    """
    eligible = [n for n in nurses if ShiftType.N in (n.allowed_shifts or set()) and n.max_n_hard > 0]
    n_count = {n.name: 0 for n in eligible}
    block_len = {n.name: 0 for n in eligible}
    rest_remaining = {n.name: 0 for n in eligible}
    max_block = {n.name: (2 if n.n_soft_consecutive_limit == 2 else 3) for n in eligible}
    prev_working: set[str] = set()
    hint: dict[tuple[str, date], int] = {}

    for day in current_days:
        for nurse in eligible:
            if nurse.name not in prev_working and rest_remaining[nurse.name] > 0:
                rest_remaining[nurse.name] -= 1

        need = requirements[day].N.minimum
        chosen: list[Nurse] = []
        for nurse in eligible:
            if len(chosen) >= need:
                break
            if nurse.name in prev_working and block_len[nurse.name] < max_block[nurse.name]:
                chosen.append(nurse)
        remaining = sorted(
            (n for n in eligible if n not in chosen and rest_remaining[n.name] <= 0),
            key=lambda n: n_count[n.name],
        )
        for nurse in remaining:
            if len(chosen) >= need:
                break
            chosen.append(nurse)

        chosen_names = {n.name for n in chosen}
        for nurse in eligible:
            if nurse.name in chosen_names:
                hint[(nurse.name, day)] = 1
                n_count[nurse.name] += 1
                block_len[nurse.name] = block_len[nurse.name] + 1 if nurse.name in prev_working else 1
            else:
                hint[(nurse.name, day)] = 0
                if nurse.name in prev_working and block_len[nurse.name] > 0:
                    rest_remaining[nurse.name] = 2
                block_len[nurse.name] = 0
        prev_working = chosen_names

    return hint


def _apply_n_cluster_hint(
    sm: ScheduleModel, nurses: list[Nurse], current_days: list[date], requirements: dict[date, DayRequirement]
):
    hint = _build_n_cluster_hint(nurses, current_days, requirements)
    for (nurse_name, day), val in hint.items():
        var = sm.shift_vars[(nurse_name, day)][ShiftType.N]
        sm.model.AddHint(var, val)


def _apply_feasible_assignment_hint(
    sm: ScheduleModel,
    nurses: list[Nurse],
    current_days: list[date],
    lookback_days: list[date],
    history: dict[tuple[str, date], ShiftType],
    requirements: dict[date, DayRequirement],
    off_target: dict[str, int],
    settings: dict,
    duty_requests: list[DutyRequest],
    fixed_assignments: dict[tuple[str, date], ShiftType],
    require_change_from: dict[tuple[str, date], ShiftType] | None,
    time_limit_seconds: float,
) -> bool:
    """Seed optimization with a quickly found solution of the hard rules.

    Exact staffing targets shrink the feasible region considerably.  A complete
    hard-feasible hint prevents CP-SAT from spending the whole optimization
    budget before it finds any valid roster.
    """
    hard_sm = ScheduleModel(
        nurses,
        current_days,
        lookback_days,
        history,
        requirements,
        off_target,
        use_assumptions=False,
        settings=settings,
    )
    hard_sm.add_tier1_hard_constraints()
    hard_sm.add_fixed_assignments(
        fixed_assignments, require_change_from=require_change_from
    )
    hard_sm.add_duty_requests(duty_requests)

    hard_solver = cp_model.CpSolver()
    hard_solver.parameters.max_time_in_seconds = min(10.0, max(1.0, time_limit_seconds))
    hard_solver.parameters.num_search_workers = 8
    status = hard_solver.Solve(hard_sm.model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return False

    for nurse in nurses:
        for day in current_days:
            for shift, hard_var in hard_sm.shift_vars[(nurse.name, day)].items():
                sm.model.AddHint(
                    sm.shift_vars[(nurse.name, day)][shift], hard_solver.Value(hard_var)
                )
    return True


def _diagnose_infeasibility(solver: cp_model.CpSolver, sm: ScheduleModel) -> list[str]:
    try:
        culprit_indices = set(solver.SufficientAssumptionsForInfeasibility())
    except Exception:
        return ["unknown (원인 진단 실패)"]
    index_to_name = {var.Index(): name for name, var in sm.assumptions.items()}
    categories = [index_to_name.get(idx, str(idx)) for idx in culprit_indices]
    return categories or ["unknown (원인 진단 실패)"]


def _extract_assignments(solver, sm: ScheduleModel, nurses, current_days):
    assignments: dict[tuple[str, date], ShiftType] = {}
    for nurse in nurses:
        for day in current_days:
            vs = sm.shift_vars[(nurse.name, day)]
            for shift, var in vs.items():
                if solver.Value(var) == 1:
                    assignments[(nurse.name, day)] = shift
                    break
    return assignments


def _split_duty_requests(
    assignments: dict[tuple[str, date], ShiftType],
    duty_requests: list[DutyRequest],
) -> tuple[list[DutyRequest], list[DutyRequest]]:
    honored: list[DutyRequest] = []
    dropped: list[DutyRequest] = []
    for req in duty_requests:
        assigned = assignments.get((req.nurse_name, req.day))
        if req.requested_shift in (ShiftType.O, ShiftType.AL):
            has_shift = assigned in (ShiftType.O, ShiftType.AL)
        else:
            has_shift = assigned == req.requested_shift
        matched = not has_shift if getattr(req, "kind", "prefer") == "avoid" else has_shift
        (honored if matched else dropped).append(req)
    return honored, dropped


def _summarize_soft_violations(solver, sm: ScheduleModel) -> dict[str, float]:
    summary: dict[str, float] = {}
    for category, _weight, var in sm.penalties:
        value = var if isinstance(var, int) else solver.Value(var)
        summary[category] = summary.get(category, 0) + value
    return summary


def _extract_relaxation_events(
    solver, sm: ScheduleModel
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    nurses: dict[str, set[str]] = {}
    cells: dict[str, set[str]] = {}
    for category, nurse_name, day, var in sm.relaxation_events:
        value = var if isinstance(var, int) else solver.Value(var)
        if value <= 0:
            continue
        nurses.setdefault(category, set()).add(nurse_name)
        if day is not None:
            cells.setdefault(category, set()).add(f"{nurse_name}|{day.isoformat()}")
    return (
        {category: sorted(names) for category, names in nurses.items()},
        {category: sorted(items) for category, items in cells.items()},
    )
