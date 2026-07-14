import { state, resetAuth, resetWard } from "../state.js";
import { renderAccounts } from "./accounts.js";
import { renderRequirements } from "./requirements.js";
import { renderRequests } from "./requests.js";
import { renderRoster } from "./roster.js";
import { renderScheduleResult } from "./schedule-result.js";

const ADMIN_TABS = [
  { key: "roster", label: "명단", render: renderRoster },
  { key: "requirements", label: "인원·규칙", render: renderRequirements },
  { key: "requests", label: "근무 신청", render: renderRequests },
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
    <div class="sidebar-user">
      <strong>${state.name} (${state.isAdmin ? "관리자" : "사용자"})</strong>
      <span class="caption" style="margin:0">${state.wardLabel}</span>
      <button id="logout-btn">로그아웃</button>
      <button id="switch-ward-btn">다른 병동으로 전환</button>
    </div>
    <h1>Duty Maker</h1>
    <div class="tab-bar" id="tab-bar"></div>
    <div id="tab-content"></div>
  `;

  root.querySelector("#logout-btn").addEventListener("click", () => {
    resetAuth();
    navigate();
  });
  root.querySelector("#switch-ward-btn").addEventListener("click", () => {
    resetWard();
    navigate();
  });

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

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
