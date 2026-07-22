import { api } from "../api.js";
import { onClickBusy } from "../ui.js";

const LEVEL_LABELS = {
  senior_charge: "차지 전담",
  middle: "차지 가능",
  junior: "액팅",
  new_junior: "신규",
};

const DUTY_OPTIONS = ["D", "E", "N", "D,E", "D,N", "E,N", "D,E,N"];
const N_SOFT_OPTIONS = ["", "2", "3"];
const KIND_LABELS = { prefer: "희망", avoid: "제외" };
const OFF_SHIFTS = ["O", "연차"];

let nurses = [];
let assistants = [];
let requestSummaries = {};
let dragIndex = null;
let targetYear = null;
let targetMonth = null;

function toLocalISODate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function monthBound(which) {
  if (!targetYear || !targetMonth) return undefined;
  if (which === "first") return `${targetYear}-${String(targetMonth).padStart(2, "0")}-01`;
  // toISOString()은 UTC로 변환하므로 UTC+ 시간대(한국 등)에서는 월 마지막 날이
  // 하루 앞당겨진다. 로컬 날짜 구성요소를 직접 조합해야 한다.
  return toLocalISODate(new Date(targetYear, targetMonth, 0));
}

function shiftsToStr(shifts) {
  return [...shifts].sort().join(",");
}

function strToShifts(str) {
  return str.split(",").filter(Boolean);
}

function allowsNight(nurse) {
  return nurse.allowed_shifts.includes("N");
}

function summarize(requests) {
  const result = {};
  for (const req of requests) {
    const [, month, day] = req.date.split("-");
    const shift = OFF_SHIFTS.includes(req.requested_shift) ? "오프" : req.requested_shift;
    const text = `${Number(month)}/${Number(day)} ${shift} ${KIND_LABELS[req.kind] ?? req.kind}`;
    (result[req.nurse_name] ??= []).push({ text, ignored: req.decision === "ignore" });
  }
  return result;
}

function summaryHtml(name) {
  const items = requestSummaries[name] ?? [];
  return items
    .map((item) =>
      item.ignored
        ? `<span class="ignored">${escapeHtml(item.text)} (미반영)</span>`
        : escapeHtml(item.text)
    )
    .join(", ");
}

export async function renderRoster(container) {
  const [roster, requests, requirements] = await Promise.all([
    api.getRoster(),
    api.getRequests(),
    api.getRequirements(),
  ]);
  nurses = roster.nurses;
  assistants = roster.assistants;
  requestSummaries = summarize(requests.requests);
  targetYear = requirements.year;
  targetMonth = requirements.month;
  paint(container);
}

function paint(container) {
  container.innerHTML = `
    <header class="page-header">
      <h2>간호사 명단</h2>
      <p class="caption">행을 드래그해 표시 순서를 바꿀 수 있습니다. 이 순서는 근무표와 HWP 출력에 반영됩니다.</p>
    </header>

    <div class="roster-scroll">
      <div class="nurse-row nurse-header">
        <span></span>
        <span>이름</span>
        <span>연차 구분</span>
        <span>가능 듀티</span>
        <span>N 상한</span>
        <span>N 선호연속</span>
        <span>연차 목표</span>
        <span>평일만</span>
        <span>헬퍼</span>
        <span>신청 요약</span>
        <span></span>
      </div>
      <div id="nurse-rows"></div>
    </div>
    <button id="add-nurse-btn">+ 간호사 추가</button>

    <section class="page-section">
    <h2>보조 인력</h2>
    <div id="assistant-rows"></div>
    <button id="add-assistant-btn">+ 보조 인력 추가</button>
    </section>

    <div class="action-row">
      <button class="primary inline-primary" id="save-roster-btn">저장</button>
      <span id="roster-status" class="caption status-message"></span>
    </div>
  `;

  paintNurseRows(container);
  paintAssistantRows(container);

  container.querySelector("#add-nurse-btn").addEventListener("click", () => {
    nurses.push({
      name: "",
      level: "junior",
      allowed_shifts: ["D", "E", "N"],
      max_n_hard: 8,
      n_soft_consecutive_limit: null,
      al_target: null,
      weekday_only: false,
      is_helper: false,
      helper_shifts: {},
      helper_workdays: null,
    });
    paintNurseRows(container);
  });

  container.querySelector("#add-assistant-btn").addEventListener("click", () => {
    assistants.push({ name: "", role: "간호조무사" });
    paintAssistantRows(container);
  });

  onClickBusy(
    container.querySelector("#save-roster-btn"),
    async () => {
      const status = container.querySelector("#roster-status");
      status.textContent = "저장 중...";
      try {
        const result = await api.putRoster({ nurses, assistants });
        nurses = result.nurses;
        assistants = result.assistants;
        paintNurseRows(container);
        paintAssistantRows(container);
        status.textContent = "저장되었습니다.";
      } catch (err) {
        status.textContent = `오류: ${err.message}`;
      }
    },
    "저장 중...",
  );
}

function paintNurseRows(container) {
  const wrap = container.querySelector("#nurse-rows");
  wrap.innerHTML = "";
  nurses.forEach((nurse, index) => {
    const night = allowsNight(nurse);
    const row = document.createElement("div");
    row.className = "nurse-row";
    row.draggable = true;
    row.dataset.index = String(index);

    row.innerHTML = `
      <span class="drag-handle" title="드래그해서 순서 변경">☰</span>
      <input type="text" class="f-name" placeholder="이름" value="${escapeAttr(nurse.name)}" />
      <select class="f-level" title="연차 구분">
        ${Object.entries(LEVEL_LABELS)
          .map(
            ([value, label]) =>
              `<option value="${value}" ${nurse.level === value ? "selected" : ""}>${label}</option>`
          )
          .join("")}
      </select>
      <select class="f-shifts" title="가능 듀티">
        ${DUTY_OPTIONS.map(
          (opt) =>
            `<option value="${opt}" ${shiftsToStr(nurse.allowed_shifts) === opt ? "selected" : ""}>${opt}</option>`
        ).join("")}
      </select>
      <input type="number" class="f-ncap" title="N 상한" min="0" max="8" value="${nurse.max_n_hard ?? ""}" ${night && !nurse.is_helper ? "" : "disabled"} />
      <select class="f-nsoft" title="N 선호 연속 일수 (미입력·2·3)" ${night && !nurse.is_helper ? "" : "disabled"}>
        ${N_SOFT_OPTIONS.map((opt) => {
          const value = nurse.n_soft_consecutive_limit == null ? "" : String(nurse.n_soft_consecutive_limit);
          return `<option value="${opt}" ${value === opt ? "selected" : ""}>${opt || "미지정"}</option>`;
        }).join("")}
      </select>
      <input type="number" class="f-altarget" title="연차 목표" min="0" max="31" placeholder="-" value="${nurse.al_target ?? ""}" ${nurse.is_helper ? "disabled" : ""} />
      <label class="inline-check">
        <input type="checkbox" class="f-weekday" ${nurse.weekday_only ? "checked" : ""} ${nurse.is_helper ? "disabled" : ""} /> 평일만
      </label>
      <label class="inline-check">
        <input type="checkbox" class="f-helper" ${nurse.is_helper ? "checked" : ""} title="외부 병동 헬퍼" /> 헬퍼
      </label>
      <span class="request-summary" title="근무 신청 요약">${summaryHtml(nurse.name)}</span>
      <button class="remove-btn" title="삭제">삭제</button>
    `;

    row.querySelector(".f-name").addEventListener("input", (e) => {
      nurse.name = e.target.value;
    });
    row.querySelector(".f-level").addEventListener("change", (e) => {
      nurse.level = e.target.value;
    });
    row.querySelector(".f-shifts").addEventListener("change", (e) => {
      const next = strToShifts(e.target.value);
      const hadNight = allowsNight(nurse);
      nurse.allowed_shifts = next;
      if (!next.includes("N")) {
        nurse.max_n_hard = 0;
        nurse.n_soft_consecutive_limit = null;
      } else if (!hadNight && !nurse.max_n_hard) {
        nurse.max_n_hard = 8;
      }
      paintNurseRows(container);
    });
    row.querySelector(".f-ncap").addEventListener("input", (e) => {
      nurse.max_n_hard = e.target.value === "" ? null : Number(e.target.value);
    });
    row.querySelector(".f-nsoft").addEventListener("change", (e) => {
      nurse.n_soft_consecutive_limit = e.target.value === "" ? null : Number(e.target.value);
    });
    row.querySelector(".f-altarget").addEventListener("input", (e) => {
      nurse.al_target = e.target.value === "" ? null : Number(e.target.value);
    });
    row.querySelector(".f-weekday").addEventListener("change", (e) => {
      nurse.weekday_only = e.target.checked;
    });
    row.querySelector(".f-helper").addEventListener("change", (e) => {
      nurse.is_helper = e.target.checked;
      if (nurse.is_helper) {
        // 헬퍼는 개인 근무 목표가 없음. 기본 모드: 날짜 지정.
        nurse.weekday_only = false;
        nurse.al_target = null;
        nurse.helper_shifts = nurse.helper_shifts || {};
        nurse.helper_workdays = null;
      }
      paintNurseRows(container);
    });
    row.querySelector(".remove-btn").addEventListener("click", () => {
      nurses.splice(index, 1);
      paintNurseRows(container);
    });

    row.addEventListener("dragstart", () => {
      dragIndex = index;
      row.classList.add("dragging");
    });
    row.addEventListener("dragend", () => {
      row.classList.remove("dragging");
    });
    row.addEventListener("dragover", (e) => {
      e.preventDefault();
    });
    row.addEventListener("drop", (e) => {
      e.preventDefault();
      if (dragIndex === null || dragIndex === index) return;
      const [moved] = nurses.splice(dragIndex, 1);
      nurses.splice(index, 0, moved);
      dragIndex = null;
      paintNurseRows(container);
    });

    wrap.appendChild(row);
    if (nurse.is_helper) wrap.appendChild(helperDetail(nurse, container));
  });
}

const HELPER_DUTY_OPTIONS = ["D", "E", "N"];

function helperDetail(nurse, container) {
  const mode = nurse.helper_workdays != null ? "workdays" : "dates";
  const box = document.createElement("div");
  box.className = "helper-detail";
  box.innerHTML = `
    <div class="helper-mode">
      <strong>헬퍼 근무 방식</strong>
      <label class="inline-check"><input type="radio" name="hmode-${nurse.name}-${Math.random().toString(36).slice(2)}" class="hm-dates" ${mode === "dates" ? "checked" : ""}/> 날짜·듀티 지정</label>
      <label class="inline-check"><input type="radio" class="hm-work" ${mode === "workdays" ? "checked" : ""}/> 월 총 근무일수</label>
    </div>
    <div class="helper-body"></div>
  `;
  const modeInputs = box.querySelectorAll(".hm-dates, .hm-work");
  modeInputs[0].name = modeInputs[1].name = `hmode-${Math.random()}`;
  const body = box.querySelector(".helper-body");

  const renderBody = () => {
    if (nurse.helper_workdays != null) {
      body.innerHTML = `
        <label class="helper-work">이번 달 총 근무일수
          <input type="number" class="hw-days" min="0" max="31" value="${nurse.helper_workdays ?? ""}" style="width:5rem" />
        </label>
        <span class="caption" style="margin:0">가능 듀티(${shiftsToStr(nurse.allowed_shifts)}) 안에서 솔버가 날짜를 결정합니다.</span>
      `;
      body.querySelector(".hw-days").addEventListener("input", (e) => {
        nurse.helper_workdays = e.target.value === "" ? 0 : Number(e.target.value);
      });
    } else {
      const entries = Object.entries(nurse.helper_shifts || {}).sort();
      body.innerHTML = `
        <div class="hs-rows">
          ${entries
            .map(
              ([d, s]) => `
            <div class="hs-row" data-date="${d}">
              <input type="date" class="hs-date" value="${d}" min="${monthBound("first") ?? ""}" max="${monthBound("last") ?? ""}" />
              <select class="hs-shift">
                ${HELPER_DUTY_OPTIONS.map((o) => `<option value="${o}" ${s === o ? "selected" : ""}>${o}</option>`).join("")}
              </select>
              <button class="hs-remove remove-btn">삭제</button>
            </div>`
            )
            .join("")}
        </div>
        <button class="hs-add">+ 근무일 추가</button>
      `;
      for (const r of body.querySelectorAll(".hs-row")) {
        const oldDate = r.dataset.date;
        r.querySelector(".hs-date").addEventListener("change", (e) => {
          const shift = nurse.helper_shifts[oldDate];
          delete nurse.helper_shifts[oldDate];
          if (e.target.value) nurse.helper_shifts[e.target.value] = shift;
          renderBody();
        });
        r.querySelector(".hs-shift").addEventListener("change", (e) => {
          nurse.helper_shifts[oldDate] = e.target.value;
        });
        r.querySelector(".hs-remove").addEventListener("click", () => {
          delete nurse.helper_shifts[oldDate];
          renderBody();
        });
      }
      body.querySelector(".hs-add").addEventListener("click", () => {
        const d = monthBound("first") ?? toLocalISODate(new Date());
        let key = d;
        let i = 1;
        while (nurse.helper_shifts[key] !== undefined) {
          // 같은 날짜가 이미 있으면 다음 빈 날짜를 찾는다.
          const next = new Date(`${d}T00:00:00`);
          next.setDate(next.getDate() + i);
          key = toLocalISODate(next);
          i += 1;
        }
        nurse.helper_shifts[key] = nurse.allowed_shifts[0] ?? "D";
        renderBody();
      });
    }
  };

  box.querySelector(".hm-dates").addEventListener("change", () => {
    // 날짜 지정 모드: 총 근무일수는 비운다 (두 모드는 배타적).
    nurse.helper_workdays = null;
    nurse.helper_shifts = nurse.helper_shifts || {};
    renderBody();
  });
  box.querySelector(".hm-work").addEventListener("change", () => {
    // 총 근무일수 모드: 날짜 지정은 비운다.
    nurse.helper_workdays = nurse.helper_workdays ?? 0;
    nurse.helper_shifts = {};
    renderBody();
  });
  renderBody();
  return box;
}

function paintAssistantRows(container) {
  const wrap = container.querySelector("#assistant-rows");
  wrap.innerHTML = "";
  assistants.forEach((assistant, index) => {
    const row = document.createElement("div");
    row.className = "roster-row";
    row.innerHTML = `
      <input type="text" class="f-name" placeholder="이름" value="${escapeAttr(assistant.name)}" />
      <input type="text" class="f-role" placeholder="구분" value="${escapeAttr(assistant.role)}" style="width:8rem" />
      <span class="request-summary">${summaryHtml(assistant.name)}</span>
      <button class="remove-btn" title="삭제">삭제</button>
    `;
    row.querySelector(".f-name").addEventListener("input", (e) => {
      assistant.name = e.target.value;
    });
    row.querySelector(".f-role").addEventListener("input", (e) => {
      assistant.role = e.target.value;
    });
    row.querySelector(".remove-btn").addEventListener("click", () => {
      assistants.splice(index, 1);
      paintAssistantRows(container);
    });
    wrap.appendChild(row);
  });
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
