import { resetAuth, state } from "./state.js";

const API_BASE = "/api";

export const AUTH_EXPIRED_EVENT = "dutymaker:auth-expired";

/**
 * 로그인해 둔 세션이 서버에서 거부되면(12시간 만료 등) 인증을 비우고 알린다.
 * 라우터가 이 이벤트를 받아 로그인 화면으로 돌린다 — 직접 import하면
 * router -> api -> router 순환이 된다.
 *
 * state.token이 있을 때만 세션 만료로 본다. 로그인 실패도 401이라서,
 * 이 조건이 없으면 PIN을 틀렸을 때 화면이 통째로 다시 그려지며 에러 문구가 사라진다.
 */
function handleUnauthorized() {
  if (!state.token) return;
  resetAuth();
  window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
}

async function readErrorDetail(res) {
  let detail = res.statusText;
  try {
    detail = (await res.json()).detail ?? detail;
  } catch {
    /* response body wasn't JSON */
  }
  return detail;
}

async function request(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await readErrorDetail(res);
    if (res.status === 401) handleUnauthorized();
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

async function download(path) {
  const headers = {};
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
  const res = await fetch(`${API_BASE}${path}`, { headers });
  if (!res.ok) {
    const detail = await readErrorDetail(res);
    if (res.status === 401) handleUnauthorized();
    throw new Error(detail);
  }
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = disposition.match(/filename\*=UTF-8''([^;]+)/);
  const filename = match ? decodeURIComponent(match[1]) : "download";
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export const api = {
  listWards: () => request("/wards"),
  createWard: (body) => request("/wards", { method: "POST", body }),
  lookup: (body) => request("/auth/lookup", { method: "POST", body }),
  login: (body) => request("/auth/login", { method: "POST", body }),
  register: (body) => request("/auth/register", { method: "POST", body }),
  changePin: (body) => request("/auth/change-pin", { method: "POST", body }),
  getRoster: () => request("/nurses"),
  putRoster: (body) => request("/nurses", { method: "PUT", body }),
  getRequirements: () => request("/requirements"),
  putRequirements: (body) => request("/requirements", { method: "PUT", body }),
  getSettings: () => request("/settings"),
  putSettings: (body) => request("/settings", { method: "PUT", body }),
  getExportSettings: () => request("/exports/settings"),
  putExportSettings: (body) => request("/exports/settings", { method: "PUT", body }),
  getRequests: () => request("/requests"),
  addRequest: (body) => request("/requests", { method: "POST", body }),
  updateRequest: (id, body) => request(`/requests/${id}`, { method: "PATCH", body }),
  deleteRequest: (id) => request(`/requests/${id}`, { method: "DELETE" }),
  setRequestLock: (body) => request("/requests/lock", { method: "PUT", body }),
  getSchedule: () => request("/schedule"),
  getPrevMonth: () => request("/schedule/prev-month"),
  putPrevMonth: (body) => request("/schedule/prev-month", { method: "PUT", body }),
  generateSchedule: () => request("/schedule/generate", { method: "POST" }),
  previewScheduleRegeneration: (body) => request("/schedule/regenerate-preview", { method: "POST", body }),
  applyScheduleRegeneration: (previewId) => request("/schedule/regenerate-apply", {
    method: "POST",
    body: { preview_id: previewId },
  }),
  cancelScheduleRegeneration: (previewId) => request(`/schedule/regenerate-preview/${encodeURIComponent(previewId)}`, {
    method: "DELETE",
  }),
  updateScheduleAssignment: (body) => request("/schedule/assignment", { method: "PATCH", body }),
  publishSchedule: (body) => request("/schedule/publish", { method: "PUT", body }),
  downloadHwpx: () => download("/exports/hwpx"),
  downloadXlsx: () => download("/exports/xlsx"),
  getAccounts: () => request("/accounts"),
  updateAccount: (name, body) => request(`/accounts/${encodeURIComponent(name)}`, { method: "PATCH", body }),
  resetPin: (name) => request(`/accounts/${encodeURIComponent(name)}/reset-pin`, { method: "POST" }),
  deleteAccount: (name) => request(`/accounts/${encodeURIComponent(name)}`, { method: "DELETE" }),
};
