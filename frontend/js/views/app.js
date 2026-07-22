import { api } from "../api.js";
import { state, resetAuth, resetWard } from "../state.js";
import { navigateTo, wardSelectPath } from "../router.js";
import { onClickBusy } from "../ui.js";
import { renderAccounts } from "./accounts.js";
import { renderAdminGuide } from "./admin-guide.js";
import { renderPrevMonth } from "./prev-month.js";
import { renderRequirements } from "./requirements.js";
import { renderRequests } from "./requests.js";
import { renderRoster } from "./roster.js";
import { renderScheduleResult } from "./schedule-result.js";

const ADMIN_TABS = [
  { key: "roster", label: "명단", render: renderRoster },
  { key: "requirements", label: "인원·규칙", render: renderRequirements },
  { key: "requests", label: "근무 신청", render: renderRequests },
  { key: "prev-month", label: "직전 달", render: renderPrevMonth },
  { key: "result", label: "결과", render: renderScheduleResult },
  { key: "accounts", label: "계정", render: renderAccounts },
];

const MEMBER_TABS = [
  { key: "requests", label: "근무 신청", render: renderRequests },
  { key: "result", label: "근무표", render: renderScheduleResult },
];

let activeTab = null;
let renderToken = 0;

export function renderApp(root, navigate) {
  const tabs = state.isAdmin ? ADMIN_TABS : MEMBER_TABS;
  if (!activeTab || !tabs.some((tab) => tab.key === activeTab)) {
    activeTab = tabs[0].key;
  }

  root.innerHTML = `
    <header class="app-header">
      <div class="app-header-title">
        <img class="brand-mark" src="assets/mascot-avatar.png" alt="" width="128" height="128" />
        <div class="app-header-titles">
          <h1>Duty Maker</h1>
          <span class="caption">${escapeHtml(state.wardLabel)}</span>
        </div>
      </div>
      <div class="app-header-user">
        <span class="user-badge">
          <strong>${escapeHtml(state.name)}</strong>
          <span>${state.isAdmin ? "관리자" : "사용자"}</span>
        </span>
        ${state.isAdmin ? `<button id="help-btn" aria-label="사용법" title="사용법">?</button>` : ""}
        <button id="change-pin-btn">PIN 변경</button>
        <button id="logout-btn">로그아웃</button>
        <button id="switch-ward-btn">병동 전환</button>
      </div>
    </header>
    <div id="change-pin-panel" class="card" style="display:none;margin-bottom:1rem">
      <label for="cp-current">현재 PIN</label>
      <input type="password" id="cp-current" autocomplete="off" />
      <label for="cp-new">새 PIN (4~6자리 숫자)</label>
      <input type="password" id="cp-new" autocomplete="off" />
      <label for="cp-new2">새 PIN 확인</label>
      <input type="password" id="cp-new2" autocomplete="off" />
      <button class="primary" id="cp-submit">변경</button>
      <button id="cp-cancel" style="margin-top:0.6rem">취소</button>
      <div id="cp-msg"></div>
    </div>
    ${state.isAdmin ? helpModalMarkup() : ""}
    <div class="tab-bar" id="tab-bar"></div>
    <div id="tab-content"></div>
  `;

  root.querySelector("#logout-btn").addEventListener("click", () => {
    resetAuth();
    navigate();
  });
  root.querySelector("#switch-ward-btn").addEventListener("click", () => {
    resetWard();
    navigateTo(wardSelectPath());
  });
  wireChangePin(root);
  if (state.isAdmin) wireHelpModal(root);

  const tabBar = root.querySelector("#tab-bar");
  const content = root.querySelector("#tab-content");

  // 각 렌더는 분리된 pane에 그린 뒤 최신 것만 붙인다. 느리게 도착한 이전 탭의
  // 렌더가 새 탭 내용을 덮어쓰지 않도록.
  async function renderActiveTab() {
    const tab = tabs.find((item) => item.key === activeTab);
    const token = ++renderToken;
    content.innerHTML = "";
    const pane = document.createElement("div");
    try {
      await tab.render(pane);
    } catch (err) {
      pane.innerHTML = `<div class="error-banner">${tab.label} 화면을 불러오지 못했습니다: ${escapeHtml(err.message)}</div>`;
    }
    if (token !== renderToken) return;
    content.replaceChildren(pane);
  }

  for (const tab of tabs) {
    const btn = document.createElement("button");
    btn.textContent = tab.label;
    btn.className = tab.key === activeTab ? "active" : "";
    btn.addEventListener("click", () => {
      activeTab = tab.key;
      for (const button of tabBar.querySelectorAll("button")) button.classList.remove("active");
      btn.classList.add("active");
      renderActiveTab();
    });
    tabBar.appendChild(btn);
  }

  renderActiveTab();
}

function helpModalMarkup() {
  return `
    <div class="help-modal" id="help-modal" aria-hidden="true">
      <button class="help-modal-backdrop" type="button" data-help-close aria-label="닫기"></button>
      <section class="help-modal-panel" role="dialog" aria-modal="true" aria-labelledby="help-modal-title">
        <div class="help-modal-heading">
          <strong id="help-modal-title">사용법</strong>
          <button type="button" data-help-close aria-label="닫기">×</button>
        </div>
        <div id="help-modal-content" class="help-modal-body"></div>
      </section>
    </div>
  `;
}

function wireHelpModal(root) {
  const modal = root.querySelector("#help-modal");
  const helpBtn = root.querySelector("#help-btn");
  if (!modal || !helpBtn) return;
  let contentRendered = false;

  const close = () => {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    helpBtn.focus();
  };
  const open = () => {
    if (!contentRendered) {
      renderAdminGuide(modal.querySelector("#help-modal-content"));
      contentRendered = true;
    }
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    modal.querySelector("[data-help-close]")?.focus();
  };

  helpBtn.addEventListener("click", open);
  for (const btn of modal.querySelectorAll("[data-help-close]")) {
    btn.addEventListener("click", close);
  }
  modal.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
  });
}

function wireChangePin(root) {
  const btn = root.querySelector("#change-pin-btn");
  const panel = root.querySelector("#change-pin-panel");
  const current = panel.querySelector("#cp-current");
  const next = panel.querySelector("#cp-new");
  const next2 = panel.querySelector("#cp-new2");
  const msg = panel.querySelector("#cp-msg");

  const setMsg = (text, isError) => {
    msg.innerHTML = text ? `<div class="${isError ? "error-banner" : "caption"}">${escapeHtml(text)}</div>` : "";
  };
  const reset = () => {
    current.value = next.value = next2.value = "";
    setMsg("");
  };

  btn.addEventListener("click", () => {
    const opening = panel.style.display === "none";
    panel.style.display = opening ? "" : "none";
    if (opening) {
      reset();
      current.focus();
    }
  });
  panel.querySelector("#cp-cancel").addEventListener("click", () => {
    panel.style.display = "none";
    reset();
  });
  onClickBusy(panel.querySelector("#cp-submit"), async () => {
    setMsg("");
    if (next.value !== next2.value) {
      setMsg("새 PIN 확인이 일치하지 않습니다.", true);
      return;
    }
    try {
      await api.changePin({ current_pin: current.value, new_pin: next.value });
      current.value = next.value = next2.value = "";
      setMsg("PIN이 변경되었습니다.", false);
    } catch (err) {
      setMsg(err.message, true);
    }
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
