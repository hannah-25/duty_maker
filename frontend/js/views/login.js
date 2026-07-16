import { api } from "../api.js";
import { applyAuth, state, resetWard } from "../state.js";
import { navigateTo, wardSelectPath } from "../router.js";
import { onClickBusy, withBusy } from "../ui.js";

export function renderLogin(root, navigate) {
  root.innerHTML = `
    <h1>Duty Maker</h1>
    <p class="caption">${escapeHtml(state.wardLabel)}</p>
    <div class="card" id="auth-card"></div>
    <button id="back-btn" style="margin-top:1.4rem">다른 병동으로</button>
  `;

  const card = root.querySelector("#auth-card");
  root.querySelector("#back-btn").addEventListener("click", () => {
    resetWard();
    navigateTo(wardSelectPath());
  });

  // 1단계: 이름 입력 → 계정/명단 조회 후 로그인 또는 PIN 등록으로 분기
  function renderNameStep(prefillName = "", errorMsg = "") {
    card.innerHTML = `
      <label for="login-name">이름</label>
      <input type="text" id="login-name" autocomplete="off" />
      <button class="primary" id="next-btn">다음</button>
      <div id="auth-error"></div>
    `;
    const nameInput = card.querySelector("#login-name");
    nameInput.value = prefillName;
    if (errorMsg) showError(errorMsg);
    nameInput.focus();

    const nextBtn = card.querySelector("#next-btn");
    const submit = async () => {
      showError("");
      const name = nameInput.value.trim();
      if (!name) {
        showError("이름을 입력하세요.");
        return;
      }
      try {
        const result = await api.lookup({ ward_id: state.wardId, name });
        if (result.registered) {
          renderPinStep(name);
        } else if (result.in_roster) {
          renderRegisterStep(name);
        } else {
          showError("명단에 없는 이름입니다. 관리자에게 문의하세요.");
        }
      } catch (err) {
        showError(err.message);
      }
    };

    onClickBusy(nextBtn, submit);
    nameInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") withBusy(nextBtn, submit);
    });
  }

  // 2단계-A: 이미 등록된 계정 → PIN 입력 후 로그인
  function renderPinStep(name) {
    card.innerHTML = `
      <p class="caption" style="margin-top:0"><strong>${escapeHtml(name)}</strong> 님, PIN을 입력하세요.</p>
      <label for="login-pin">PIN</label>
      <input type="password" id="login-pin" autocomplete="off" />
      <button class="primary" id="login-btn">로그인</button>
      <button id="change-name-btn" style="margin-top:0.6rem">이름 다시 입력</button>
      <div id="auth-error"></div>
    `;
    const pinInput = card.querySelector("#login-pin");
    const loginBtn = card.querySelector("#login-btn");
    pinInput.focus();

    const submit = async () => {
      showError("");
      try {
        const result = await api.login({ ward_id: state.wardId, name, pin: pinInput.value });
        if (!applyAuth(result.token)) {
          showError("로그인 토큰을 읽지 못했습니다. 다시 시도해 주세요.");
          return;
        }
        navigate();
      } catch (err) {
        showError(err.message);
      }
    };

    onClickBusy(loginBtn, submit, "로그인 중...");
    pinInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") withBusy(loginBtn, submit, "로그인 중...");
    });
    card.querySelector("#change-name-btn").addEventListener("click", () => renderNameStep(name));
  }

  // 2단계-B: 명단엔 있으나 미등록 → PIN 설정 후 등록
  function renderRegisterStep(name) {
    card.innerHTML = `
      <p class="caption" style="margin-top:0"><strong>${escapeHtml(name)}</strong> 님, 처음이시네요. PIN을 설정하세요.</p>
      <label for="reg-pin">PIN (4~6자리 숫자)</label>
      <input type="password" id="reg-pin" autocomplete="off" />
      <label for="reg-pin2">PIN 확인</label>
      <input type="password" id="reg-pin2" autocomplete="off" />
      <button class="primary" id="register-btn">등록</button>
      <button id="change-name-btn" style="margin-top:0.6rem">이름 다시 입력</button>
      <div id="auth-error"></div>
    `;
    const pin = card.querySelector("#reg-pin");
    const pin2 = card.querySelector("#reg-pin2");
    const registerBtn = card.querySelector("#register-btn");
    pin.focus();

    const submit = async () => {
      showError("");
      if (pin.value !== pin2.value) {
        showError("PIN 확인이 일치하지 않습니다.");
        return;
      }
      try {
        const result = await api.register({ ward_id: state.wardId, name, pin: pin.value });
        if (!applyAuth(result.token)) {
          showError("로그인 토큰을 읽지 못했습니다. 다시 시도해 주세요.");
          return;
        }
        navigate();
      } catch (err) {
        showError(err.message);
      }
    };

    onClickBusy(registerBtn, submit, "등록 중...");
    pin2.addEventListener("keydown", (e) => {
      if (e.key === "Enter") withBusy(registerBtn, submit, "등록 중...");
    });
    card.querySelector("#change-name-btn").addEventListener("click", () => renderNameStep(name));
  }

  function showError(message) {
    const box = card.querySelector("#auth-error");
    if (box) box.innerHTML = message ? `<div class="error-banner">${escapeHtml(message)}</div>` : "";
  }

  renderNameStep();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
