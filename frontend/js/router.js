import { api } from "./api.js";
import { resetWard, restoreLastWard, setWard, state } from "./state.js";
import { renderWardSelect } from "./views/ward-select.js";
import { renderLogin } from "./views/login.js";
import { renderApp } from "./views/app.js";

const root = document.getElementById("app-root");
let navigating = false;

export function wardSelectPath() {
  return "#/wards";
}

export function wardLoginPath(wardId) {
  return `#/wards/${encodeURIComponent(wardId)}/login`;
}

export function wardAppPath(wardId) {
  return `#/wards/${encodeURIComponent(wardId)}/app`;
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
        setHash(wardLoginPath(state.wardId));
        return;
      }
      renderLogin(root, navigate);
    } else {
      if (currentRoute()?.view !== "app") {
        setHash(wardAppPath(state.wardId));
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
    return;
  }

  if (state.wardId) {
    setHash(state.token ? wardAppPath(state.wardId) : wardLoginPath(state.wardId));
    return;
  }

  if (restoreLastWard()) {
    setHash(wardLoginPath(state.wardId));
    return;
  }

  if (location.hash !== wardSelectPath()) {
    setHash(wardSelectPath());
  }
}

async function applyWard(wardId) {
  if (state.wardId === wardId && state.wardLabel) return;
  const wards = await api.listWards();
  const ward = wards.find((item) => item.ward_id === wardId);
  if (!ward) {
    resetWard();
    setHash(wardSelectPath());
    return;
  }
  setWard(ward.ward_id, `${ward.hospital_name} - ${ward.ward_name}`);
}

function currentRoute() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] !== "wards") return null;
  if (parts.length === 1) return { view: "select" };
  return {
    view: parts[2] === "app" ? "app" : "login",
    wardId: decodeURIComponent(parts[1] ?? ""),
  };
}

function setHash(nextHash) {
  if (location.hash === nextHash) {
    return;
  }
  location.hash = nextHash;
  setTimeout(navigate, 0);
}

window.addEventListener("hashchange", navigate);
