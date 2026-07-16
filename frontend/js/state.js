export const state = {
  wardId: null,
  wardLabel: "",
  token: null,
  name: null,
  isAdmin: false,
};

const LAST_WARD_KEY = "dutyMaker.lastWard";

export function setWard(wardId, wardLabel) {
  state.wardId = wardId;
  state.wardLabel = wardLabel;
  try {
    localStorage.setItem(LAST_WARD_KEY, JSON.stringify({ wardId, wardLabel }));
  } catch {
    /* localStorage may be unavailable in private or restricted contexts */
  }
}

export function restoreLastWard() {
  try {
    const raw = localStorage.getItem(LAST_WARD_KEY);
    if (!raw) return false;
    const saved = JSON.parse(raw);
    if (!saved?.wardId) return false;
    state.wardId = saved.wardId;
    state.wardLabel = saved.wardLabel ?? "";
    return true;
  } catch {
    return false;
  }
}

export function resetAuth() {
  state.token = null;
  state.name = null;
  state.isAdmin = false;
}

export function resetWard() {
  state.wardId = null;
  state.wardLabel = "";
  try {
    localStorage.removeItem(LAST_WARD_KEY);
  } catch {
    /* localStorage may be unavailable in private or restricted contexts */
  }
  resetAuth();
}
