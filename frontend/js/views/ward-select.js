import { api } from "../api.js";
import { setWard, state } from "../state.js";

export async function renderWardSelect(root, navigate) {
  root.innerHTML = `
    <h1>Duty Maker</h1>
    <p class="caption">병원/병동을 선택하거나 새로 등록하세요.</p>
    <div class="card">
      <label for="ward-select">병원 / 병동</label>
      <select id="ward-select"><option value="">불러오는 중...</option></select>
      <button class="primary" id="continue-btn" disabled>선택한 병동으로 계속</button>
    </div>
    <button id="toggle-register" style="margin-top:1.4rem">새 병원/병동 등록 ▾</button>
    <div class="card" id="register-card" style="margin-top:0.8rem;display:none">
      <label for="reg-hospital">병원 이름</label>
      <input type="text" id="reg-hospital" />
      <label for="reg-ward">병동 이름</label>
      <input type="text" id="reg-ward" />
      <label for="reg-admin-name">관리자 이름</label>
      <input type="text" id="reg-admin-name" />
      <label for="reg-admin-pin">관리자 PIN (4~6자리 숫자)</label>
      <input type="password" id="reg-admin-pin" />
      <label for="reg-admin-pin2">PIN 확인</label>
      <input type="password" id="reg-admin-pin2" />
      <label for="reg-code">병동 등록 코드</label>
      <input type="password" id="reg-code" />
      <button class="primary" id="register-btn">병동 등록</button>
      <div id="reg-error"></div>
    </div>
  `;

  const select = root.querySelector("#ward-select");
  const continueBtn = root.querySelector("#continue-btn");

  let wards = [];
  try {
    wards = await api.listWards();
  } catch (err) {
    select.innerHTML = "";
    const opt = document.createElement("option");
    opt.textContent = "병동 목록을 불러오지 못했습니다.";
    select.appendChild(opt);
  }

  select.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = wards.length ? "선택하세요" : "등록된 병동이 없습니다";
  select.appendChild(placeholder);
  for (const ward of wards) {
    const opt = document.createElement("option");
    opt.value = ward.ward_id;
    opt.textContent = `${ward.hospital_name} - ${ward.ward_name}`;
    select.appendChild(opt);
  }

  select.addEventListener("change", () => {
    continueBtn.disabled = !select.value;
  });

  const toggle = root.querySelector("#toggle-register");
  const registerCard = root.querySelector("#register-card");
  toggle.addEventListener("click", () => {
    const opening = registerCard.style.display === "none";
    registerCard.style.display = opening ? "" : "none";
    toggle.textContent = opening ? "새 병원/병동 등록 ▴" : "새 병원/병동 등록 ▾";
    if (opening) root.querySelector("#reg-hospital").focus();
  });

  continueBtn.addEventListener("click", () => {
    const ward = wards.find((item) => item.ward_id === select.value);
    if (!ward) return;
    setWard(ward.ward_id, `${ward.hospital_name} - ${ward.ward_name}`);
    location.hash = `#/wards/${encodeURIComponent(ward.ward_id)}/login`;
  });

  root.querySelector("#register-btn").addEventListener("click", async () => {
    const errorBox = root.querySelector("#reg-error");
    errorBox.innerHTML = "";
    const hospital_name = root.querySelector("#reg-hospital").value.trim();
    const ward_name = root.querySelector("#reg-ward").value.trim();
    const admin_name = root.querySelector("#reg-admin-name").value.trim();
    const admin_pin = root.querySelector("#reg-admin-pin").value;
    const admin_pin2 = root.querySelector("#reg-admin-pin2").value;
    const registration_code = root.querySelector("#reg-code").value;

    if (!hospital_name || !ward_name || !admin_name) {
      errorBox.innerHTML = `<div class="error-banner">병원 이름, 병동 이름, 관리자 이름을 모두 입력하세요.</div>`;
      return;
    }
    if (admin_pin !== admin_pin2) {
      errorBox.innerHTML = `<div class="error-banner">PIN 확인이 일치하지 않습니다.</div>`;
      return;
    }
    try {
      const result = await api.createWard({
        hospital_name,
        ward_name,
        admin_name,
        admin_pin,
        registration_code,
      });
      state.token = result.token;
      state.name = result.name;
      state.isAdmin = result.is_admin;
      setWard(result.ward_id, `${hospital_name} - ${ward_name}`);
      location.hash = `#/wards/${encodeURIComponent(result.ward_id)}/app`;
    } catch (err) {
      errorBox.innerHTML = `<div class="error-banner">${err.message}</div>`;
    }
  });
}
