from __future__ import annotations

from datetime import date
from typing import Optional

from ortools.sat.python import cp_model

from core.constraints import N_MONTHLY_RANGE_DEFAULT, ScheduleModel
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
    n_monthly_range: tuple[int, int] = N_MONTHLY_RANGE_DEFAULT,
) -> ScheduleResult:
    """한 달치 근무표를 생성한다.

    history: (간호사이름, 날짜) -> ShiftType. 이전 달 마지막 5일 이력 (없으면 O로 간주).
    off_target: 간호사이름 -> 이번달 목표 오프일수 (주말 + 병동 공휴일 수).
    n_monthly_range: 나이트 가능 인원의 월 N 개수 하드 범위 (병동 기본 6~8).
    """
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
        use_assumptions=False, n_monthly_range=n_monthly_range,
    )
    sm.add_tier1_hard_constraints()
    sm.add_tier2_soft_constraints(active_duty_requests)
    sm.add_duty_requests(active_duty_requests)
    sm.add_tier3_exceptions(exceptions)

    sm.model.Minimize(sum(sm.objective_terms()))
    _apply_n_cluster_hint(sm, nurses, current_days, requirements)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 8
    status = solver.Solve(sm.model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # 2차: 정말 Infeasible인 경우에만, 원인 진단을 위해 assumption 모드로 재구성해서 재시도.
        # (assumption을 쓰면 presolve가 제한돼 매번 쓰기엔 느리므로 이 경로에서만 사용)
        diag_sm = ScheduleModel(
            nurses, current_days, lb_days, history, requirements, off_target,
            use_assumptions=True, n_monthly_range=n_monthly_range,
        )
        diag_sm.add_tier1_hard_constraints()
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
    )


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
