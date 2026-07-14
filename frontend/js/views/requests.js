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
};

const DECISION_LABELS = {
  force: "반영",
  ignore: "미반영",
};

let current = null;

export async function renderRequests(container) {
  current = await api.getRequests();
  paint(container);
}

function paint(container) {
  container.innerHTML = `
    <h2 style="font-size:1.15rem">근무 신청</h2>
    <p class="caption">${current.year}년 ${current.month}월 신청을 관리합니다.</p>

    ${current.is_admin ? adminLockBlock() : lockNotice()}

    <div class="request-form">
      ${current.is_admin ? nameSelect() : ""}
      <label>
        날짜
        <input type="date" id="request-date" min="${firstDay()}" max="${lastDay()}" value="${firstDay()}" ${current.locked && !current.is_admin ? "disabled" : ""} />
      </label>
      <label>
        유형
        <select id="request-kind" ${current.locked && !current.is_admin ? "disabled" : ""}>
          <option value="prefer">희망</option>
          <option value="avoid">제외</option>
        </select>
      </label>
      <label>
        근무
        <select id="request-shift" ${current.locked && !current.is_admin ? "disabled" : ""}>
          <option value="O">오프</option>
          <option value="D">D</option>
          <option value="E">E</option>
          <option value="N">N</option>
        </select>
      </label>
      <label>
        메모
        <input type="text" id="request-memo" placeholder="선택 입력" ${current.locked && !current.is_admin ? "disabled" : ""} />
      </label>
      <button id="add-request-btn" class="primary inline-primary" ${current.locked && !current.is_admin ? "disabled" : ""}>추가</button>
    </div>

    <div id="requests-status" class="caption"></div>
    <div id="request-rows"></div>
  `;

  if (current.is_admin) {
    container.querySelector("#request-lock").addEventListener("change", async (e) => {
      current = await api.setRequestLock({ locked: e.target.checked });
      paint(container);
    });
  }

  container.querySelector("#add-request-btn").addEventListener("click", () => addRequest(container));
  paintRows(container);
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
    <label>
      이름
      <select id="request-name">
        ${current.names.map((name) => `<option value="${escapeAttr(name)}">${escapeHtml(name)}</option>`).join("")}
      </select>
    </label>
  `;
}

async function addRequest(container) {
  const status = container.querySelector("#requests-status");
  status.textContent = "추가 중...";
  try {
    const body = {
      nurse_name: current.is_admin ? container.querySelector("#request-name").value : null,
      date: container.querySelector("#request-date").value,
      kind: container.querySelector("#request-kind").value,
      requested_shift: container.querySelector("#request-shift").value,
      memo: container.querySelector("#request-memo").value.trim(),
    };
    current = await api.addRequest(body);
    paint(container);
  } catch (err) {
    status.textContent = `오류: ${err.message}`;
  }
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
      <td>${KIND_LABELS[item.kind] ?? item.kind}</td>
      <td>${SHIFT_LABELS[item.requested_shift] ?? item.requested_shift}</td>
      <td>${escapeHtml(item.memo)}</td>
      <td>${decisionCell(item)}</td>
      <td><button class="remove-btn" data-delete="${item.id}" ${current.locked && !current.is_admin ? "disabled" : ""}>삭제</button></td>
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

function firstDay() {
  return `${current.year}-${String(current.month).padStart(2, "0")}-01`;
}

function lastDay() {
  return new Date(current.year, current.month, 0).toISOString().slice(0, 10);
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
