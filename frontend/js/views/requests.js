import { api } from "../api.js";

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

const DECISION_LABELS = {
  force: "반영",
  ignore: "미반영",
};

const SHIFT_KEYS = new Set(["D", "E", "N", "O"]);
const WEEKDAY_LABELS = ["일", "월", "화", "수", "목", "금", "토"];
const OTHER_REASONS = ["예비군", "보수교육", "교육", "기타"];

let current = null;
let editor = {
  focusedDate: null,
  selectedDates: new Set(),
  anchorDate: null,
  mode: "prefer",
  otherReason: "예비군",
  name: null,
  dragStartDate: null,
  isDragging: false,
};

export async function renderRequests(container) {
  current = await api.getRequests();
  editor = {
    focusedDate: firstDay(),
    selectedDates: new Set([firstDay()]),
    anchorDate: firstDay(),
    mode: "prefer",
    otherReason: "예비군",
    name: current.names[0] ?? "",
    dragStartDate: null,
    isDragging: false,
  };
  paint(container);
}

function paint(container) {
  container.innerHTML = `
    <h2 style="font-size:1.15rem">근무 신청</h2>
    <p class="caption">${current.year}년 ${current.month}월 신청을 관리합니다.</p>

    ${current.is_admin ? adminLockBlock() : lockNotice()}

    <section class="request-editor" aria-label="근무 신청 빠른 입력">
      <div class="request-editor-top">
        ${current.is_admin ? nameSelect() : ""}
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
        <span>날짜 클릭/드래그 선택</span>
        <span><kbd>D</kbd><kbd>E</kbd><kbd>N</kbd><kbd>O</kbd> 입력</span>
        <span>방향키 이동</span>
        <span>Shift+방향키 범위</span>
        <span>Esc 해제</span>
        <button id="request-help-btn" type="button">도움말</button>
      </div>

      <div id="request-editor-status" class="request-editor-status" aria-live="polite"></div>
      <div class="request-calendar-wrap">
        <table class="request-calendar" aria-label="${current.month}월 근무 신청 달력">
          <thead>
            <tr>${WEEKDAY_LABELS.map((day) => `<th>${day}</th>`).join("")}</tr>
          </thead>
          <tbody>${calendarRows()}</tbody>
        </table>
      </div>

      <div class="request-actions">
        <button id="request-clear-selection" type="button">선택 해제</button>
        <button id="request-delete-selection" type="button" ${isInputDisabled() ? "disabled" : ""}>선택 날짜 삭제</button>
        <span class="caption" style="margin:0">단일 날짜 입력 후에는 자동으로 다음 날짜로 이동합니다.</span>
      </div>
    </section>

    <div id="requests-status" class="caption"></div>
    <div id="request-help" class="request-help is-hidden">
      <strong>빠른 입력</strong>
      <div><kbd>D</kbd> 데이, <kbd>E</kbd> 이브닝, <kbd>N</kbd> 나이트, <kbd>O</kbd> 오프</div>
      <div>선택된 날짜가 여러 개면 같은 값이 한 번에 적용됩니다.</div>
      <div>기타는 선택한 사유를 메모로 저장합니다.</div>
    </div>
    <div id="request-rows"></div>
  `;

  bindEditor(container);
  paintRows(container);
}

function bindEditor(container) {
  if (current.is_admin) {
    container.querySelector("#request-lock").addEventListener("change", async (e) => {
      current = await api.setRequestLock({ locked: e.target.checked });
      paint(container);
    });
    container.querySelector("#request-name").addEventListener("change", () => {
      editor.name = container.querySelector("#request-name").value;
      repaintCalendar(container);
    });
  }

  for (const button of container.querySelectorAll("[data-request-mode]")) {
    button.addEventListener("click", () => {
      editor.mode = button.dataset.requestMode;
      repaintCalendar(container);
    });
  }

  const otherReason = container.querySelector("#request-other-reason");
  if (otherReason) {
    otherReason.addEventListener("change", (e) => {
      editor.otherReason = e.target.value;
    });
  }

  container.querySelector("#request-help-btn").addEventListener("click", () => {
    container.querySelector("#request-help").classList.toggle("is-hidden");
  });
  container.querySelector("#request-clear-selection").addEventListener("click", () => {
    clearSelection();
    repaintCalendar(container);
  });
  container.querySelector("#request-delete-selection").addEventListener("click", () => deleteSelectedRequests(container));

  for (const cell of container.querySelectorAll("[data-date]")) {
    cell.addEventListener("mousedown", (e) => {
      if (isInputDisabled()) return;
      e.preventDefault();
      startSelection(cell.dataset.date);
      repaintCalendar(container);
    });
    cell.addEventListener("mouseenter", () => {
      if (!editor.isDragging || isInputDisabled()) return;
      extendSelection(cell.dataset.date);
      repaintCalendar(container);
    });
    cell.addEventListener("click", () => {
      focusCalendar(container);
    });
  }

  document.addEventListener("mouseup", stopDragging, { once: true });
  container.querySelector(".request-editor").addEventListener("keydown", (e) => handleKeydown(e, container));
  focusCalendar(container);
}

function repaintCalendar(container) {
  const top = container.querySelector(".request-editor-top");
  const status = container.querySelector("#request-editor-status");
  const existingStatus = status.textContent;
  const selected = top.querySelector("#request-name")?.value;
  if (selected) editor.name = selected;
  paint(container);
  container.querySelector("#request-editor-status").textContent = existingStatus || selectionText();
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
    clearSelection();
    repaintCalendar(container);
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
    repaintCalendar(container);
  }
}

function isFormControl(target) {
  return ["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(target.tagName);
}

async function applyShift(container, shift) {
  if (isInputDisabled()) return;
  const dates = selectedDates();
  if (!dates.length) return;
  const status = container.querySelector("#requests-status");
  const name = selectedName(container);
  const kind = editor.mode === "avoid" ? "avoid" : "prefer";
  const memo = editor.mode === "other" ? editor.otherReason : "";

  status.textContent = `${dates.length}개 날짜에 ${shift} ${KIND_LABELS[editor.mode]} 적용 중...`;
  try {
    for (const date of dates) {
      const existing = current.requests.find(
        (item) =>
          item.nurse_name === name &&
          item.date === date &&
          item.kind === kind &&
          item.requested_shift === shift
      );
      if (existing) current = await api.deleteRequest(existing.id);
      current = await api.addRequest({
        nurse_name: current.is_admin ? name : null,
        date,
        kind,
        requested_shift: shift,
        memo,
      });
    }
    const doneMessage = `${dates.length}개 날짜에 ${shift} ${KIND_LABELS[editor.mode]} 적용됨`;
    if (dates.length === 1) moveFocus("ArrowRight", false);
    else editor.selectedDates = new Set(dates);
    paint(container);
    container.querySelector("#requests-status").textContent = doneMessage;
  } catch (err) {
    status.textContent = `오류: ${err.message}`;
  }
}

async function deleteSelectedRequests(container) {
  if (isInputDisabled()) return;
  const dates = selectedDates();
  if (!dates.length) return;
  const status = container.querySelector("#requests-status");
  const name = selectedName(container);
  const targets = current.requests.filter((item) => item.nurse_name === name && dates.includes(item.date));
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

function calendarRows() {
  const dates = monthDates();
  const leading = dates[0].getDay();
  const cells = [];
  for (let i = 0; i < leading; i += 1) cells.push(`<td class="request-day is-empty"></td>`);
  for (const day of dates) cells.push(calendarCell(day));
  while (cells.length % 7 !== 0) cells.push(`<td class="request-day is-empty"></td>`);

  const rows = [];
  for (let i = 0; i < cells.length; i += 7) rows.push(`<tr>${cells.slice(i, i + 7).join("")}</tr>`);
  return rows.join("");
}

function calendarCell(day) {
  const date = toDateString(day);
  const selected = editor.selectedDates.has(date);
  const focused = editor.focusedDate === date;
  const weekend = day.getDay() === 0 || day.getDay() === 6;
  const requests = requestsForDate(date);
  const requestHtml = requests.length
    ? requests.map((item) => requestChip(item)).join("")
    : `<span class="request-day-hint">${focused || selected ? "D/E/N/O" : ""}</span>`;
  return `
    <td
      class="request-day ${weekend ? "is-weekend" : ""} ${selected ? "is-selected" : ""} ${focused ? "is-focused" : ""}"
      tabindex="0"
      data-date="${date}"
      aria-selected="${selected ? "true" : "false"}"
    >
      <div class="request-day-number">${day.getDate()}</div>
      <div class="request-day-items">${requestHtml}</div>
    </td>
  `;
}

function requestChip(item) {
  const isOther = item.memo && item.kind === "prefer";
  const kind = isOther ? "other" : item.kind;
  const label = isOther ? item.memo : KIND_LABELS[item.kind] ?? item.kind;
  return `
    <span class="request-chip request-chip-${kind}" title="${escapeAttr(label)}">
      <strong>${SHIFT_LABELS[item.requested_shift] ?? item.requested_shift}</strong>
      <small>${escapeHtml(label)}</small>
    </span>
  `;
}

function requestsForDate(date) {
  const name = selectedNameFromDocument();
  return current.requests
    .filter((item) => item.nurse_name === name && item.date === date)
    .sort((a, b) => `${a.kind}${a.requested_shift}`.localeCompare(`${b.kind}${b.requested_shift}`));
}

function startSelection(date) {
  editor.focusedDate = date;
  editor.anchorDate = date;
  editor.dragStartDate = date;
  editor.selectedDates = new Set([date]);
  editor.isDragging = true;
}

function extendSelection(date) {
  editor.focusedDate = date;
  editor.selectedDates = new Set(rangeDates(editor.dragStartDate, date));
}

function stopDragging() {
  editor.isDragging = false;
  editor.dragStartDate = null;
}

function moveFocus(key, expand) {
  const offsets = {
    ArrowLeft: -1,
    ArrowRight: 1,
    ArrowUp: -7,
    ArrowDown: 7,
  };
  const currentIndex = dateIndex(editor.focusedDate);
  const nextIndex = Math.max(0, Math.min(monthDates().length - 1, currentIndex + offsets[key]));
  const nextDate = toDateString(monthDates()[nextIndex]);
  editor.focusedDate = nextDate;
  if (expand) {
    editor.anchorDate ||= selectedDates()[0] || nextDate;
    editor.selectedDates = new Set(rangeDates(editor.anchorDate, nextDate));
  } else {
    editor.anchorDate = nextDate;
    editor.selectedDates = new Set([nextDate]);
  }
}

function clearSelection() {
  editor.selectedDates = new Set();
  editor.anchorDate = editor.focusedDate;
}

function selectedDates() {
  return [...editor.selectedDates].sort();
}

function selectionText() {
  const dates = selectedDates();
  if (!dates.length) return "선택된 날짜가 없습니다.";
  if (dates.length === 1) return `${formatDate(dates[0])} 선택됨`;
  return `${formatDate(dates[0])} 외 ${dates.length - 1}일 선택됨`;
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

function nameSelect() {
  return `
    <label class="request-name-select">
      이름
      <select id="request-name">
        ${current.names
          .map(
            (name) =>
              `<option value="${escapeAttr(name)}" ${name === editor.name ? "selected" : ""}>${escapeHtml(name)}</option>`
          )
          .join("")}
      </select>
    </label>
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

function paintRows(container) {
  const wrap = container.querySelector("#request-rows");
  if (!current.requests.length) {
    wrap.innerHTML = `<p class="caption">등록된 신청이 없습니다.</p>`;
    return;
  }

  wrap.innerHTML = `
    <table class="compact-table request-table">
      <thead>
        <tr>
          <th>이름</th>
          <th>날짜</th>
          <th>유형</th>
          <th>근무</th>
          <th>메모</th>
          <th>반영</th>
          <th></th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  `;
  const tbody = wrap.querySelector("tbody");
  for (const item of current.requests) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(item.nurse_name)}</td>
      <td>${item.date}</td>
      <td>${requestKindLabel(item)}</td>
      <td>${SHIFT_LABELS[item.requested_shift] ?? item.requested_shift}</td>
      <td>${escapeHtml(item.memo)}</td>
      <td>${decisionCell(item)}</td>
      <td><button class="remove-btn" data-delete="${item.id}" ${isInputDisabled() ? "disabled" : ""}>삭제</button></td>
    `;
    tbody.appendChild(tr);
  }

  for (const select of wrap.querySelectorAll("[data-decision]")) {
    select.addEventListener("change", async (e) => {
      current = await api.updateRequest(e.target.dataset.decision, { decision: e.target.value });
      paint(container);
    });
  }

  for (const button of wrap.querySelectorAll("[data-delete]")) {
    button.addEventListener("click", async () => {
      current = await api.deleteRequest(button.dataset.delete);
      paint(container);
    });
  }
}

function decisionCell(item) {
  if (!current.is_admin) return DECISION_LABELS[item.decision] ?? item.decision;
  return `
    <select data-decision="${item.id}">
      <option value="force" ${item.decision === "force" ? "selected" : ""}>반영</option>
      <option value="ignore" ${item.decision === "ignore" ? "selected" : ""}>미반영</option>
    </select>
  `;
}

function requestKindLabel(item) {
  return item.memo && item.kind === "prefer" ? "기타" : KIND_LABELS[item.kind] ?? item.kind;
}

function selectedName(container) {
  return current.is_admin ? container.querySelector("#request-name").value : current.names[0];
}

function selectedNameFromDocument() {
  return editor.name ?? document.querySelector("#request-name")?.value ?? current.names[0];
}

function isInputDisabled() {
  return current.locked && !current.is_admin;
}

function focusCalendar(container) {
  container.querySelector(`[data-date="${editor.focusedDate}"]`)?.focus({ preventScroll: true });
  const status = container.querySelector("#request-editor-status");
  if (status) status.textContent = selectionText();
}

function monthDates() {
  const last = new Date(current.year, current.month, 0).getDate();
  return Array.from({ length: last }, (_, index) => new Date(current.year, current.month - 1, index + 1));
}

function rangeDates(start, end) {
  const dates = monthDates();
  const startIndex = dateIndex(start);
  const endIndex = dateIndex(end);
  const [from, to] = startIndex <= endIndex ? [startIndex, endIndex] : [endIndex, startIndex];
  return dates.slice(from, to + 1).map(toDateString);
}

function dateIndex(date) {
  return monthDates().findIndex((item) => toDateString(item) === date);
}

function firstDay() {
  return `${current.year}-${String(current.month).padStart(2, "0")}-01`;
}

function lastDay() {
  return new Date(current.year, current.month, 0).toISOString().slice(0, 10);
}

function toDateString(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function formatDate(date) {
  const [, month, day] = date.split("-");
  return `${Number(month)}/${Number(day)}`;
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
