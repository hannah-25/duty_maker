import { api } from "../api.js";
import { state } from "../state.js";

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

let current = null;
let viewMode = "grid"; // "grid" | "calendar" — 세션 동안만 유지

export async function renderScheduleResult(container) {
  current = await api.getSchedule();
  paint(container);
}

function paint(container) {
  container.innerHTML = `
    <h2 style="font-size:1.15rem">${state.isAdmin ? "생성 결과" : "근무표"}</h2>
    <p class="caption">${current.year}년 ${current.month}월 근무표</p>
    ${adminControls()}
    ${downloadControls()}
    <div id="schedule-status"></div>
    <div id="schedule-body"></div>
  `;

  if (state.isAdmin) {
    container.querySelector("#generate-schedule-btn").addEventListener("click", async () => {
      const status = container.querySelector("#schedule-status");
      status.innerHTML = `<p class="caption">근무표 생성 중...</p>`;
      try {
        current = await api.generateSchedule();
        paint(container);
      } catch (err) {
        status.innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
      }
    });
    const publishToggle = container.querySelector("#publish-toggle");
    if (publishToggle) {
      publishToggle.addEventListener("change", async (e) => {
        current = await api.publishSchedule({ published: e.target.checked });
        paint(container);
      });
    }
  }
  for (const button of container.querySelectorAll("[data-download]")) {
    button.addEventListener("click", async () => {
      const status = container.querySelector("#schedule-status");
      status.innerHTML = "";
      try {
        if (button.dataset.download === "hwpx") await api.downloadHwpx();
        if (button.dataset.download === "xlsx") await api.downloadXlsx();
      } catch (err) {
        status.innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
      }
    });
  }

  paintSchedule(container);
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
  return `
    <div class="result-controls">
      <button data-download="hwpx">HWPX 다운로드</button>
      <button data-download="xlsx">XLSX 다운로드</button>
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

function paintSchedule(container) {
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
    <div class="view-toggle">
      <button data-view="grid" class="${viewMode === "grid" ? "active" : ""}">표 보기</button>
      <button data-view="calendar" class="${viewMode === "calendar" ? "active" : ""}">달력 보기</button>
    </div>
    <div id="schedule-view"></div>
    <p class="caption">파란 글자는 반영된 듀티 신청, ★는 차지, 회색은 주말·공휴일입니다.</p>
    ${checklistBlock()}
    ${violationsBlock()}
  `;

  const view = body.querySelector("#schedule-view");
  const renderView = () => {
    view.innerHTML = viewMode === "calendar" ? calendarViewHTML(ctx) : gridViewHTML(ctx);
  };
  for (const btn of body.querySelectorAll(".view-toggle button")) {
    btn.addEventListener("click", () => {
      if (viewMode === btn.dataset.view) return;
      viewMode = btn.dataset.view;
      for (const b of body.querySelectorAll(".view-toggle button")) b.classList.remove("active");
      btn.classList.add("active");
      renderView();
    });
  }
  renderView();
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
  const nurseRows = names.map((name) =>
    tableRow(name, dates, holidays, highlights, charges, helpers, (date) => byNurse.get(name)?.get(date), true)
  );
  const assistantRows = current.assistant_rows.map((row) =>
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
          <tr>
            <th>이름</th>
            ${dates
              .map(
                (date) =>
                  `<th class="${isHoliday(date, holidays) ? "col-holiday" : ""}">${dayLabel(date)}</th>`
              )
              .join("")}
            ${STAT_COLUMNS.map((label) => `<th class="stat-col">${label}</th>`).join("")}
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
  // 날짜 열 × 근무 그룹(day/eve/night/S) 행. 각 칸에 명단 순서로 이름 나열, 차지는 ★.
  const cellNames = (date, shift) =>
    names
      .filter((name) => byNurse.get(name)?.get(date) === shift)
      .map((name) => {
        const star = charges.has(`${name}|${date}`) ? '<span class="charge-star">★</span>' : "";
        const tag = helpers.has(name) ? '<span class="helper-tag">헬퍼</span>' : "";
        return `<div class="cal-name">${escapeHtml(name)}${star}${tag}</div>`;
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
          <tr>
            <th></th>
            ${dates
              .map(
                (date) =>
                  `<th class="${isHoliday(date, holidays) ? "col-holiday" : ""}">${dayLabel(date)}</th>`
              )
              .join("")}
          </tr>
        </thead>
        <tbody>${groupRows}</tbody>
      </table>
    </div>
  `;
}

function tableRow(name, dates, holidays, highlights, charges, helpers, shiftAt, showCounts) {
  const isHelper = helpers.has(name);
  const counts = { D: 0, E: 0, N: 0, O: 0, 연차: 0 };
  const cells = dates
    .map((date) => {
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
      return `<td class="${classes.join(" ")}">${escapeHtml(shift)}</td>`;
    })
    .join("");
  const statCells = STAT_COLUMNS.map(
    (key) => `<td class="stat-col">${showCounts ? counts[key] || "" : ""}</td>`
  ).join("");
  const label = escapeHtml(name) + (isHelper ? '<span class="helper-tag">헬퍼</span>' : "");
  return `<tr><th>${label}</th>${cells}${statCells}</tr>`;
}

function dayLabel(date) {
  const [, month, day] = date.split("-");
  const weekday = WEEKDAY_KR[new Date(`${date}T00:00:00`).getDay()];
  return `${Number(month)}/${Number(day)}(${weekday})`;
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
