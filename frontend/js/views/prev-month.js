import { api } from "../api.js";
import { onClickBusy } from "../ui.js";

// 직전 달 마지막 5일에 넣을 수 있는 근무. "O"(오프)가 기본값이며 저장되지 않는다.
const SHIFTS = [
  { key: "D", label: "D" },
  { key: "E", label: "E" },
  { key: "N", label: "N" },
  { key: "S", label: "S" },
  { key: "O", label: "오프" },
  { key: "연차", label: "연차" },
];
// 키보드 입력 → 근무. 연차는 A 키에 매핑한다.
const KEY_TO_SHIFT = { D: "D", E: "E", N: "N", S: "S", O: "O", A: "연차" };
const WEEKDAY_KR = ["일", "월", "화", "수", "목", "금", "토"];

let current = null;
let editor = null;

export async function renderPrevMonth(container) {
  current = await api.getPrevMonth();
  resetEditor();
  paint(container);
}

function resetEditor() {
  const first = cellKey(current.nurse_names[0] ?? "", current.dates[0] ?? "");
  editor = {
    // 작업용 사본: { name: { dateiso: shift } } — 오프는 담지 않는다.
    values: deepCopyValues(current.values),
    focusedKey: first,
    anchorKey: first,
    selectedKeys: new Set(first ? [first] : []),
    dragStartKey: "",
    isDragging: false,
    dirty: false,
  };
}

function paint(container) {
  const { year, month, dates, nurse_names: names, confirmed } = current;
  const previousScroll = container.querySelector(".prev-month-editor .schedule-scroll");
  const scrollLeft = previousScroll?.scrollLeft ?? 0;

  container.innerHTML = `
    <h2 style="font-size:1.15rem">직전 달 근무</h2>
    <p class="caption">
      ${year}년 ${month}월 근무표를 만들기 전에, 직전 달 마지막 5일의 근무를 입력하세요.
      월 경계의 연속근무·연속나이트·나이트 후 휴식 규칙에 사용됩니다. 빈칸은 오프로 처리됩니다.
    </p>

    <div class="prev-month-banner ${bannerClass(confirmed)}">${bannerText(confirmed)}</div>

    ${
      names.length === 0
        ? `<p class="caption">먼저 '명단' 탭에서 간호사를 등록하세요.</p>`
        : renderEditor(dates, names)
    }
  `;

  if (names.length) {
    bindEditor(container);
    const nextScroll = container.querySelector(".prev-month-editor .schedule-scroll");
    if (nextScroll) requestAnimationFrame(() => (nextScroll.scrollLeft = scrollLeft));
  }
}

function renderEditor(dates, names) {
  return `
    <section class="request-editor prev-month-editor" aria-label="직전 달 근무 빠른 입력">
      <div class="request-guide-bar">
        <strong>셀을 고르고 근무를 누르세요</strong>
        <span class="guide-keyboard">이름-날짜 셀 클릭/드래그</span>
        <span class="guide-keyboard"><kbd>D</kbd><kbd>E</kbd><kbd>N</kbd><kbd>S</kbd><kbd>O</kbd><kbd>A</kbd>(연차) 입력</span>
        <span class="guide-keyboard">방향키 이동 · Shift+방향키 범위</span>
        <span class="guide-touch">셀을 누르고 아래 근무를 선택하세요</span>
      </div>

      <div class="request-shift-bar" role="group" aria-label="근무 입력">
        ${SHIFTS.map((shift) => shiftButton(shift.key, shift.label)).join("")}
      </div>

      <div id="prev-month-selection" class="request-editor-status" aria-live="polite"></div>

      <div class="schedule-scroll">
        <table class="request-grid" aria-label="직전 달 근무 입력 표">
          <thead>
            <tr>
              <th>이름</th>
              ${dates.map((iso) => `<th class="${isWeekend(iso) ? "col-holiday" : ""}">${dayLabel(iso)}</th>`).join("")}
            </tr>
          </thead>
          <tbody>${gridRows(dates, names)}</tbody>
        </table>
      </div>

      <div class="request-actions">
        <button id="prev-month-clear" type="button">선택 해제</button>
        <button id="prev-month-reset" type="button">전체 오프로 초기화</button>
        <span class="caption" style="margin:0">단일 셀 입력 후 오른쪽 셀로 자동 이동합니다.</span>
      </div>

      <div style="margin-top:1rem">
        <button class="primary inline-primary" id="prev-month-save">저장</button>
        <span id="prev-month-status" class="caption" style="margin-left:0.8rem"></span>
      </div>
    </section>
  `;
}

function gridRows(dates, names) {
  return names
    .map(
      (name) => `
        <tr>
          <th>${escapeHtml(name)}</th>
          ${dates.map((iso) => gridCell(name, iso)).join("")}
        </tr>`,
    )
    .join("");
}

function gridCell(name, iso) {
  const key = cellKey(name, iso);
  const selected = editor.selectedKeys.has(key);
  const focused = editor.focusedKey === key;
  const shift = shiftAt(name, iso);
  const body = shift
    ? `<span class="prev-month-chip">${escapeHtml(shift)}</span>`
    : `<span class="request-day-hint">${focused || selected ? "D/E/N/S/O" : ""}</span>`;
  return `
    <td
      class="request-grid-cell ${isWeekend(iso) ? "col-holiday" : ""} ${selected ? "is-selected" : ""} ${focused ? "is-focused" : ""}"
      tabindex="0"
      data-cell-key="${escapeAttr(key)}"
      aria-selected="${selected ? "true" : "false"}"
    >
      <span class="cell-date" aria-hidden="true">${dayLabel(iso)}</span>
      ${body}
    </td>
  `;
}

function bindEditor(container) {
  for (const button of container.querySelectorAll("[data-apply-shift]")) {
    onClickBusy(button, () => applyShift(container, button.dataset.applyShift));
  }

  for (const cell of container.querySelectorAll("[data-cell-key]")) {
    cell.addEventListener("mousedown", (e) => {
      e.preventDefault();
      startSelection(cell.dataset.cellKey);
      document.addEventListener("mouseup", stopDragging, { once: true });
      updateSelection(container);
    });
    cell.addEventListener("mouseenter", () => {
      if (!editor.isDragging) return;
      extendSelection(cell.dataset.cellKey);
      updateSelection(container);
    });
    cell.addEventListener("click", () => focusGrid(container));
  }

  container.querySelector(".prev-month-editor").addEventListener("keydown", (e) => handleKeydown(e, container));

  container.querySelector("#prev-month-clear").addEventListener("click", () => {
    clearSelection();
    updateSelection(container);
  });
  container.querySelector("#prev-month-reset").addEventListener("click", () => {
    editor.values = {};
    editor.dirty = true;
    paint(container);
    container.querySelector("#prev-month-status").textContent = "전체 오프로 초기화했습니다. 저장을 눌러 반영하세요.";
  });

  onClickBusy(
    container.querySelector("#prev-month-save"),
    async () => {
      const status = container.querySelector("#prev-month-status");
      status.textContent = "저장 중...";
      try {
        current = await api.putPrevMonth({ values: editor.values });
        resetEditor();
        paint(container);
        container.querySelector("#prev-month-status").textContent = "저장되었습니다.";
      } catch (err) {
        status.textContent = `오류: ${err.message}`;
      }
    },
    "저장 중...",
  );

  focusGrid(container);
}

function handleKeydown(e, container) {
  if (["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(e.target.tagName)) return;
  const key = e.key.toUpperCase();
  if (KEY_TO_SHIFT[key]) {
    e.preventDefault();
    applyShift(container, KEY_TO_SHIFT[key]);
    return;
  }
  if (e.key === "Escape") {
    e.preventDefault();
    clearSelection();
    updateSelection(container);
    return;
  }
  if (e.key === "Backspace" || e.key === "Delete") {
    e.preventDefault();
    applyShift(container, "O");
    return;
  }
  if (e.key.startsWith("Arrow")) {
    e.preventDefault();
    moveFocus(e.key, e.shiftKey);
    updateSelection(container);
  }
}

function applyShift(container, shift) {
  const cells = selectedCells();
  if (!cells.length) return;
  for (const { name, date } of cells) setShift(name, date, shift);
  editor.dirty = true;
  if (cells.length === 1) moveFocus("ArrowRight", false);
  paint(container);
  const label = shift === "O" ? "오프" : shift;
  container.querySelector("#prev-month-status").textContent =
    `${cells.length}개 셀을 ${label}(으)로 설정했습니다. 저장을 눌러 반영하세요.`;
}

function updateSelection(container) {
  for (const cell of container.querySelectorAll("[data-cell-key]")) {
    const key = cell.dataset.cellKey;
    const selected = editor.selectedKeys.has(key);
    const focused = editor.focusedKey === key;
    cell.classList.toggle("is-selected", selected);
    cell.classList.toggle("is-focused", focused);
    cell.setAttribute("aria-selected", String(selected));
    const hint = cell.querySelector(".request-day-hint");
    if (hint) hint.textContent = focused || selected ? "D/E/N/S/O" : "";
  }
  focusGrid(container);
}

// --- 선택 로직 (근무 신청 화면과 동일한 조작감) ---
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

function moveFocus(arrow, expand) {
  const { nameIndex, dateIndex } = keyPosition(editor.focusedKey);
  let nextName = nameIndex;
  let nextDate = dateIndex;
  if (arrow === "ArrowLeft") nextDate -= 1;
  if (arrow === "ArrowRight") nextDate += 1;
  if (arrow === "ArrowUp") nextName -= 1;
  if (arrow === "ArrowDown") nextName += 1;
  nextName = clamp(nextName, 0, current.nurse_names.length - 1);
  nextDate = clamp(nextDate, 0, current.dates.length - 1);
  const nextKey = keyFromPosition(nextName, nextDate);
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
    for (let col = colStart; col <= colEnd; col += 1) result.push(keyFromPosition(row, col));
  }
  return result;
}

function keyPosition(key) {
  const { name, date } = parseCellKey(key);
  return {
    nameIndex: Math.max(0, current.nurse_names.indexOf(name)),
    dateIndex: Math.max(0, current.dates.indexOf(date)),
  };
}

function keyFromPosition(nameIndex, dateIndex) {
  return cellKey(current.nurse_names[nameIndex] ?? "", current.dates[dateIndex] ?? "");
}

function focusGrid(container) {
  container.querySelector(`[data-cell-key="${cssAttrValue(editor.focusedKey)}"]`)?.focus({ preventScroll: true });
  const status = container.querySelector("#prev-month-selection");
  if (status) status.textContent = selectionText();
}

// --- 값 조작 ---
function shiftAt(name, iso) {
  const value = editor.values?.[name]?.[iso];
  return value && value !== "O" ? value : "";
}

function setShift(name, date, shift) {
  if (shift === "O") {
    if (editor.values[name]) {
      delete editor.values[name][date];
      if (!Object.keys(editor.values[name]).length) delete editor.values[name];
    }
    return;
  }
  (editor.values[name] ??= {})[date] = shift;
}

function deepCopyValues(values) {
  const copy = {};
  for (const [name, days] of Object.entries(values ?? {})) {
    copy[name] = { ...days };
  }
  return copy;
}

function bannerClass(confirmed) {
  return confirmed ? "ok" : "warn";
}

function bannerText(confirmed) {
  return confirmed
    ? "입력이 확정되어 있어 근무표를 생성할 수 있습니다. 수정 후 다시 저장하면 반영됩니다."
    : "아직 확정되지 않았습니다. 저장해야 근무표를 생성할 수 있습니다 (전원 오프여도 저장하세요).";
}

function shiftButton(shift, label) {
  return `<button type="button" data-apply-shift="${shift}">${label}</button>`;
}

function dayLabel(iso) {
  const [, month, day] = iso.split("-");
  const weekday = WEEKDAY_KR[new Date(`${iso}T00:00:00`).getDay()];
  return `${Number(month)}/${Number(day)}(${weekday})`;
}

function formatDate(iso) {
  const [, month, day] = iso.split("-");
  return `${Number(month)}/${Number(day)}`;
}

function isWeekend(iso) {
  const day = new Date(`${iso}T00:00:00`).getDay();
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
