// One API client for the whole app: token, company override (Superadmin support access), errors as messages.
const BASE = import.meta.env.VITE_API_BASE || "";
let token = localStorageGet("c2h_token");
let companyOverride = localStorageGet("c2h_company");

function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* private mode */ } }

export function setToken(t) { token = t; localStorageSet("c2h_token", t); }
export function getToken() { return token; }
export function setCompanyOverride(id) { companyOverride = id ? String(id) : null; localStorageSet("c2h_company", companyOverride); }
export function getCompanyOverride() { return companyOverride; }

async function request(method, path, body, opts = {}) {
  const headers = {};
  if (token) headers.Authorization = "Bearer " + token;
  if (companyOverride) headers["X-Company-Id"] = companyOverride;
  let payload;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  let res;
  try { res = await fetch(BASE + "/api" + path, { method, headers, body: payload }); }
  catch { throw new Error("Can't reach Code2Hire. Check your internet connection and try again."); }
  if (opts.raw) {
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "Request failed");
    return res;
  }
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json() : null;
  if (res.status === 401 && token) { setToken(null); window.dispatchEvent(new Event("c2h:logout")); }
  if (!res.ok) {
    const msg = res.status === 429 ? (data && data.error) || "Too many tries. Please wait a moment and try again."
      : (data && data.error) || (res.status >= 500 ? "Something went wrong on our side. Please try again." : `Something went wrong (${res.status}).`);
    const e = new Error(msg); e.status = res.status; e.fields = (data && data.fields) || null; e.data = data; throw e;
  }
  return data && "data" in data ? data.data : data;
}

export const api = {
  get: (p, params) => request("GET", p + (params ? "?" + new URLSearchParams(clean(params)) : "")),
  post: (p, b = {}) => request("POST", p, b),
  put: (p, b = {}) => request("PUT", p, b),
  patch: (p, b = {}) => request("PATCH", p, b),
  del: (p, b) => request("DELETE", p, b),
  raw: (method, p, b) => request(method, p, b, { raw: true }),
};

function clean(o) { const r = {}; Object.entries(o).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") r[k] = v; }); return r; }

export async function download(path, filename) {
  const res = await api.raw("GET", path);
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
