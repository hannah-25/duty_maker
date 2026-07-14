import { api } from "../api.js";

let current = null;
let settings = null;

export async function renderRequirements(container) {
  [current, settings] = await Promise.all([api.getRequirements(), api.getSettings()]);
  paint(container);
}

function paint(container) {
  container.innerHTML = `
    <h2 style="font-size:1.15rem">인원·규칙</h2>
    <p class="caption">근무표 생성에 쓰는 인원 기준과 이 병동의 근무 규칙을 함께 관리합니다.</p>

    <div class="reqrules-layout">
      <div class="rr-col">
        <h3 class="rr-heading">인원 기준</h3>
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
          ${templateBlock("weekday", "평일", current.weekday_template)}
          ${templateBlock("weekend", "주말", current.weekend_template)}
        </div>

        <h3>공휴일</h3>
        <div id="holiday-rows" class="check-list"></div>

        <h3>날짜별 예외</h3>
        <p class="caption">특정 날짜의 D/E/N 필요 인원이 기본 템플릿과 다를 때만 추가하세요.</p>
        <div id="override-rows"></div>
        <button id="add-override-btn">+ 예외 추가</button>
      </div>

      <div class="rr-col">
        <h3 class="rr-heading">병동 규칙</h3>
        ${settingsBlock()}
      </div>
    </div>

    <div style="margin-top:1.4rem">
      <button class="primary inline-primary" id="save-requirements-btn">저장</button>
      <span id="requirements-status" class="caption" style="margin:0 0 0 0.8rem"></span>
    </div>
  `;

  paintHolidays(container);
  paintOverrides(container);

  container.querySelector("#reload-month-btn").addEventListener("click", async () => {
    const year = Number(container.querySelector("#req-year").value);
    const month = Number(container.querySelector("#req-month").value);
    current.year = year;
    current.month = month;
    current.selected_holidays = [];
    current.date_overrides = [];
    await save(container, { silent: true });
    current = await api.getRequirements();
    paint(container);
  });

  container.querySelector("#add-override-btn").addEventListener("click", () => {
    current.date_overrides.push({ date: firstDay(), D: 0, E: 0, N: 0 });
    paintOverrides(container);
  });

  container.querySelector("#save-requirements-btn").addEventListener("click", () => save(container));
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

function settingsBlock() {
  return `
    <section class="panel">
      <h4>나이트 시니어 배치</h4>
      <label class="inline-check">
        <input type="checkbox" id="s-senior-night" ${settings.senior_night_exactly_one ? "checked" : ""} />
        나이트에 책임급을 <strong>정확히 1명</strong> 배치
      </label>
      <p class="caption" style="margin:0.5rem 0 0">나이트 전담이 전부 책임급인 병동은 끄세요.</p>
    </section>

    <section class="panel">
      <h4>평일 데이 차지 최소 인원</h4>
      <div class="settings-inline">
        <label>평일 D 차지 <input type="number" id="s-charge" min="0" max="5" value="${settings.weekday_day_charge_min}" />명 이상</label>
      </div>
      <p class="caption" style="margin:0.5rem 0 0">0이면 미적용(주말 D 차지 1명은 항상 보장).</p>
    </section>

    <p class="caption">월 나이트 개수는 명단의 개인 N상한으로 제한됩니다. 나이트 전담(N만 가능)은 개인 N상한만큼 나이트를 서고 나머지 날은 오프가 됩니다.</p>
  `;
}

async function save(container, { silent = false } = {}) {
  const status = container.querySelector("#requirements-status");
  if (status && !silent) status.textContent = "저장 중...";
  try {
    collect(container);
    [current, settings] = await Promise.all([
      api.putRequirements({
        year: current.year,
        month: current.month,
        weekday_template: current.weekday_template,
        weekend_template: current.weekend_template,
        selected_holidays: current.selected_holidays,
        date_overrides: current.date_overrides,
      }),
      api.putSettings(settings),
    ]);
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
  // 병동 규칙도 함께 수집.
  const seniorNight = container.querySelector("#s-senior-night");
  if (seniorNight) {
    settings = {
      senior_night_exactly_one: seniorNight.checked,
      weekday_day_charge_min: Number(container.querySelector("#s-charge").value),
    };
  }
}

function firstDay() {
  return `${current.year}-${String(current.month).padStart(2, "0")}-01`;
}

function lastDay() {
  return new Date(current.year, current.month, 0).toISOString().slice(0, 10);
}
