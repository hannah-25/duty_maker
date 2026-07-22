import { api } from "../api.js";
import { onClickBusy } from "../ui.js";

let current = null;
let settings = null;

export async function renderRequirements(container) {
  [current, settings] = await Promise.all([api.getRequirements(), api.getSettings()]);
  paint(container);
}

function paint(container) {
  container.innerHTML = `
    <header class="page-header">
      <h2>인원·규칙</h2>
      <p class="caption">근무표 생성에 쓰는 연월, 평일/주말 필요 인원·차지, 공휴일, 날짜별 예외를 관리합니다.</p>
    </header>

    <div class="requirements-grid">
      <label>
        연도
        <input type="number" id="req-year" min="2020" max="2100" value="${current.year}" />
      </label>
      <label>
        월
        <input type="number" id="req-month" min="1" max="12" value="${current.month}" />
      </label>
      <button id="reload-month-btn" style="align-self:end">연월 적용</button>
    </div>

    <div class="template-grid">
      ${templateBlock("weekday", "평일 근무", current.weekday_template)}
      ${templateBlock("weekend", "주말 근무", current.weekend_template)}
    </div>
    <p class="caption">'차지'는 그 근무의 차지 가능자 최소 인원입니다. 모든 근무엔 최소 1명이 항상 배치됩니다.</p>

    <h3>공휴일</h3>
    <div id="holiday-rows" class="check-list"></div>

    <h3>날짜별 예외</h3>
    <p class="caption">특정 날짜의 D/E/N 필요 인원이 기본 템플릿과 다를 때만 추가하세요.</p>
    <div id="override-rows"></div>
    <button id="add-override-btn">+ 예외 추가</button>

    <div class="action-row">
      <button class="primary inline-primary" id="save-requirements-btn">저장</button>
      <span id="requirements-status" class="caption status-message"></span>
    </div>
  `;

  paintHolidays(container);
  paintOverrides(container);

  onClickBusy(container.querySelector("#reload-month-btn"), async () => {
    await save(container, { silent: true });
    current = await api.getRequirements();
    paint(container);
  });

  container.querySelector("#add-override-btn").addEventListener("click", () => {
    current.date_overrides.push({ date: firstDay(), D: 0, E: 0, N: 0 });
    paintOverrides(container);
  });

  onClickBusy(container.querySelector("#save-requirements-btn"), () => save(container), "저장 중...");
}

function templateBlock(key, title, template) {
  return `
    <section class="panel">
      <h3>${title}</h3>
      <table class="compact-table">
        <thead>
          <tr><th>근무</th><th>하한</th><th>상한</th><th>목표</th></tr>
        </thead>
        <tbody>
          ${["D", "E", "N"].map((shift) => requirementRow(key, shift, template[shift])).join("")}
        </tbody>
      </table>
      <div class="charge-row">
        <span>차지 최소</span>
        ${["D", "E", "N"]
          .map(
            (shift) => `
          <label>${shift}
            <input type="number" min="0" max="5" data-charge="${key}_charge_${shift}" value="${settings[`${key}_charge_${shift}`] ?? 0}" />
          </label>`
          )
          .join("")}
      </div>
    </section>
  `;
}

function requirementRow(key, shift, req) {
  return `
    <tr>
      <th>${shift}</th>
      <td><input type="number" min="0" data-template="${key}" data-shift="${shift}" data-field="minimum" value="${req.minimum}" /></td>
      <td><input type="number" min="0" data-template="${key}" data-shift="${shift}" data-field="maximum" value="${req.maximum}" /></td>
      <td><input type="number" min="0" data-template="${key}" data-shift="${shift}" data-field="target" value="${req.target}" /></td>
    </tr>
  `;
}

function paintHolidays(container) {
  const wrap = container.querySelector("#holiday-rows");
  wrap.innerHTML = "";
  for (const holiday of current.holidays) {
    const label = document.createElement("label");
    label.className = "inline-check";
    label.innerHTML = `
      <input type="checkbox" value="${holiday.date}" ${holiday.selected ? "checked" : ""} />
      ${holiday.date} ${holiday.title}
    `;
    wrap.appendChild(label);
  }
}

function paintOverrides(container) {
  const wrap = container.querySelector("#override-rows");
  wrap.innerHTML = "";
  current.date_overrides.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "roster-row";
    row.innerHTML = `
      <input type="date" class="f-date" value="${item.date}" min="${firstDay()}" max="${lastDay()}" />
      <input type="number" class="f-D" min="0" value="${item.D}" style="width:5rem" />
      <input type="number" class="f-E" min="0" value="${item.E}" style="width:5rem" />
      <input type="number" class="f-N" min="0" value="${item.N}" style="width:5rem" />
      <button class="remove-btn">삭제</button>
    `;
    row.querySelector(".f-date").addEventListener("input", (e) => {
      item.date = e.target.value;
    });
    row.querySelector(".f-D").addEventListener("input", (e) => {
      item.D = Number(e.target.value);
    });
    row.querySelector(".f-E").addEventListener("input", (e) => {
      item.E = Number(e.target.value);
    });
    row.querySelector(".f-N").addEventListener("input", (e) => {
      item.N = Number(e.target.value);
    });
    row.querySelector(".remove-btn").addEventListener("click", () => {
      current.date_overrides.splice(index, 1);
      paintOverrides(container);
    });
    wrap.appendChild(row);
  });
}

async function save(container, { silent = false } = {}) {
  const status = container.querySelector("#requirements-status");
  if (status && !silent) status.textContent = "저장 중...";
  try {
    const previousMonthKey = `${current.year}-${current.month}`;
    collect(container);
    const nextMonthKey = `${current.year}-${current.month}`;
    if (previousMonthKey !== nextMonthKey) {
      current.selected_holidays = [];
      current.date_overrides = [];
    }
    // Both endpoints persist the ward's full state. Save sequentially so the
    // settings request cannot overwrite the just-saved holiday selection.
    current = await api.putRequirements({
      year: current.year,
      month: current.month,
      weekday_template: current.weekday_template,
      weekend_template: current.weekend_template,
      selected_holidays: current.selected_holidays,
      date_overrides: current.date_overrides,
    });
    settings = await api.putSettings(settings);
    if (status && !silent) status.textContent = "저장되었습니다.";
  } catch (err) {
    if (status) status.textContent = `오류: ${err.message}`;
    if (silent) throw err;
  }
}

function collect(container) {
  current.year = Number(container.querySelector("#req-year").value);
  current.month = Number(container.querySelector("#req-month").value);
  for (const input of container.querySelectorAll("[data-template]")) {
    const target = input.dataset.template === "weekday" ? current.weekday_template : current.weekend_template;
    target[input.dataset.shift][input.dataset.field] = Number(input.value);
  }
  current.selected_holidays = [...container.querySelectorAll("#holiday-rows input:checked")].map(
    (input) => input.value
  );
  // 근무별 차지 최소 인원(병동 규칙)도 함께 수집.
  const next = { ...settings };
  for (const input of container.querySelectorAll("[data-charge]")) {
    next[input.dataset.charge] = Number(input.value);
  }
  settings = next;
}

function firstDay() {
  return `${current.year}-${String(current.month).padStart(2, "0")}-01`;
}

function lastDay() {
  // toISOString()은 UTC로 변환하므로 UTC+ 시간대(한국 등)에서는 월 마지막 날이
  // 하루 앞당겨진다. 로컬 날짜 구성요소를 직접 조합해야 한다.
  const d = new Date(current.year, current.month, 0);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
