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

    <section class="panel">
      <h3>보조근무</h3>
      <label class="inline-check">
        <input type="checkbox" id="use-s-shift" ${settings.use_s_shift !== false ? "checked" : ""} />
        S 근무 사용
      </label>
      <p class="caption">끄면 S는 배정되지 않습니다. 켜면 S는 저연차 간호사에게만 배정되고 D 인원에 포함됩니다.</p>
    </section>

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

    <details class="constraint-guide panel">
      <summary>
        <span>
          <strong>제약조건 안내</strong>
          <small>하드는 반드시, 소프트는 가능한 한 지킵니다.</small>
        </span>
      </summary>
      <div class="constraint-guide-content">
        <p>하드 제약을 하나라도 만족할 수 없으면 근무표 생성이 실패합니다. 소프트 제약은 벌점이 낮아지도록 조정하며, 하드 제약을 대신할 수 없습니다.</p>
        <div class="constraint-guide-grid">
          <section>
            <h3>하드 제약 · 반드시 지킴</h3>
            <ul>
              <li>하루 D/E/N/S/O/연차 중 하나만 배정</li>
              <li>일별 D·E·N 인원 하한·상한과 근무별 차지 최소 인원 충족</li>
              <li>나이트 종료 뒤 2일 휴식, 연속 근무 최대 5일, 연속 나이트 최대 3일</li>
              <li>이브닝 다음 날 D·S 배정 금지</li>
              <li>개인별 가능 듀티·나이트 월 상한·오프/연차 목표 준수</li>
              <li>S는 사용 설정 시에만, 저연차·신규 저연차에게만 배정</li>
              <li>평일 전담자의 주말 휴식, 헬퍼·나이트 전담의 별도 근무 규칙 적용</li>
              <li>강제반영 신청과 부분 재생성에서 고정한 배정 준수</li>
            </ul>
          </section>
          <section>
            <h3>소프트 제약 · 가능한 한 지킴</h3>
            <ul>
              <li>목표 인원 충족(월요일 우선), 단독 나이트와 휴식 뒤 재나이트 회피</li>
              <li>하루 S 1명 이하 및 S 사용 최소화</li>
              <li>시니어 이브닝·신규 저연차 동시 근무 쏠림 완화</li>
              <li>5일 연속 근무, 4일 연속 휴식, 휴식 사이 단독 근무 회피</li>
              <li>통주말 휴식 월 1회 이상(가능하면 2회) 확보</li>
              <li>제외 희망 근무, 연차 과다 사용·편중 최소화</li>
              <li>일반 희망·제외 신청은 높은 우선순위의 소프트 제약</li>
            </ul>
          </section>
        </div>
      </div>
    </details>
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
  next.use_s_shift = container.querySelector("#use-s-shift").checked;
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
