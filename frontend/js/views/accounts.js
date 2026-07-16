import { api } from "../api.js";

let current = null;

export async function renderAccounts(container) {
  current = await api.getAccounts();
  paint(container);
}

function paint(container) {
  container.innerHTML = `
    <h2 style="font-size:1.15rem">계정 관리</h2>
    <p class="caption">PIN 초기화 시 해당 계정의 PIN이 <strong>1234</strong>로 바뀝니다. 사용자는 1234로 로그인한 뒤 본인 PIN을 변경해야 합니다.</p>
    ${unregisteredBlock()}
    <div id="accounts-status" class="caption"></div>
    <div id="account-rows"></div>
  `;
  paintRows(container);
}

function unregisteredBlock() {
  if (!current.unregistered_names.length) return "";
  return `
    <div class="panel" style="margin-bottom:1rem">
      <h3>계정 미등록</h3>
      <p class="caption" style="margin:0">${current.unregistered_names.map(escapeHtml).join(", ")}</p>
    </div>
  `;
}

function paintRows(container) {
  const wrap = container.querySelector("#account-rows");
  if (!current.accounts.length) {
    wrap.innerHTML = `<p class="caption">등록된 계정이 없습니다.</p>`;
    return;
  }
  wrap.innerHTML = `
    <table class="compact-table account-table">
      <thead>
        <tr><th>이름</th><th>상태</th><th>관리자</th><th></th></tr>
      </thead>
      <tbody>
        ${current.accounts
          .map(
            (account) => `
              <tr>
                <td>${escapeHtml(account.name)}${account.is_current ? " (본인)" : ""}</td>
                <td>${account.in_roster ? "명단 있음" : "명단 없음"}</td>
                <td>
                  <label class="inline-check">
                    <input type="checkbox" data-admin="${escapeAttr(account.name)}" ${account.is_admin ? "checked" : ""} ${account.is_current ? "disabled" : ""} />
                    관리자
                  </label>
                </td>
                <td>
                  <button data-reset="${escapeAttr(account.name)}" ${account.is_current ? "disabled" : ""}>PIN 초기화</button>
                </td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
  `;

  for (const input of wrap.querySelectorAll("[data-admin]")) {
    input.addEventListener("change", async (e) => {
      await update(container, () => api.updateAccount(e.target.dataset.admin, { is_admin: e.target.checked }));
    });
  }
  for (const button of wrap.querySelectorAll("[data-reset]")) {
    button.addEventListener("click", async () => {
      const name = button.dataset.reset;
      if (!confirm(`${name} 님의 PIN을 1234로 초기화할까요?`)) return;
      await update(container, () => api.resetPin(name));
    });
  }
}

async function update(container, action) {
  const status = container.querySelector("#accounts-status");
  status.textContent = "저장 중...";
  try {
    current = await action();
    paint(container);
  } catch (err) {
    status.textContent = `오류: ${err.message}`;
  }
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
