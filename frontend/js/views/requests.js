import { api } from "../api.js";
import { onClickBusy } from "../ui.js";

const SHIFT_LABELS = {
  O: "오프",
  D: "D",
  E: "E",
  N: "N",
};

const KIND_LABELS = {
  prefer: "희망",
  avoid: "제외",
  other: "기타",
};

const SHIFT_KEYS = new Set(["D", "E", "N", "O"]);
const WEEKDAY_KR = ["일", "월", "화", "수", "목", "금", "토"];
const OTHER_REASONS = ["예비군", "보수교육", "교육", "기타"];

let current = null;
let editor = {
  focusedKey: "",
  anchorKey: "",
  selectedKeys: new Set(),
  dragStartKey: "",
  isDragging: false,
  mode: "prefer",
  otherReason: "예비군",
  mobileName: "",
};

export async function renderRequests(container) {
  current = await api.getRequests();
  const first = cellKey(visibleNames()[0] ?? "", monthDateStrings()[0] ?? firstDay());
  editor = {
    focusedKey: first,
    anchorKey: first,
    selectedKeys: new Set(first ? [first] : []),
    dragStartKey: "",
    isDragging: false,
    mode: "prefer",
    otherReason: "예비군",
    mobileName: visibleNames()[0] ?? "",
  };
  paint(container);
}

function paint(container) {
  const previousScroll = container.querySelector(".request-editor .schedule-scroll");
  const previousScrollLeft = previousScroll?.scrollLeft ?? 0;
  const previousScrollTop = previousScroll?.scrollTop ?? 0;
  document.body.classList.remove("has-request-sheet");
  container.innerHTML = `
    <h2 style="font-size:1.15rem">근무 신청</h2>
    <p class="caption">${current.year}년 ${current.month}월 신청을 관리합니다.</p>

    ${current.is_admin ? adminLockBlock() : lockNotice()}

    <section class="request-editor ${current.is_admin ? "is-admin" : "is-member"}" aria-label="근무 신청 빠른 입력">
      <div class="request-editor-top">
        <div class="request-mode-group" role="group" aria-label="신청 유형">
          ${modeButton("prefer", "희망")}
          ${modeButton("avoid", "제외")}
          ${modeButton("other", "기타")}
        </div>
        <label class="request-other-reason ${editor.mode === "other" ? "" : "is-hidden"}">
          기타 사유
          <select id="request-other-reason" ${isInputDisabled() ? "disabled" : ""}>
            ${OTHER_REASONS.map(
              (reason) => `<option value="${reason}" ${editor.otherReason === reason ? "selected" : ""}>${reason}</option>`
            ).join("")}
          </select>
        </label>
      </div>

      <div class="request-guide-bar">
        <strong>현재: ${KIND_LABELS[editor.mode]}</strong>
        <span class="guide-keyboard">이름-날짜 셀 클릭/드래그</span>
        <span class="guide-keyboard"><kbd>D</kbd><kbd>E</kbd><kbd>N</kbd><kbd>O</kbd> 입력</span>
        <span class="guide-keyboard">방향키 이동</span>
        <span class="guide-keyboard">Shift+방향키 범위</span>
        <span class="guide-keyboard">Esc 해제</span>
        <span class="guide-touch">날짜를 누르고 근무를 선택하세요</span>
        <button id="request-help-btn" type="button">도움말</button>
      </div>

      <div class="request-shift-bar" role="group" aria-label="근무 입력">
        ${shiftButton("D", "D")}
        ${shiftButton("E", "E")}
        ${shiftButton("N", "N")}
        ${shiftButton("O", "오프")}
      </div>

      <div id="request-editor-status" class="request-editor-status" aria-live="polite"></div>
      ${mobileCalendar()}
      <div class="schedule-scroll">
        <table class="request-grid" aria-label="${current.month}월 근무 신청 표">
          <thead>
            <tr>
              <th>이름</th>
              ${monthDateStrings().map((date) => `<th class="${isWeekend(date) ? "col-holiday" : ""}">${dayLabel(date)}</th>`).join("")}
            </tr>
          </thead>
          <tbody>${requestGridRows()}</tbody>
        </table>
      </div>

      ${mobileShiftSheet()}

      <div class="request-actions">
        <button id="request-clear-selection" type="button">선택 해제</button>
        <button id="request-delete-selection" type="button" ${isInputDisabled() ? "disabled" : ""}>선택 셀 삭제</button>
        <span class="caption" style="margin:0">단일 셀 입력 후에는 오른쪽 셀로 자동 이동합니다.</span>
      </div>
    </section>

    <div id="requests-status" class="caption"></div>
    <div id="request-help" class="request-help is-hidden">
      <strong>빠른 입력</strong>
      <div>모든 멤버의 신청이 한 표에 표시됩니다. 셀을 선택하고 <kbd>D</kbd>/<kbd>E</kbd>/<kbd>N</kbd>/<kbd>O</kbd>를 누르세요.</div>
      <div>드래그 또는 Shift+방향키로 여러 셀을 선택하면 한 번에 적용됩니다.</div>
      <div>기타는 선택한 사유를 메모로 저장합니다.</div>
    </div>
  `;

  bindEditor(container);
  const nextScroll = container.querySelector(".request-editor .schedule-scroll");
  if (nextScroll) {
    requestAnimationFrame(() => {
      nextScroll.scrollLeft = previousScrollLeft;
      nextScroll.scrollTop = previousScrollTop;
    });
  }
}

function bindEditor(container) {
  if (current.is_admin) {
    container.querySelector("#request-lock").addEventListener("change", async (e) => {
      current = await api.setRequestLock({ locked: e.target.checked });
      paint(container);
    });
  }

  for (const button of container.querySelectorAll("[data-request-mode]")) {
    button.addEventListener("click", () => {
      editor.mode = button.dataset.requestMode;
      repaint(container);
    });
  }

  const otherReason = container.querySelector("#request-other-reason");
  if (otherReason) {
    otherReason.addEventListener("change", (e) => {
      editor.otherReason = e.target.value;
    });
  }

  container.querySelector("#request-mobile-name")?.addEventListener("change", (event) => {
    editor.mobileName = event.target.value;
    const key = cellKey(editor.mobileName, monthDateStrings()[0] ?? firstDay());
    editor.focusedKey = key;
    editor.anchorKey = key;
    editor.selectedKeys = new Set([key]);
    repaint(container);
  });

  // 폰에서는 더블탭이 흔하다. applyShift가 끝나기 전 두 번째 탭이 들어오면
  // 같은 셀에 중복 요청이 나간다.
  for (const button of container.querySelectorAll("[data-apply-shift]")) {
    onClickBusy(button, () => applyShift(container, button.dataset.applyShift));
  }

  for (const day of container.querySelectorAll("[data-mobile-cell-key]")) bindMobileDay(container, day);

  for (const closeButton of container.querySelectorAll("[data-sheet-close]")) {
    closeButton.addEventListener("click", () => closeMobileSheet(container));
  }

  container.querySelector("#request-help-btn").addEventListener("click", () => {
    container.querySelector("#request-help").classList.toggle("is-hidden");
  });
  container.querySelector("#request-clear-selection").addEventListener("click", () => {
    clearSelection();
    updateGridSelection(container);
  });
  onClickBusy(container.querySelector("#request-delete-selection"), () => deleteSelectedRequests(container));

  for (const cell of container.querySelectorAll("[data-cell-key]")) {
    cell.addEventListener("mousedown", (e) => {
      if (isInputDisabled()) return;
      e.preventDefault();
      startSelection(cell.dataset.cellKey);
      // Register for every drag.  A one-time listener registered at render
      // time can be consumed by an unrelated click, leaving selection stuck.
      document.addEventListener("mouseup", stopDragging, { once: true });
      updateGridSelection(container);
    });
    cell.addEventListener("mouseenter", () => {
      if (!editor.isDragging || isInputDisabled()) return;
      extendSelection(cell.dataset.cellKey);
      updateGridSelection(container);
    });
    cell.addEventListener("click", () => focusGrid(container));
  }

  container.querySelector(".request-editor").addEventListener("keydown", (e) => handleKeydown(e, container));
  focusGrid(container);
}

function repaint(container) {
  const statusText = container.querySelector("#request-editor-status")?.textContent ?? "";
  paint(container);
  container.querySelector("#request-editor-status").textContent = statusText || selectionText();
}

function updateGridSelection(container) {
  for (const cell of container.querySelectorAll("[data-cell-key]")) {
    const key = cell.dataset.cellKey;
    const selected = editor.selectedKeys.has(key);
    const focused = editor.focusedKey === key;
    cell.classList.toggle("is-selected", selected);
    cell.classList.toggle("is-focused", focused);
    cell.setAttribute("aria-selected", String(selected));
    const hint = cell.querySelector(".request-day-hint");
    if (hint) hint.textContent = focused || selected ? "D/E/N/O" : "";
  }
  focusGrid(container);
}

function handleKeydown(e, container) {
  if (isFormControl(e.target)) return;
  const key = e.key.toUpperCase();
  if (SHIFT_KEYS.has(key)) {
    e.preventDefault();
    applyShift(container, key);
    return;
  }
  if (e.key === "Escape") {
    e.preventDefault();
    if (container.querySelector(".request-sheet.is-open")) {
      closeMobileSheet(container);
      return;
    }
    clearSelection();
    updateGridSelection(container);
    return;
  }
  if (e.key === "Backspace" || e.key === "Delete") {
    e.preventDefault();
    deleteSelectedRequests(container);
    return;
  }
  if (e.key.startsWith("Arrow")) {
    e.preventDefault();
    moveFocus(e.key, e.shiftKey);
    updateGridSelection(container);
  }
}

function isFormControl(target) {
  return ["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(target.tagName);
}

async function applyShift(container, shift) {
  if (isInputDisabled()) return;
  const cells = selectedCells();
  if (!cells.length) return;
  const status = container.querySelector("#requests-status");
  const kind = editor.mode === "avoid" ? "avoid" : "prefer";
  const memo = editor.mode === "other" ? editor.otherReason : "";

  status.textContent = `${cells.length}개 셀에 ${shift} ${KIND_LABELS[editor.mode]} 적용 중...`;
  try {
    for (const cell of cells) {
      const replacing = current.requests.filter(
        (item) => sameRequestBucket(item, cell.name, cell.date) || isOppositeRequest(item, cell.name, cell.date)
      );
      for (const item of replacing) current = await api.deleteRequest(item.id);
      current = await api.addRequest({
        nurse_name: current.is_admin ? cell.name : null,
        date: cell.date,
        kind,
        requested_shift: shift,
        memo,
      });
    }

    const doneMessage = `${cells.length}개 셀에 ${shift} ${KIND_LABELS[editor.mode]} 적용됨`;
    if (cells.length === 1) moveFocus("ArrowRight", false);
    else editor.selectedKeys = new Set(cells.map((cell) => cellKey(cell.name, cell.date)));
    paint(container);
    container.querySelector("#requests-status").textContent = doneMessage;
  } catch (err) {
    status.textContent = `오류: ${err.message}`;
  }
}

async function deleteSelectedRequests(container) {
  if (isInputDisabled()) return;
  const cells = selectedCells();
  if (!cells.length) return;
  const keys = new Set(cells.map((cell) => cellKey(cell.name, cell.date)));
  const targets = current.requests.filter((item) => keys.has(cellKey(item.nurse_name, item.date)));
  const status = container.querySelector("#requests-status");
  status.textContent = `${targets.length}개 신청 삭제 중...`;
  try {
    for (const item of targets) current = await api.deleteRequest(item.id);
    const doneMessage = `${targets.length}개 신청 삭제됨`;
    paint(container);
    container.querySelector("#requests-status").textContent = doneMessage;
  } catch (err) {
    status.textContent = `오류: ${err.message}`;
  }
}

function sameRequestBucket(item, name, date) {
  if (item.nurse_name !== name || item.date !== date) return false;
  if (editor.mode === "avoid") return item.kind === "avoid";
  if (editor.mode === "other") return item.kind === "prefer" && Boolean(item.memo);
  return item.kind === "prefer" && !item.memo;
}

function isOppositeRequest(item, name, date) {
  if (item.nurse_name !== name || item.date !== date) return false;
  const nextKind = editor.mode === "avoid" ? "avoid" : "prefer";
  return item.kind !== nextKind;
}

function requestGridRows() {
  const dates = monthDateStrings();
  return visibleNames()
    .map(
      (name) => `
        <tr>
          <th>${escapeHtml(name)}</th>
          ${dates.map((date) => requestCell(name, date)).join("")}
        </tr>
      `
    )
    .join("");
}

function mobileCalendar() {
  const name = current.is_admin ? (editor.mobileName || visibleNames()[0] || "") : (visibleNames()[0] ?? "");
  const dates = monthDateStrings();
  const leading = new Date(`${dates[0]}T00:00:00`).getDay();
  const slots = [...Array(leading).fill(""), ...dates];
  while (slots.length % 7) slots.push("");

  return `
    ${current.is_admin ? `
      <label class="request-mobile-name">
        간호사
        <select id="request-mobile-name">
          ${visibleNames().map((item) => `<option value="${escapeAttr(item)}" ${item === name ? "selected" : ""}>${escapeHtml(item)}</option>`).join("")}
        </select>
      </label>
    ` : ""}
    <div class="request-mobile-calendar" aria-label="${current.month}월 근무 신청 달력">
      <div class="request-mobile-weekdays" aria-hidden="true">
        ${["일", "월", "화", "수", "목", "금", "토"].map((day) => `<span>${day}</span>`).join("")}
      </div>
      <div class="request-mobile-days">
        ${slots.map((date) => (date ? mobileCalendarDay(name, date) : `<span class="request-mobile-day is-empty"></span>`)).join("")}
      </div>
    </div>
  `;
}

function mobileCalendarDay(name, date) {
  const key = cellKey(name, date);
  const requests = requestsForCell(name, date);
  const selected = editor.selectedKeys.has(key);
  return `
    <button
      type="button"
      class="request-mobile-day ${isWeekend(date) ? "is-weekend" : ""} ${selected ? "is-selected" : ""}"
      data-mobile-cell-key="${escapeAttr(key)}"
      aria-label="${formatDate(date)}${requests.length ? `, 신청 ${requests.length}건` : ""}"
      ${isInputDisabled() ? "disabled" : ""}
    >
      <span class="request-mobile-day-number">${Number(date.slice(-2))}</span>
      <span class="request-mobile-day-items">${requests.map((item) => mobileRequestBadge(item)).join("")}</span>
    </button>
  `;
}

function mobileShiftSheet() {
  return `
    <div class="request-sheet" aria-hidden="true">
      <button class="request-sheet-backdrop" type="button" data-sheet-close aria-label="닫기"></button>
      <section class="request-sheet-panel" role="dialog" aria-modal="true" aria-labelledby="request-sheet-title">
        <div class="request-sheet-handle" aria-hidden="true"></div>
        <div class="request-sheet-heading">
          <div>
            <strong id="request-sheet-title">근무 신청</strong>
            <span id="request-sheet-date"></span>
          </div>
          <button type="button" data-sheet-close aria-label="닫기">×</button>
        </div>
        <div id="request-sheet-content"></div>
      </section>
    </div>
  `;
}

function mobileRequestBadge(item) {
  const kind = requestKind(item);
  const shift = SHIFT_LABELS[item.requested_shift] ?? item.requested_shift;
  const label = kind === "avoid" ? `제외 ${shift}` : kind === "other" ? `${shift} 기타` : shift;
  return `<strong class="request-mobile-shift is-${kind}">${escapeHtml(label)}</strong>`;
}

function openMobileSheet(container) {
  const sheet = container.querySelector(".request-sheet");
  if (!sheet) return;
  const cell = selectedCells()[0];
  sheet.querySelector("#request-sheet-date").textContent = cell ? `${formatDate(cell.date)} (${dayLabel(cell.date).split("(")[1]}` : "";
  renderMobileSheetContent(container);
  sheet.classList.add("is-open");
  sheet.setAttribute("aria-hidden", "false");
  document.body.classList.add("has-request-sheet");
  sheet.querySelector("[data-apply-shift]")?.focus();
}

function renderMobileSheetContent(container) {
  const sheet = container.querySelector(".request-sheet");
  const content = sheet?.querySelector("#request-sheet-content");
  const cell = selectedCells()[0];
  if (!sheet || !content || !cell) return;
  const requests = requestsForCell(cell.name, cell.date);
  sheet.classList.remove("is-prefer", "is-avoid", "is-other");
  sheet.classList.add(`is-${editor.mode}`);
  sheet.querySelector("#request-sheet-title").textContent = `${KIND_LABELS[editor.mode]} 신청`;
  content.innerHTML = `
    ${requests.length ? `
      <div class="request-sheet-current">
        <div class="request-sheet-section-label">선택된 근무</div>
        ${requests.map((item) => mobileCurrentRequest(item)).join("")}
      </div>
    ` : ""}
    <div class="request-sheet-section-label">신청 유형</div>
    <div class="request-sheet-modes" role="group" aria-label="신청 유형">
      ${modeButton("prefer", "희망")}${modeButton("avoid", "제외")}${modeButton("other", "기타")}
    </div>
    <div class="request-sheet-section-label">근무 선택</div>
    <div class="request-sheet-shifts" role="group" aria-label="근무 입력">
      ${shiftButton("D", "D")}${shiftButton("E", "E")}${shiftButton("N", "N")}${shiftButton("O", "오프")}
    </div>
  `;

  for (const button of content.querySelectorAll("[data-request-mode]")) {
    button.addEventListener("click", () => {
      editor.mode = button.dataset.requestMode;
      renderMobileSheetContent(container);
    });
  }
  for (const button of content.querySelectorAll("[data-apply-shift]")) {
    onClickBusy(button, () => applyShift(container, button.dataset.applyShift));
  }
  for (const button of content.querySelectorAll("[data-delete-current]")) {
    onClickBusy(button, () => deleteMobileRequest(container, button.dataset.deleteCurrent), "삭제 중...");
  }
}

function mobileCurrentRequest(item) {
  const kind = requestKind(item);
  const shift = SHIFT_LABELS[item.requested_shift] ?? item.requested_shift;
  const label = kind === "other" ? item.memo : KIND_LABELS[kind];
  return `
    <div class="request-sheet-current-item is-${kind}">
      <span><strong>${escapeHtml(shift)}</strong><small>${escapeHtml(label)}</small></span>
      <button type="button" data-delete-current="${escapeAttr(item.id)}" aria-label="${escapeAttr(shift)} ${escapeAttr(label)} 신청 삭제">삭제</button>
    </div>
  `;
}

async function deleteMobileRequest(container, requestId) {
  if (!confirm("선택한 근무 신청을 삭제하시겠습니까?")) return;
  try {
    current = await api.deleteRequest(requestId);
    const message = "근무 신청을 삭제했습니다.";
    paint(container);
    container.querySelector("#requests-status").textContent = message;
  } catch (err) {
    container.querySelector("#requests-status").textContent = `오류: ${err.message}`;
  }
}

function bindMobileDay(container, day) {
  let timer = 0;
  let longPressed = false;
  const open = () => {
    startSelection(day.dataset.mobileCellKey);
    stopDragging();
    openMobileSheet(container);
  };
  day.addEventListener("pointerdown", () => {
    longPressed = false;
    timer = window.setTimeout(() => {
      longPressed = true;
      navigator.vibrate?.(20);
      deleteMobileDateRequests(container, day.dataset.mobileCellKey);
    }, 550);
  });
  const cancel = () => window.clearTimeout(timer);
  day.addEventListener("pointerup", cancel);
  day.addEventListener("pointercancel", cancel);
  day.addEventListener("pointerleave", cancel);
  day.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    cancel();
    longPressed = true;
    deleteMobileDateRequests(container, day.dataset.mobileCellKey);
  });
  day.addEventListener("click", () => {
    if (longPressed) {
      longPressed = false;
      return;
    }
    open();
  });
}

async function deleteMobileDateRequests(container, key) {
  if (isInputDisabled()) return;
  const { name, date } = parseCellKey(key);
  const targets = requestsForCell(name, date);
  if (!targets.length) {
    startSelection(key);
    stopDragging();
    openMobileSheet(container);
    return;
  }
  if (!confirm(`${formatDate(date)} 신청 ${targets.length}건을 모두 삭제하시겠습니까?`)) return;
  try {
    for (const item of targets) current = await api.deleteRequest(item.id);
    const message = `${formatDate(date)} 신청 ${targets.length}건을 삭제했습니다.`;
    paint(container);
    container.querySelector("#requests-status").textContent = message;
  } catch (err) {
    container.querySelector("#requests-status").textContent = `오류: ${err.message}`;
  }
}

function closeMobileSheet(container) {
  const sheet = container.querySelector(".request-sheet");
  if (!sheet) return;
  sheet.classList.remove("is-open");
  sheet.setAttribute("aria-hidden", "true");
  document.body.classList.remove("has-request-sheet");
}

function requestCell(name, date) {
  const key = cellKey(name, date);
  const selected = editor.selectedKeys.has(key);
  const focused = editor.focusedKey === key;
  const requests = requestsForCell(name, date);
  const html = requests.length
    ? requests.map((item) => requestChip(item)).join("")
    : `<span class="request-day-hint">${focused || selected ? "D/E/N/O" : ""}</span>`;
  return `
    <td
      class="request-grid-cell ${isWeekend(date) ? "col-holiday" : ""} ${selected ? "is-selected" : ""} ${focused ? "is-focused" : ""}"
      tabindex="0"
      data-cell-key="${escapeAttr(key)}"
      aria-selected="${selected ? "true" : "false"}"
    >
      <span class="cell-date" aria-hidden="true">${dayLabel(date)}</span>
      ${html}
    </td>
  `;
}

function requestChip(item) {
  const kind = requestKind(item);
  const label = kind === "other" ? item.memo : KIND_LABELS[item.kind] ?? item.kind;
  return `
    <span class="request-chip request-chip-${kind}" title="${escapeAttr(label)}">
      <strong>${SHIFT_LABELS[item.requested_shift] ?? item.requested_shift}</strong>
      <small>${escapeHtml(label)}</small>
    </span>
  `;
}

function requestsForCell(name, date) {
  return current.requests
    .filter((item) => item.nurse_name === name && item.date === date)
    .sort((a, b) => `${requestKind(a)}${a.requested_shift}`.localeCompare(`${requestKind(b)}${b.requested_shift}`));
}

function startSelection(key) {
  editor.focusedKey = key;
  editor.anchorKey = key;
  editor.dragStartKey = key;
  editor.selectedKeys = new Set([key]);
  editor.isDragging = true;
}

function extendSelection(key) {
  editor.focusedKey = key;
  editor.selectedKeys = new Set(rectangleKeys(editor.dragStartKey, key));
}

function stopDragging() {
  editor.isDragging = false;
  editor.dragStartKey = "";
}

function moveFocus(key, expand) {
  const { nameIndex, dateIndex } = keyPosition(editor.focusedKey);
  const next = {
    nameIndex,
    dateIndex,
  };
  if (key === "ArrowLeft") next.dateIndex -= 1;
  if (key === "ArrowRight") next.dateIndex += 1;
  if (key === "ArrowUp") next.nameIndex -= 1;
  if (key === "ArrowDown") next.nameIndex += 1;
  next.nameIndex = clamp(next.nameIndex, 0, visibleNames().length - 1);
  next.dateIndex = clamp(next.dateIndex, 0, monthDateStrings().length - 1);

  const nextKey = keyFromPosition(next.nameIndex, next.dateIndex);
  editor.focusedKey = nextKey;
  if (expand) {
    editor.anchorKey ||= [...editor.selectedKeys][0] || nextKey;
    editor.selectedKeys = new Set(rectangleKeys(editor.anchorKey, nextKey));
  } else {
    editor.anchorKey = nextKey;
    editor.selectedKeys = new Set([nextKey]);
  }
}

function clearSelection() {
  editor.selectedKeys = new Set();
  editor.anchorKey = editor.focusedKey;
}

function selectedCells() {
  return [...editor.selectedKeys].map(parseCellKey).filter((cell) => cell.name && cell.date);
}

function selectionText() {
  const cells = selectedCells();
  if (!cells.length) return "선택된 셀이 없습니다.";
  if (cells.length === 1) return `${cells[0].name} ${formatDate(cells[0].date)} 선택됨`;
  return `${cells[0].name} ${formatDate(cells[0].date)} 외 ${cells.length - 1}개 셀 선택됨`;
}

function rectangleKeys(fromKey, toKey) {
  const from = keyPosition(fromKey);
  const to = keyPosition(toKey);
  const rowStart = Math.min(from.nameIndex, to.nameIndex);
  const rowEnd = Math.max(from.nameIndex, to.nameIndex);
  const colStart = Math.min(from.dateIndex, to.dateIndex);
  const colEnd = Math.max(from.dateIndex, to.dateIndex);
  const result = [];
  for (let row = rowStart; row <= rowEnd; row += 1) {
    for (let col = colStart; col <= colEnd; col += 1) {
      result.push(keyFromPosition(row, col));
    }
  }
  return result;
}

function keyPosition(key) {
  const { name, date } = parseCellKey(key);
  return {
    nameIndex: Math.max(0, visibleNames().indexOf(name)),
    dateIndex: Math.max(0, monthDateStrings().indexOf(date)),
  };
}

function keyFromPosition(nameIndex, dateIndex) {
  return cellKey(visibleNames()[nameIndex] ?? "", monthDateStrings()[dateIndex] ?? "");
}

function adminLockBlock() {
  return `
    <label class="inline-check" style="margin-bottom:1rem">
      <input type="checkbox" id="request-lock" ${current.locked ? "checked" : ""} />
      신청 마감
    </label>
  `;
}

function lockNotice() {
  return current.locked ? `<div class="error-banner">근무 신청이 마감되었습니다.</div>` : "";
}

/** 키보드 없이도 신청을 넣을 수 있어야 한다 — 폰에는 D/E/N/O를 칠 방법이 없다. */
function shiftButton(shift, label) {
  return `
    <button
      type="button"
      data-apply-shift="${shift}"
      ${isInputDisabled() ? "disabled" : ""}
    >${label}</button>
  `;
}

function modeButton(mode, label) {
  return `
    <button
      type="button"
      class="${editor.mode === mode ? "active" : ""}"
      data-request-mode="${mode}"
      ${isInputDisabled() ? "disabled" : ""}
    >${label}</button>
  `;
}

function requestKind(item) {
  return item.memo && item.kind === "prefer" ? "other" : item.kind;
}

function visibleNames() {
  return current.names;
}

function isInputDisabled() {
  return current.locked && !current.is_admin;
}

function focusGrid(container) {
  container.querySelector(`[data-cell-key="${cssAttrValue(editor.focusedKey)}"]`)?.focus({ preventScroll: true });
  const status = container.querySelector("#request-editor-status");
  if (status) status.textContent = selectionText();
}

function monthDateStrings() {
  const last = new Date(current.year, current.month, 0).getDate();
  return Array.from({ length: last }, (_, index) =>
    `${current.year}-${String(current.month).padStart(2, "0")}-${String(index + 1).padStart(2, "0")}`
  );
}

function firstDay() {
  return `${current.year}-${String(current.month).padStart(2, "0")}-01`;
}

function dayLabel(date) {
  const [, month, day] = date.split("-");
  const weekday = WEEKDAY_KR[new Date(`${date}T00:00:00`).getDay()];
  return `${Number(month)}/${Number(day)}(${weekday})`;
}

function formatDate(date) {
  const [, month, day] = date.split("-");
  return `${Number(month)}/${Number(day)}`;
}

function isWeekend(date) {
  const day = new Date(`${date}T00:00:00`).getDay();
  return day === 0 || day === 6;
}

function cellKey(name, date) {
  return `${name}|${date}`;
}

function parseCellKey(key) {
  const index = key.lastIndexOf("|");
  return { name: key.slice(0, index), date: key.slice(index + 1) };
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function cssAttrValue(value) {
  return String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function escapeAttr(value) {
  return String(value ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
