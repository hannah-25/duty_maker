export const state = {
  wardId: null,
  wardLabel: "",
  token: null,
  name: null,
  isAdmin: false,
};

const LAST_WARD_KEY = "dutyMaker.lastWard";
const AUTH_KEY = "dutyMaker.auth";

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

/**
 * JWT payload를 읽는다. 서명은 검증하지 않는다 — 화면에 이름/권한을 그리기 위한
 * 용도일 뿐이고, 실제 권한은 서버가 요청마다 다시 검증한다.
 */
function decodeTokenPayload(token) {
  try {
    const segment = String(token).split(".")[1];
    if (!segment) return null;
    const base64 = segment.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
    // 이름이 한글이라 atob 결과를 그대로 쓰면 깨진다. UTF-8로 다시 디코딩해야 한다.
    const bytes = Uint8Array.from(atob(padded), (ch) => ch.charCodeAt(0));
    const payload = JSON.parse(new TextDecoder().decode(bytes));
    if (!payload?.ward_id || !payload?.name) return null;
    return payload;
  } catch {
    return null;
  }
}

function isExpired(payload) {
  return typeof payload.exp !== "number" || payload.exp * 1000 <= Date.now();
}

/** 토큰을 state에 반영하고 저장한다. 이름/권한은 토큰이 유일한 출처다. */
export function applyAuth(token) {
  const payload = decodeTokenPayload(token);
  if (!payload || isExpired(payload)) return false;
  state.token = token;
  state.name = payload.name;
  state.isAdmin = Boolean(payload.is_admin);
  try {
    localStorage.setItem(AUTH_KEY, token);
  } catch {
    /* 저장에 실패해도 이번 세션은 그대로 쓸 수 있다 */
  }
  return true;
}

function clearAuthState() {
  state.token = null;
  state.name = null;
  state.isAdmin = false;
}

/**
 * 해당 병동에 유효한 토큰만 state에 남긴다. 이미 들고 있는 토큰이 다른 병동의
 * 것이거나 만료됐으면 버리고, 저장된 토큰으로 복구를 시도한다.
 *
 * 메모리 토큰을 반드시 검사해야 한다. 그러지 않으면 A 병동에 로그인한 채
 * /wards/B/app 으로 이동했을 때 B 화면이 A 토큰으로 그려진다.
 */
export function restoreAuth(wardId) {
  if (state.token) {
    const payload = decodeTokenPayload(state.token);
    if (payload && !isExpired(payload) && payload.ward_id === wardId) return true;
    clearAuthState();
  }

  let token = null;
  try {
    token = localStorage.getItem(AUTH_KEY);
  } catch {
    return false;
  }
  if (!token) return false;

  const payload = decodeTokenPayload(token);
  if (!payload || isExpired(payload)) {
    resetAuth();
    return false;
  }
  // 다른 병동의 토큰은 그 병동으로 돌아갔을 때 다시 쓸 수 있으니 지우지 않는다.
  if (payload.ward_id !== wardId) return false;

  state.token = token;
  state.name = payload.name;
  state.isAdmin = Boolean(payload.is_admin);
  return true;
}

export function resetAuth() {
  clearAuthState();
  try {
    localStorage.removeItem(AUTH_KEY);
  } catch {
    /* localStorage may be unavailable in private or restricted contexts */
  }
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
