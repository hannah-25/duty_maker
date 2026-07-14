import { api } from "../api.js";
import { state, resetWard } from "../state.js";

export function renderLogin(root, navigate) {
  root.innerHTML = `
    <h1>Duty Maker</h1>
    <p class="caption">${state.wardLabel}</p>
    <p class="caption">이름과 PIN으로 로그인하세요. 새로고침하면 다시 로그인해야 합니다.</p>
    <div class="tab-bar">
      <button class="active" data-tab="login">로그인</button>
      <button data-tab="register">PIN 등록</button>
    </div>
    <div class="card" id="login-panel">
      <label for="login-name">이름</label>
      <input type="text" id="login-name" />
      <label for="login-pin">PIN (4~6자리 숫자)</label>
      <input type="password" id="login-pin" />
      <button class="primary" id="login-btn">로그인</button>
      <div id="login-error"></div>
    </div>
    <div class="card" id="register-panel" style="display:none">
      <label for="reg-name">이름</label>
      <input type="text" id="reg-name" />
      <label for="reg-pin">PIN (4~6자리 숫자)</label>
      <input type="password" id="reg-pin" />
      <label for="reg-pin2">PIN 확인</label>
      <input type="password" id="reg-pin2" />
      <button class="primary" id="register-btn">등록</button>
      <div id="register-error"></div>
    </div>
    <button id="back-btn" style="margin-top:1.4rem">다른 병동으로</button>
  `;

  const loginPanel = root.querySelector("#login-panel");
  const registerPanel = root.querySelector("#register-panel");
  for (const btn of root.querySelectorAll(".tab-bar button")) {
    btn.addEventListener("click", () => {
      for (const button of root.querySelectorAll(".tab-bar button")) button.classList.remove("active");
      btn.classList.add("active");
      const isLogin = btn.dataset.tab === "login";
      loginPanel.style.display = isLogin ? "" : "none";
      registerPanel.style.display = isLogin ? "none" : "";
    });
  }

  root.querySelector("#login-btn").addEventListener("click", async () => {
    const errorBox = root.querySelector("#login-error");
    errorBox.innerHTML = "";
    const name = root.querySelector("#login-name").value.trim();
    const pin = root.querySelector("#login-pin").value;
    try {
      const result = await api.login({ ward_id: state.wardId, name, pin });
      state.token = result.token;
      state.name = result.name;
      state.isAdmin = result.is_admin;
      navigate();
    } catch (err) {
      errorBox.innerHTML = `<div class="error-banner">${err.message}</div>`;
    }
  });

  root.querySelector("#register-btn").addEventListener("click", async () => {
    const errorBox = root.querySelector("#register-error");
    errorBox.innerHTML = "";
    const name = root.querySelector("#reg-name").value.trim();
    const pin = root.querySelector("#reg-pin").value;
    const pin2 = root.querySelector("#reg-pin2").value;
    if (pin !== pin2) {
      errorBox.innerHTML = `<div class="error-banner">PIN 확인이 일치하지 않습니다.</div>`;
      return;
    }
    try {
      const result = await api.register({ ward_id: state.wardId, name, pin });
      state.token = result.token;
      state.name = result.name;
      state.isAdmin = result.is_admin;
      navigate();
    } catch (err) {
      errorBox.innerHTML = `<div class="error-banner">${err.message}</div>`;
    }
  });

  root.querySelector("#back-btn").addEventListener("click", () => {
    resetWard();
    navigate();
  });
}
