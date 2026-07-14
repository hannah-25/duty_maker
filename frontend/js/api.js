import { state } from "./state.js";

const API_BASE = "/api";

async function request(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* response body wasn't JSON */
    }
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
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* response body wasn't JSON */
    }
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
  login: (body) => request("/auth/login", { method: "POST", body }),
  register: (body) => request("/auth/register", { method: "POST", body }),
  getRoster: () => request("/nurses"),
  putRoster: (body) => request("/nurses", { method: "PUT", body }),
  getRequirements: () => request("/requirements"),
  putRequirements: (body) => request("/requirements", { method: "PUT", body }),
  getSettings: () => request("/settings"),
  putSettings: (body) => request("/settings", { method: "PUT", body }),
  getRequests: () => request("/requests"),
  addRequest: (body) => request("/requests", { method: "POST", body }),
  updateRequest: (id, body) => request(`/requests/${id}`, { method: "PATCH", body }),
  deleteRequest: (id) => request(`/requests/${id}`, { method: "DELETE" }),
  setRequestLock: (body) => request("/requests/lock", { method: "PUT", body }),
  getSchedule: () => request("/schedule"),
  generateSchedule: () => request("/schedule/generate", { method: "POST" }),
  publishSchedule: (body) => request("/schedule/publish", { method: "PUT", body }),
  downloadHwpx: () => download("/exports/hwpx"),
  downloadXlsx: () => download("/exports/xlsx"),
  getAccounts: () => request("/accounts"),
  updateAccount: (name, body) => request(`/accounts/${encodeURIComponent(name)}`, { method: "PATCH", body }),
  deleteAccount: (name) => request(`/accounts/${encodeURIComponent(name)}`, { method: "DELETE" }),
};
