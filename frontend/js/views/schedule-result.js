import { api } from "../api.js";
import { state } from "../state.js";
import { onClickBusy } from "../ui.js";

const WEEKDAY_KR = ["일", "월", "화", "수", "목", "금", "토"];
const OFF_SHIFTS = ["O", "연차"];
// 오른쪽 개인별 집계 열 (각 간호사의 근무 개수).
const STAT_COLUMNS = ["D", "E", "N", "O", "연차"];
// 근무표 하단 날짜별 인원 집계 행.
const TALLY_ROWS = ["D", "E", "N", "S"];
// 달력뷰 근무 그룹 (근무 코드 -> 표시 라벨).
const CALENDAR_GROUPS = [
  ["D", "day"],
  ["E", "eve"],
  ["N", "night"],
  ["S", "S"],
];
const BASE_EDITABLE_SHIFTS = ["D", "E", "N", "O", "연차"];

let current = null;
let wardSettings = null;
let viewMode = "grid"; // "grid" | "calendar" — 세션 동안만 유지
let scheduleScope = "all"; // "mine" | "all"
let regionMode = false;
let regionSelection = null;
let regenerationPreview = null;
let editingCell = null;
let exportSettings = null;
let disposeRegionSelectionListeners = () => {};
let scheduleEditMode = false;
// 편집 세션 동안 실제로 건드린(값 변경 또는 우클릭 고정 토글) 셀만 담는다 — 저장 전까지
// 서버에는 아무것도 전달되지 않는다. { edits: Map<"이름|날짜", { nurse_name, date, shift, pinned }> }
let editDraft = null;

export async function renderScheduleResult(container) {
  [current, exportSettings, wardSettings] = await Promise.all([
    api.getSchedule(),
    api.getExportSettings(),
    api.getSettings(),
  ]);
  viewMode = state.isAdmin ? "grid" : "calendar";
  scheduleScope = state.isAdmin ? "all" : "mine";
  regionMode = false;
  regionSelection = null;
  regenerationPreview = null;
  editingCell = null;
  scheduleEditMode = false;
  editDraft = null;
  paint(container);
}

function editableShiftsFor(nurseName) {
  const canAssignS = wardSettings?.use_s_shift !== false
    && current?.s_eligible_names?.includes(nurseName);
  return canAssignS ? ["D", "E", "N", "S", "O", "연차"] : BASE_EDITABLE_SHIFTS;
}

function paint(container) {
  // Root-level updates (generate, publish, apply, and a manual edit) replace
  // the result markup. Capture the result grid before doing so, otherwise the
  // browser creates a fresh scroll container at its origin.
  const previousPosition = captureSchedulePosition(container);
  disposeRegionSelectionListeners();
  container.innerHTML = `
    <header class="page-header">
      <h2>${state.isAdmin ? "생성 결과" : "근무표"}</h2>
      <p class="caption">${current.year}년 ${current.month}월 근무표</p>
    </header>
    ${adminControls()}
    ${downloadControls()}
    <div id="schedule-status"></div>
    <div id="schedule-body"></div>
  `;

  if (state.isAdmin) {
    onClickBusy(
      container.querySelector("#generate-schedule-btn"),
      async () => {
        const status = container.querySelector("#schedule-status");
        const stopProgress = showGenerationProgress(status);
        try {
          current = await api.generateSchedule();
          // 새로 생성된 근무표는 이전 편집 세션의 draft와 무관하다 — 그대로 두면
          // 옛 셀 값이 새 근무표 위에 겹쳐 보여 집계가 어긋난다.
          scheduleEditMode = false;
          editDraft = null;
          editingCell = null;
          paint(container);
        } catch (err) {
          status.innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
        } finally {
          stopProgress();
        }
      },
      "생성 중...",
    );
    const publishToggle = container.querySelector("#publish-toggle");
    if (publishToggle) {
      publishToggle.addEventListener("change", async (e) => {
        // 요청이 끝나기 전에 다시 누르면 마지막 응답이 뒤늦게 덮어쓸 수 있다.
        publishToggle.disabled = true;
        const status = container.querySelector("#schedule-status");
        try {
          current = await api.publishSchedule({ published: e.target.checked });
          paint(container);
        } catch (err) {
          publishToggle.checked = !e.target.checked;
          publishToggle.disabled = false;
          status.innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
        }
      });
    }
  }
  const saveExportSettings = container.querySelector("#save-export-settings-btn");
  if (saveExportSettings) {
    onClickBusy(saveExportSettings, async () => {
      const status = container.querySelector("#schedule-status");
      try {
        exportSettings = await api.putExportSettings({
          title_mode: container.querySelector("#export-title-mode").value,
          custom_title: container.querySelector("#export-custom-title").value.trim(),
          holiday_color: container.querySelector("#export-holiday-color").value,
          honored_off_color: container.querySelector("#export-honored-off-color").value,
          summary_fields: [...container.querySelectorAll("[data-summary-field]:checked")].map((input) => input.value),
        });
        status.textContent = "\ub0b4\ubcf4\ub0b4\uae30 \ud45c\uc2dc \uc124\uc815\uc744 \uc800\uc7a5\ud588\uc2b5\ub2c8\ub2e4.";
      } catch (err) {
        status.innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
      }
    }, "\uc800\uc7a5 \uc911...");
  }

  for (const button of container.querySelectorAll("[data-download]")) {
    onClickBusy(
      button,
      async () => {
        const status = container.querySelector("#schedule-status");
        status.innerHTML = "";
        try {
          if (button.dataset.download === "hwpx") await api.downloadHwpx();
          if (button.dataset.download === "xlsx") await api.downloadXlsx();
        } catch (err) {
          status.innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
        }
      },
      "다운로드 중...",
    );
  }

  paintSchedule(container, previousPosition);
}

function captureSchedulePosition(container) {
  const selector = container?.id === "schedule-view" ? ".schedule-scroll" : "#schedule-body .schedule-scroll";
  const scroll = container?.querySelector?.(selector);
  return {
    left: scroll?.scrollLeft ?? 0,
    top: scroll?.scrollTop ?? 0,
    pageLeft: window.scrollX,
    pageTop: window.scrollY,
  };
}

function restoreSchedulePosition(scroll, position) {
  if (!position) return;
  requestAnimationFrame(() => {
    scroll.scrollLeft = position.left;
    scroll.scrollTop = position.top;
    window.scrollTo(position.pageLeft, position.pageTop);
  });
}

function showGenerationProgress(status) {
  const steps = [
    "근무 요청과 제약조건을 확인하고 있어요",
    "가능한 근무 조합을 계산하고 있어요",
    "근무 균형과 휴무일을 조정하고 있어요",
    "최종 근무표를 검증하고 있어요",
  ];
  let stepIndex = 0;
  status.innerHTML = `
    <div class="generation-progress" role="status" aria-live="polite">
      <div class="generation-progress__heading">
        <span class="generation-spinner" aria-hidden="true"></span>
        <div><strong>근무표 생성 중</strong><p>${steps[stepIndex]}</p></div>
      </div>
      <div class="generation-progress__track" aria-hidden="true"><span></span></div>
      <small>조건에 따라 최대 1분 정도 걸릴 수 있습니다.</small>
    </div>`;
  const message = status.querySelector(".generation-progress p");
  const timer = window.setInterval(() => {
    stepIndex = (stepIndex + 1) % steps.length;
    message.textContent = steps[stepIndex];
  }, 4000);
  return () => window.clearInterval(timer);
}

function adminControls() {
  if (!state.isAdmin) return "";
  const canPublish = current.feasible === true;
  return `
    <div class="result-controls">
      <button class="primary inline-primary" id="generate-schedule-btn">근무표 생성</button>
      <label class="inline-check">
        <input type="checkbox" id="publish-toggle" ${current.published ? "checked" : ""} ${canPublish ? "" : "disabled"} />
        결과 공개
      </label>
    </div>
  `;
}

function downloadControls() {
  if (current.feasible !== true || !current.visible) return "";
  const adminSettings = state.isAdmin && exportSettings ? `
    <div class="panel export-settings">
      <h3>\ub0b4\ubcf4\ub0b4\uae30 \ud45c\uc2dc</h3>
      <div class="settings-inline">
        <label>\uc81c\ubaa9 \ud615\uc2dd
          <select id="export-title-mode">
            <option value="ward_month_off" ${exportSettings.title_mode === "ward_month_off" ? "selected" : ""}>\ubcd1\ub3d9\uba85 + \uc6d4 + \uadfc\ubb34\ud45c + OFF</option>
            <option value="hospital_ward_month_off" ${exportSettings.title_mode === "hospital_ward_month_off" ? "selected" : ""}>\uae30\uad00\uba85 + \ubcd1\ub3d9\uba85 + \uc6d4 + \uadfc\ubb34\ud45c + OFF</option>
            <option value="custom" ${exportSettings.title_mode === "custom" ? "selected" : ""}>\uc9c1\uc811 \uc785\ub825\ud55c \uc81c\ubaa9</option>
          </select>
        </label>
        <label>\uc0ac\uc6a9\uc790 \uc81c\ubaa9 <input id="export-custom-title" maxlength="100" value="${escapeHtml(exportSettings.custom_title)}" /></label>
        <label>\ud734\uc77c \uc0c9 <input id="export-holiday-color" type="color" value="${exportSettings.holiday_color}" /></label>
        <label>\ubc18\uc601\ub41c O/\uc5f0\ucc28 \uc2e0\uccad \uc0c9 <input id="export-honored-off-color" type="color" value="${exportSettings.honored_off_color}" /></label>
        <details class="export-summary-fields" open>
          <summary>\uc6b0\uce21 \uc9d1\uacc4 \uc124\uc815</summary>
          <div class="export-summary-fields__options">
            ${[["D", "D"], ["E", "E"], ["N", "N"], ["O", "O"], ["AL", "\uc5f0\ucc28"]].map(([value, label]) => `<label class="inline-check"><input type="checkbox" data-summary-field value="${value}" ${(exportSettings.summary_fields ?? []).includes(value) ? "checked" : ""} /> ${label}</label>`).join("")}
          </div>
        </details>
        <button id="save-export-settings-btn">\ud45c\uc2dc \uc124\uc815 \uc800\uc7a5</button>
      </div>
      <p class="caption">\ub450 \ud30c\uc77c\uc5d0 \ub3d9\uc77c\ud558\uac8c \uc801\uc6a9\ub429\ub2c8\ub2e4. \ud734\uc77c\uc740 \uc8fc\ub9d0\uacfc \uc120\ud0dd \uacf5\ud734\uc77c\uc744 \ud3ec\ud568\ud569\ub2c8\ub2e4.</p>
    </div>` : "";
  return `
    ${adminSettings}
    <div class="result-controls">
      <button data-download="hwpx">HWPX \ub2e4\uc6b4\ub85c\ub4dc</button>
      <button data-download="xlsx">XLSX \ub2e4\uc6b4\ub85c\ub4dc</button>
    </div>
  `;
}

/** 반영된 신청 중 파란 글씨로 강조할 셀 — 오프 희망과 제외 신청, 그리고 보조 인력 표시. */
function highlightCells() {
  const cells = new Set();
  for (const req of current.honored_requests) {
    const isOffPrefer = req.kind === "prefer" && OFF_SHIFTS.includes(req.requested_shift);
    if (isOffPrefer || req.kind === "avoid") cells.add(`${req.nurse_name}|${req.date}`);
  }
  for (const row of current.assistant_rows) {
    for (const date of Object.keys(row.marks)) cells.add(`${row.name}|${date}`);
  }
  return cells;
}

function isHoliday(date, holidays) {
  const day = new Date(`${date}T00:00:00`).getDay();
  return day === 0 || day === 6 || holidays.has(date);
}

function paintSchedule(container, initialPosition = null) {
  const body = container.querySelector("#schedule-body");
  if (!current.visible) {
    body.innerHTML = `<p class="caption">아직 공개된 근무표가 없습니다.</p>`;
    return;
  }
  if (current.feasible === false) {
    body.innerHTML = `
      <div class="error-banner">실행 가능한 근무표를 찾지 못했습니다.</div>
      <pre class="plain-list">${escapeHtml(current.infeasible_categories.join("\n"))}</pre>
    `;
    return;
  }
  if (!current.assignments.length) {
    body.innerHTML = `<p class="caption">생성된 근무표가 없습니다.</p>`;
    return;
  }

  const ctx = buildContext();

  body.innerHTML = `
    ${summaryBlock()}
    ${scopeToggleBlock()}
    <div class="view-toggle ${state.isAdmin ? "" : "member-view-toggle"}">
      <button data-view="grid" class="${viewMode === "grid" ? "active" : ""}" ${scheduleEditMode ? "disabled" : ""}>표 보기</button>
      <button data-view="calendar" class="${viewMode === "calendar" ? "active" : ""}" ${scheduleEditMode ? "disabled" : ""}>달력 보기</button>
    </div>
    ${editControlsHTML()}
    ${regionControlsHTML()}
    <div id="schedule-view"></div>
    <p class="caption">파란 글자는 반영된 듀티 신청, 회색은 주말·공휴일입니다.${scheduleEditMode ? " 우클릭한 셀은 재생성 시에도 고정됩니다." : ""}</p>
    ${checklistBlock()}
    ${violationsBlock()}
  `;

  const view = body.querySelector("#schedule-view");
  let pendingPosition = initialPosition;
  const renderView = () => {
    const previousScroll = view.querySelector(".schedule-scroll");
    const previousPosition = previousScroll
      ? captureSchedulePosition(view)
      : pendingPosition;
    disposeRegionSelectionListeners();
    const visibleContext = scopedContext(ctx);
    view.innerHTML = viewMode === "calendar" ? calendarViewHTML(visibleContext) : gridViewHTML(visibleContext);
    const nextScroll = view.querySelector(".schedule-scroll");
    if (nextScroll) restoreSchedulePosition(nextScroll, previousPosition);
    pendingPosition = null;
    disposeRegionSelectionListeners = bindRegionSelection(body, view, visibleContext, renderView);
    bindScheduleAssignmentEditing(body, view, renderView, visibleContext);
  };
  const scopeButton = body.querySelector("#schedule-scope-toggle");
  if (scopeButton) {
    scopeButton.addEventListener("click", () => {
      scheduleScope = scheduleScope === "mine" ? "all" : "mine";
      body.querySelector(".schedule-scope-controls strong").textContent =
        scheduleScope === "mine" ? "내 근무" : "전체 근무표";
      scopeButton.textContent = scheduleScope === "mine" ? "전체 근무표 보기" : "내 근무만 보기";
      scopeButton.setAttribute("aria-pressed", String(scheduleScope === "all"));
      renderView();
    });
  }
  for (const btn of body.querySelectorAll(".view-toggle button")) {
    btn.addEventListener("click", () => {
      if (viewMode === btn.dataset.view) return;
      viewMode = btn.dataset.view;
      if (viewMode !== "grid") clearRegionState();
      for (const b of body.querySelectorAll(".view-toggle button")) b.classList.remove("active");
      btn.classList.add("active");
      renderView();
    });
  }
  bindScheduleEditControls(container, body);
  renderView();
}

function bindScheduleEditControls(container, body) {
  const startButton = body.querySelector("#schedule-edit-start-btn");
  if (startButton) {
    startButton.addEventListener("click", () => {
      // 영역 다시 생성 도구는 자체 렌더링(renderView)만 갱신하므로, 그 도구가 켜진
      // 상태에서도 이 버튼이 잠깐 보일 수 있다 — 편집 모드로 들어갈 때 확실히 꺼둔다.
      clearRegionState();
      scheduleEditMode = true;
      editDraft = { edits: new Map() };
      paint(container);
    });
  }
  const saveButton = body.querySelector("#schedule-edit-save-btn");
  if (saveButton) {
    onClickBusy(saveButton, async () => {
      const status = container.querySelector("#schedule-status");
      try {
        current = await api.updateScheduleAssignments({
          expected_revision: current.revision ?? current.schedule_revision,
          edits: [...editDraft.edits.values()],
        });
        scheduleEditMode = false;
        editDraft = null;
        editingCell = null;
        paint(container);
      } catch (err) {
        status.innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
      }
    }, "저장 중...");
  }
  const cancelButton = body.querySelector("#schedule-edit-cancel-btn");
  if (cancelButton) {
    cancelButton.addEventListener("click", () => {
      if (editDraft?.edits.size && !confirm("저장하지 않은 변경사항을 취소할까요?")) return;
      scheduleEditMode = false;
      editDraft = null;
      editingCell = null;
      paint(container);
    });
  }
}

function supportsRegionSelection() {
  // 터치 기능이 있는 노트북은 primary pointer가 coarse로 보고되어도 마우스 드래그를
  // 지원한다. 화면 폭만 제한해 작은 모바일 표와의 충돌만 피한다.
  return state.isAdmin && window.matchMedia("(min-width: 761px)").matches;
}

function editControlsHTML() {
  if (!state.isAdmin || current.feasible !== true) return "";
  if (scheduleEditMode) {
    const count = editDraft?.edits.size ?? 0;
    return `
      <div class="result-controls schedule-edit-controls">
        <button class="primary inline-primary" id="schedule-edit-save-btn" ${count ? "" : "disabled"}>저장</button>
        <button type="button" id="schedule-edit-cancel-btn">취소</button>
        <span class="caption">${count ? `${count}개 셀 변경됨 · ` : "변경사항 없음 · "}우클릭: 고정 / 고정 해제</span>
      </div>
    `;
  }
  // 영역 다시 생성 도구와 동시에 켤 수 없다 — 도구가 하나라도 활성 상태면 진입 버튼을 숨긴다.
  if (regionMode || regenerationPreview) return "";
  return `
    <div class="result-controls">
      <button type="button" id="schedule-edit-start-btn">근무표 수정</button>
    </div>
  `;
}

function regionControlsHTML() {
  if (!state.isAdmin) return "";
  if (scheduleEditMode) return "";
  return `
    <section class="schedule-region-tools" id="schedule-region-tools" aria-label="근무표 영역 다시 생성">
      <button type="button" id="region-mode-btn" aria-pressed="false">영역 다시 생성</button>
      <span class="caption" id="region-selection-status">버튼을 누른 뒤 근무 셀을 드래그하세요.</span>
      <button type="button" id="region-clear-btn" hidden>선택 해제</button>
      <button type="button" class="primary inline-primary" id="region-preview-btn" hidden>선택 영역 미리보기</button>
      <button type="button" id="region-cancel-btn" hidden>미리보기 취소</button>
      <button type="button" class="primary inline-primary" id="region-apply-btn" hidden>적용</button>
    </section>`;
}

function clearRegionState() {
  regionMode = false;
  regionSelection = null;
  regenerationPreview = null;
  editingCell = null;
}

function selectedCells(ctx) {
  if (!regionSelection) return [];
  const cells = [];
  for (let row = regionSelection.rowStart; row <= regionSelection.rowEnd; row += 1) {
    for (let col = regionSelection.colStart; col <= regionSelection.colEnd; col += 1) {
      cells.push({ nurse_name: ctx.names[row], date: ctx.dates[col] });
    }
  }
  return cells;
}

function previewAssignments() {
  const candidate = regenerationPreview?.schedule ?? regenerationPreview?.candidate ?? regenerationPreview;
  const assignments = candidate?.assignments ?? regenerationPreview?.assignments ?? [];
  return new Map(assignments.map((item) => [`${item.nurse_name}|${item.date}`, item.shift]));
}

function bindRegionSelection(body, view, ctx, renderView) {
  const tools = body.querySelector("#schedule-region-tools");
  if (!tools) return () => {};
  const supported = supportsRegionSelection();
  tools.classList.toggle("is-supported", supported);
  if (!supported || viewMode !== "grid") return () => {};

  const modeButton = tools.querySelector("#region-mode-btn");
  const clearButton = tools.querySelector("#region-clear-btn");
  const previewButton = tools.querySelector("#region-preview-btn");
  const cancelButton = tools.querySelector("#region-cancel-btn");
  const applyButton = tools.querySelector("#region-apply-btn");
  const status = tools.querySelector("#region-selection-status");
  const cells = selectedCells(ctx);
  modeButton.setAttribute("aria-pressed", String(regionMode));
  modeButton.classList.toggle("active", regionMode);
  clearButton.hidden = !regionSelection;
  previewButton.hidden = !regionSelection || Boolean(regenerationPreview);
  cancelButton.hidden = !regenerationPreview;
  applyButton.hidden = !regenerationPreview;
  if (regenerationPreview) {
    const changed = regenerationPreview.changed_count ?? regenerationPreview.changed_cells?.length ?? previewAssignments().size;
    status.textContent = `선택 ${cells.length}개 · 변경 ${changed}개를 미리 보는 중입니다.`;
  } else if (regionSelection) {
    status.textContent = `직원 ${regionSelection.rowEnd - regionSelection.rowStart + 1}명 · 날짜 ${regionSelection.colEnd - regionSelection.colStart + 1}일 · 셀 ${cells.length}개`;
  } else {
    status.textContent = regionMode ? "근무 셀을 드래그해 직사각형 영역을 선택하세요." : "버튼을 누른 뒤 근무 셀을 드래그하세요.";
  }

  modeButton.onclick = () => {
    regionMode = !regionMode;
    if (!regionMode) regionSelection = null;
    regenerationPreview = null;
    renderView();
  };
  clearButton.onclick = () => {
    regionSelection = null;
    regenerationPreview = null;
    renderView();
  };

  let anchor = null;
  let activePointerId = null;
  let captureTarget = null;
  let pointerPosition = null;
  let autoScrollFrame = null;
  const scroll = view.querySelector(".schedule-scroll");
  const events = new AbortController();
  const edgeSize = 48;
  const maxScrollStep = 22;
  const selectTo = (cell) => {
    if (!anchor) return;
    const row = Number(cell.dataset.regionRow);
    const col = Number(cell.dataset.regionCol);
    regionSelection = {
      rowStart: Math.min(anchor.row, row), rowEnd: Math.max(anchor.row, row),
      colStart: Math.min(anchor.col, col), colEnd: Math.max(anchor.col, col),
    };
    view.querySelectorAll("[data-region-row]").forEach((item) => {
      const r = Number(item.dataset.regionRow);
      const c = Number(item.dataset.regionCol);
      item.classList.toggle("region-selected", r >= regionSelection.rowStart && r <= regionSelection.rowEnd && c >= regionSelection.colStart && c <= regionSelection.colEnd);
    });
  };
  const selectAtPointer = () => {
    if (!pointerPosition) return;
    const cell = document.elementFromPoint(pointerPosition.x, pointerPosition.y)?.closest("[data-region-row]");
    if (cell && view.contains(cell)) selectTo(cell);
  };
  const edgeVelocity = (position, start, end) => {
    if (position < start + edgeSize) return -Math.min(1, (start + edgeSize - position) / edgeSize);
    if (position > end - edgeSize) return Math.min(1, (position - (end - edgeSize)) / edgeSize);
    return 0;
  };
  const stopAutoScroll = () => {
    if (autoScrollFrame !== null) cancelAnimationFrame(autoScrollFrame);
    autoScrollFrame = null;
  };
  const autoScroll = () => {
    autoScrollFrame = null;
    if (!anchor || !pointerPosition || !scroll) return;
    const rect = scroll.getBoundingClientRect();
    const horizontal = edgeVelocity(pointerPosition.x, rect.left, rect.right);
    const vertical = edgeVelocity(pointerPosition.y, rect.top, rect.bottom);
    if (!horizontal && !vertical) return;
    const left = Math.max(0, Math.min(scroll.scrollWidth - scroll.clientWidth, scroll.scrollLeft + horizontal * maxScrollStep));
    const top = Math.max(0, Math.min(scroll.scrollHeight - scroll.clientHeight, scroll.scrollTop + vertical * maxScrollStep));
    if (left !== scroll.scrollLeft || top !== scroll.scrollTop) {
      scroll.scrollLeft = left;
      scroll.scrollTop = top;
      selectAtPointer();
    }
    autoScrollFrame = requestAnimationFrame(autoScroll);
  };
  const updateAutoScroll = () => {
    if (autoScrollFrame === null) autoScrollFrame = requestAnimationFrame(autoScroll);
  };
  view.querySelectorAll("[data-region-row]").forEach((cell) => {
    cell.addEventListener("pointerdown", (event) => {
      if (!regionMode || regenerationPreview || event.button !== 0) return;
      event.preventDefault();
      anchor = { row: Number(cell.dataset.regionRow), col: Number(cell.dataset.regionCol) };
      activePointerId = event.pointerId;
      captureTarget = cell;
      pointerPosition = { x: event.clientX, y: event.clientY };
      cell.setPointerCapture(event.pointerId);
      selectTo(cell);
    });
  });
  const finishSelection = () => {
    if (!anchor) return;
    stopAutoScroll();
    const pointerId = activePointerId;
    anchor = null;
    activePointerId = null;
    pointerPosition = null;
    if (captureTarget?.hasPointerCapture(pointerId)) captureTarget.releasePointerCapture(pointerId);
    captureTarget = null;
    // The selected-cell styling is updated while dragging.  Re-rendering the
    // table here replaces .schedule-scroll and resets its scroll position.
    // Only the controls need to reflect the completed selection.
    const selectionCells = selectedCells(ctx);
    clearButton.hidden = !regionSelection;
    previewButton.hidden = !regionSelection || Boolean(regenerationPreview);
    status.textContent = `직원 ${regionSelection.rowEnd - regionSelection.rowStart + 1}명 · 날짜 ${regionSelection.colEnd - regionSelection.colStart + 1}일 · 셀 ${selectionCells.length}개`;
  };
  view.addEventListener("pointermove", (event) => {
    if (!anchor || event.pointerId !== activePointerId || event.buttons !== 1) return;
    pointerPosition = { x: event.clientX, y: event.clientY };
    selectAtPointer();
    updateAutoScroll();
  }, { signal: events.signal });
  view.addEventListener("pointerup", finishSelection, { signal: events.signal });
  view.addEventListener("pointercancel", finishSelection, { signal: events.signal });
  view.addEventListener("lostpointercapture", finishSelection, { signal: events.signal });
  window.addEventListener("blur", finishSelection, { signal: events.signal });

  previewButton.onclick = async () => {
    previewButton.disabled = true;
    status.textContent = "선택 영역을 다시 계산하고 있습니다…";
    try {
      regenerationPreview = await api.previewScheduleRegeneration({
        expected_revision: current.revision ?? current.schedule_revision,
        cells: selectedCells(ctx),
      });
      renderView();
    } catch (err) {
      body.closest("main")?.querySelector("#schedule-status")?.replaceChildren(errorBanner(err.message));
      status.textContent = "미리보기를 만들지 못했습니다.";
      status.textContent = `미리보기 실패: ${err.message}`;
      previewButton.disabled = false;
    }
  };
  cancelButton.onclick = async () => {
    cancelButton.disabled = true;
    try {
      if (regenerationPreview?.preview_id) await api.cancelScheduleRegeneration(regenerationPreview.preview_id);
    } catch (err) {
      body.closest("main")?.querySelector("#schedule-status")?.replaceChildren(errorBanner(err.message));
    } finally {
      regenerationPreview = null;
      renderView();
    }
  };
  applyButton.onclick = async () => {
    applyButton.disabled = true;
    try {
      current = await api.applyScheduleRegeneration(regenerationPreview.preview_id);
      clearRegionState();
      // 재생성된 근무표에 이전 편집 draft가 겹쳐 보이지 않도록 함께 비운다.
      scheduleEditMode = false;
      editDraft = null;
      paint(body.closest("main") ?? body.parentElement);
    } catch (err) {
      body.closest("main")?.querySelector("#schedule-status")?.replaceChildren(errorBanner(err.message));
      applyButton.disabled = false;
    }
  };
  return () => {
    finishSelection();
    events.abort();
  };
}

function isManualOverride(name, date) {
  const key = `${name}|${date}`;
  const draftEdit = editDraft?.edits.get(key);
  if (draftEdit) return draftEdit.pinned;

  const persistedCells = current.manual_override_cells;
  if (Array.isArray(persistedCells)) return persistedCells.includes(key);

  // 이전 응답 형태도 수용해 화면 전환 중 핀 표시가 사라지지 않게 한다.
  const overrides = current.manual_overrides ?? [];
  if (Array.isArray(overrides)) {
    return overrides.some((item) =>
      item === key || (item?.nurse_name === name && item?.date === date)
    );
  }
  return Boolean(overrides[key]);
}

function draftShiftFor(name, date) {
  return editDraft?.edits.get(`${name}|${date}`)?.shift;
}

function bindScheduleAssignmentEditing(body, view, renderView, ctx) {
  if (!state.isAdmin || !scheduleEditMode || viewMode !== "grid" || current.feasible !== true) return;

  for (const button of view.querySelectorAll("[data-duty-editor-toggle]")) {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      const next = { nurse_name: button.dataset.nurse, date: button.dataset.date };
      editingCell = editingCell?.nurse_name === next.nurse_name && editingCell?.date === next.date ? null : next;
      renderView();
    });
    button.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      const nurse_name = button.dataset.nurse;
      const date = button.dataset.date;
      const key = `${nurse_name}|${date}`;
      const pinned = !isManualOverride(nurse_name, date);
      const existing = editDraft.edits.get(key);
      const shift = existing?.shift ?? ctx.byNurse.get(nurse_name)?.get(date) ?? "";
      editDraft.edits.set(key, { nurse_name, date, shift, pinned });
      paint(body.closest("main") ?? body.parentElement);
    });
  }

  for (const button of view.querySelectorAll("[data-assignment-shift]")) {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const nurse_name = button.dataset.nurse;
      const date = button.dataset.date;
      const shift = button.dataset.assignmentShift;
      const key = `${nurse_name}|${date}`;
      // 근무 변경 자체는 자동으로 고정하지 않는다 — 이미 우클릭으로 고정돼 있었다면 유지, 아니면 그대로 미고정.
      const pinned = isManualOverride(nurse_name, date);
      editDraft.edits.set(key, { nurse_name, date, shift, pinned });
      editingCell = null;
      paint(body.closest("main") ?? body.parentElement);
    });
  }
}

function errorBanner(message) {
  const banner = document.createElement("div");
  banner.className = "error-banner";
  banner.textContent = message;
  return banner;
}

function scopeToggleBlock() {
  if (state.isAdmin) return "";
  return `
    <div class="schedule-scope-controls">
      <strong>${scheduleScope === "mine" ? "내 근무" : "전체 근무표"}</strong>
      <button id="schedule-scope-toggle" aria-pressed="${scheduleScope === "all"}">
        ${scheduleScope === "mine" ? "전체 근무표 보기" : "내 근무만 보기"}
      </button>
    </div>
  `;
}

function scopedContext(ctx) {
  if (state.isAdmin || scheduleScope === "all") return ctx;
  return { ...ctx, names: ctx.names.filter((name) => name === state.name) };
}

function buildContext() {
  const dates = current.dates.length
    ? current.dates
    : [...new Set(current.assignments.map((item) => item.date))].sort();
  const holidays = new Set(current.holidays);
  const highlights = highlightCells();
  const charges = new Set(current.charge_cells ?? []);

  const byNurse = new Map();
  for (const item of current.assignments) {
    if (!byNurse.has(item.nurse_name)) byNurse.set(item.nurse_name, new Map());
    byNurse.get(item.nurse_name).set(item.date, item.shift);
  }
  const names = current.nurse_names.length ? current.nurse_names : [...byNurse.keys()];
  const helpers = new Set(current.helper_names ?? []);
  return { dates, holidays, highlights, charges, byNurse, names, helpers };
}

function gridViewHTML({ dates, holidays, highlights, charges, byNurse, names, helpers }) {
  const candidate = previewAssignments();
  const nurseRows = names.map((name, rowIndex) =>
    tableRow(name, dates, holidays, highlights, charges, helpers, (date) => draftShiftFor(name, date) ?? byNurse.get(name)?.get(date), true, rowIndex, candidate)
  );
  const assistantRows = (scheduleScope === "mine" && !state.isAdmin ? [] : current.assistant_rows).map((row) =>
    tableRow(row.name, dates, holidays, highlights, charges, helpers, (date) => row.marks[date], false)
  );
  // 보조 인력은 간호사와 시각적으로 구분되게 빈 행 2줄을 둔다.
  const colspan = 1 + dates.length + STAT_COLUMNS.length;
  const spacerRows = assistantRows.length
    ? `<tr class="spacer-row"><td colspan="${colspan}"></td></tr>`.repeat(2)
    : "";

  // 하단 날짜별 인원 집계 (간호사 배정 기준).
  const tally = (shift) =>
    dates.map((date) => names.reduce((n, name) => n + (byNurse.get(name)?.get(date) === shift ? 1 : 0), 0));
  const tallyRows = TALLY_ROWS.map(
    (shift) => `
      <tr class="tally-row">
        <th>${shift} 합계</th>
        ${tally(shift).map((c) => `<td class="tally-cell">${c || ""}</td>`).join("")}
        ${STAT_COLUMNS.map(() => `<td class="stat-col"></td>`).join("")}
      </tr>
    `
  ).join("");

  return `
    <div class="schedule-scroll">
      <table class="schedule-table">
        <thead>
          <tr class="date-month-row">
            <th rowspan="2">이름</th>
            <th class="date-month-label" colspan="${dates.length}">${monthLabel(dates[0])}</th>
            ${STAT_COLUMNS.map((label) => `<th class="stat-col" rowspan="2">${label}</th>`).join("")}
          </tr>
          <tr class="date-header-row">
            ${dates
              .map(
                (date) =>
                  `<th class="${isHoliday(date, holidays) ? "col-holiday" : ""}">${dateHeader(date)}</th>`
              )
              .join("")}
          </tr>
        </thead>
        <tbody>
          ${nurseRows.join("")}
          ${spacerRows}
          ${assistantRows.join("")}
          ${tallyRows}
        </tbody>
      </table>
    </div>
  `;
}

function calendarViewHTML({ dates, holidays, charges, byNurse, names, helpers }) {
  if (!state.isAdmin) return monthlyScheduleCalendarHTML({ dates, holidays, charges, byNurse, names, helpers });
  // 날짜 열 × 근무 그룹(day/eve/night/S) 행. 각 칸에 명단 순서로 이름 나열, 차지는 ★.
  const cellNames = (date, shift) =>
    names
      .filter((name) => byNurse.get(name)?.get(date) === shift)
      .map((name) => {
        const charged = charges.has(`${name}|${date}`);
        const tag = helpers.has(name) ? '<span class="helper-tag">헬퍼</span>' : "";
        return `<div class="cal-name"><span class="cal-name-line ${charged ? "is-charge" : ""}"><span class="cal-name-text">${escapeHtml(name)}</span>${tag}</span></div>`;
      })
      .join("");

  const groupRows = CALENDAR_GROUPS.map(
    ([shift, label]) => `
      <tr>
        <th class="cal-group">${label}</th>
        ${dates
          .map(
            (date) =>
              `<td class="cal-cell ${isHoliday(date, holidays) ? "col-holiday" : ""}">${cellNames(date, shift)}</td>`
          )
          .join("")}
      </tr>
    `
  ).join("");

  return `
    <div class="schedule-scroll">
      <table class="calendar-table">
        <thead>
          <tr class="date-month-row">
            <th rowspan="2"></th>
            <th class="date-month-label" colspan="${dates.length}">${monthLabel(dates[0])}</th>
          </tr>
          <tr class="date-header-row">
            ${dates
              .map(
                (date) =>
                  `<th class="${isHoliday(date, holidays) ? "col-holiday" : ""}">${dateHeader(date)}</th>`
              )
              .join("")}
          </tr>
        </thead>
        <tbody>${groupRows}</tbody>
      </table>
    </div>
  `;
}

function monthlyScheduleCalendarHTML({ dates, holidays, charges, byNurse, names, helpers }) {
  const leading = new Date(`${dates[0]}T00:00:00`).getDay();
  const slots = [...Array(leading).fill(""), ...dates];
  while (slots.length % 7) slots.push("");

  const dutyItems = (date) => {
    if (scheduleScope === "mine") {
      const shift = byNurse.get(state.name)?.get(date) ?? "";
      if (!shift) return "";
      const charged = charges.has(`${state.name}|${date}`);
      return `<strong class="member-duty-shift shift-${escapeHtml(shift)} ${charged ? "is-charge" : ""}">${escapeHtml(shift)}</strong>`;
    }
    return CALENDAR_GROUPS.map(([shift, label]) => {
      const dutyNames = names.filter((name) => byNurse.get(name)?.get(date) === shift);
      if (!dutyNames.length) return "";
      const visibleNames = dutyNames.slice(0, 2);
      const remaining = dutyNames.length - visibleNames.length;
      const visibleMarkup = visibleNames.map((name) => {
        const charged = charges.has(`${name}|${date}`);
        const helper = helpers.has(name) ? '<span class="helper-tag">헬퍼</span>' : "";
        const nameMarkup = `${escapeHtml(name)}${helper}`;
        return charged ? `<span class="member-charge-name">${nameMarkup}</span>` : nameMarkup;
      }).join(", ");
      if (!remaining) return `<div class="member-duty-group"><strong>${escapeHtml(label)}</strong><span>${visibleMarkup}</span></div>`;
      return `<details class="member-duty-group"><summary><strong>${escapeHtml(label)}</strong><span>${visibleMarkup}<em> 외 ${remaining}명</em></span></summary><div class="member-duty-expanded">${escapeHtml(dutyNames.join(", "))}</div></details>`;
    }).join("");
  };

  return `
    <div class="member-month-calendar is-${scheduleScope}" aria-label="${current.month}월 근무 달력">
      <div class="member-month-weekdays" aria-hidden="true">
        ${WEEKDAY_KR.map((day) => `<span>${day}</span>`).join("")}
      </div>
      <div class="member-month-days">
        ${slots.map((date) => date ? `
          <div class="member-month-day ${isHoliday(date, holidays) ? "is-holiday" : ""}">
            <span class="member-month-day-number">${Number(date.slice(-2))}</span>
            <div class="member-month-day-duty">${dutyItems(date)}</div>
          </div>` : '<span class="member-month-day is-empty"></span>').join("")}
      </div>
    </div>`;
}

function tableRow(name, dates, holidays, highlights, charges, helpers, shiftAt, showCounts, regionRow = null, candidate = new Map()) {
  const isHelper = helpers.has(name);
  const counts = { D: 0, E: 0, N: 0, O: 0, 연차: 0 };
  const cells = dates
    .map((date, colIndex) => {
      let shift = shiftAt(date) ?? "";
      // 헬퍼는 비근무일(O)을 빈칸으로 표시한다.
      if (isHelper && (shift === "O" || shift === "연차")) shift = "";
      if (counts[shift] !== undefined) counts[shift] += 1;
      const classes = [];
      if (shift) classes.push(`shift-${shift}`);
      else if (isHoliday(date, holidays)) classes.push("col-holiday");
      if (highlights.has(`${name}|${date}`)) classes.push("request-hit");
      // 표 보기에서는 차지에 굵기만 주고 별표는 생략(달력뷰에만 표시).
      if (charges.has(`${name}|${date}`)) classes.push("charge-cell");
      const key = `${name}|${date}`;
      const manualOverride = isManualOverride(name, date);
      if (manualOverride) classes.push("manual-override");
      if (editDraft?.edits.has(key)) classes.push("pending-edit");
      const nextShift = candidate.get(key);
      const changed = nextShift != null && nextShift !== shift;
      if (changed) classes.push("region-preview-changed");
      const selected = regionSelection && regionRow != null && regionRow >= regionSelection.rowStart && regionRow <= regionSelection.rowEnd && colIndex >= regionSelection.colStart && colIndex <= regionSelection.colEnd;
      if (selected) classes.push("region-selected");
      const attrs = regionRow == null ? "" : ` data-region-row="${regionRow}" data-region-col="${colIndex}" data-nurse="${escapeHtml(name)}" data-date="${date}"`;
      const content = changed ? `<span class="region-old-shift">${escapeHtml(shift)}</span><strong>${escapeHtml(nextShift)}</strong>` : escapeHtml(shift);
      const isEditing = editingCell?.nurse_name === name && editingCell?.date === date;
      const editor = isEditing ? `
        <div class="schedule-duty-editor" role="group" aria-label="${escapeHtml(name)} ${date} 근무 변경">
          ${editableShiftsFor(name).map((value) => `<button type="button" data-assignment-shift="${escapeHtml(value)}" data-nurse="${escapeHtml(name)}" data-date="${date}" ${value === shift ? "disabled" : ""}>${escapeHtml(value)}</button>`).join("")}
        </div>` : "";
      const display = regionRow == null ? content : `
        <button type="button" class="schedule-duty-cell-button" data-duty-editor-toggle data-nurse="${escapeHtml(name)}" data-date="${date}" aria-expanded="${isEditing}" aria-label="${escapeHtml(name)} ${date} 근무 ${escapeHtml(shift)} 변경">
          ${content}${manualOverride ? '<span class="manual-override-pin" aria-label="수동 고정">📌</span>' : ""}
        </button>${editor}`;
      return `<td class="${classes.join(" ")}"${attrs}>${display}</td>`;
    })
    .join("");
  const statCells = STAT_COLUMNS.map(
    (key) => `<td class="stat-col">${showCounts ? counts[key] || "" : ""}</td>`
  ).join("");
  const label = escapeHtml(name) + (isHelper ? '<span class="helper-tag">헬퍼</span>' : "");
  return `<tr><th>${label}</th>${cells}${statCells}</tr>`;
}

function monthLabel(date) {
  const [, month] = date.split("-");
  return `${Number(month)}월`;
}

function dateHeader(date) {
  const [, , day] = date.split("-");
  const weekday = WEEKDAY_KR[new Date(`${date}T00:00:00`).getDay()];
  return `<span class="date-header-day">${Number(day)}</span><span class="date-header-weekday">${weekday}</span>`;
}

function summaryBlock() {
  if (!state.isAdmin) return "";
  const validation = current.validation_ok == null ? "-" : current.validation_ok ? "통과" : "실패";
  return `
    <div class="metric-row">
      ${metric(current.published ? "공개 중" : "비공개", "공개 상태")}
      ${metric(current.holidays.length, "공휴일")}
      ${metric(current.objective_value ?? "-", "목적값")}
      ${metric(validation, "검증")}
    </div>
  `;
}

function metric(value, label) {
  return `<div><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`;
}

function checklistBlock() {
  if (!state.isAdmin || !current.checklist.length) return "";
  const unmet = current.checklist.filter((item) => !item.ok).length;
  const notice = unmet
    ? `<div class="error-banner">미반영 항목 ${unmet}건 — 아래 표에서 ❌ 항목을 확인하세요.</div>`
    : `<p class="caption">입력한 모든 제약 조건이 반영되었습니다.</p>`;
  return `
    <section class="panel" style="margin-bottom:1rem">
      <h3>입력 조건 반영 현황</h3>
      ${notice}
      <table class="compact-table">
        <thead>
          <tr><th>항목</th><th>대상</th><th>기준(입력)</th><th>실제</th><th>반영</th></tr>
        </thead>
        <tbody>
          ${current.checklist
            .map(
              (row) => `
                <tr>
                  <td>${escapeHtml(row.item)}</td>
                  <td>${escapeHtml(row.subject)}</td>
                  <td>${escapeHtml(row.expected)}</td>
                  <td>${escapeHtml(row.actual)}</td>
                  <td>${row.ok ? "✅" : "❌"}</td>
                </tr>
              `
            )
            .join("")}
        </tbody>
      </table>
    </section>
  `;
}

function violationsBlock() {
  if (!state.isAdmin || !current.violations.length) return "";
  return `
    <section class="panel">
      <h3>검증 오류</h3>
      <ul class="plain-list">${current.violations.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
    </section>
  `;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
