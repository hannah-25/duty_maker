import { api, AUTH_EXPIRED_EVENT } from "./api.js";
import { resetWard, restoreAuth, restoreLastWard, setWard, state } from "./state.js";
import { renderWardSelect } from "./views/ward-select.js";
import { renderLogin } from "./views/login.js";
import { renderApp } from "./views/app.js";

const root = document.getElementById("app-root");
let navigating = false;

export function wardSelectPath() {
  return "/wards";
}

export function wardLoginPath(wardId) {
  return `/wards/${encodeURIComponent(wardId)}/login`;
}

export function wardAppPath(wardId) {
  return `/wards/${encodeURIComponent(wardId)}/app`;
}

// 사용자 동작으로 이동할 때 쓴다(뒤로가기 히스토리에 남김).
export function navigateTo(path) {
  setPath(path, false);
}

export async function navigate() {
  if (navigating) return;
  navigating = true;
  try {
    await syncRouteToState();
    if (!state.wardId) {
      renderWardSelect(root, navigate);
    } else if (!state.token) {
      if (currentRoute()?.view !== "login") {
        setPath(wardLoginPath(state.wardId), true);
        return;
      }
      renderLogin(root, navigate);
    } else {
      if (currentRoute()?.view !== "app") {
        setPath(wardAppPath(state.wardId), true);
        return;
      }
      renderApp(root, navigate);
    }
  } finally {
    navigating = false;
  }
}

async function syncRouteToState() {
  const route = currentRoute();
  if (route?.wardId) {
    await applyWard(route.wardId);
    // applyWard가 병동을 못 찾으면 병동 선택으로 되돌린다.
    if (state.wardId) restoreAuth(state.wardId);
    return;
  }

  if (!state.wardId && !restoreLastWard()) {
    if (location.pathname !== wardSelectPath()) {
      setPath(wardSelectPath(), true);
    }
    return;
  }

  restoreAuth(state.wardId);
  setPath(state.token ? wardAppPath(state.wardId) : wardLoginPath(state.wardId), true);
}

async function applyWard(wardId) {
  if (state.wardId === wardId && state.wardLabel) return;
  const wards = await api.listWards();
  const ward = wards.find((item) => item.ward_id === wardId);
  if (!ward) {
    resetWard();
    setPath(wardSelectPath(), true);
    return;
  }
  setWard(ward.ward_id, `${ward.hospital_name} - ${ward.ward_name}`);
}

function currentRoute() {
  const parts = location.pathname.replace(/^\/+/, "").split("/").filter(Boolean);
  if (parts[0] !== "wards") return null;
  if (parts.length === 1) return { view: "select" };
  return {
    view: parts[2] === "app" ? "app" : "login",
    wardId: decodeURIComponent(parts[1] ?? ""),
  };
}

// replace=true인 리다이렉트는 잘못된 URL을 바로잡는 용도라 히스토리에 쌓지 않는다.
function setPath(nextPath, replace = false) {
  if (location.pathname === nextPath) {
    return;
  }
  if (replace) {
    history.replaceState({}, "", nextPath);
  } else {
    history.pushState({}, "", nextPath);
  }
  setTimeout(navigate, 0);
}

window.addEventListener("popstate", navigate);

// 세션이 만료되면 로그인 화면으로 되돌린다.
window.addEventListener(AUTH_EXPIRED_EVENT, () => {
  // 이미 로그인 경로면 setPath가 아무것도 하지 않으므로 직접 다시 그린다.
  if (state.wardId && location.pathname !== wardLoginPath(state.wardId)) {
    setPath(wardLoginPath(state.wardId), true);
    return;
  }
  navigate();
});
