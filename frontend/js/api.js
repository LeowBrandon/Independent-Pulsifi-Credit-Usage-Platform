/**
 * API client for the Independent Pulsifi Credit Usage Platform MVP.
 * Automatically injects RBAC actor headers (X-Actor-Role / X-Actor-Name).
 */

export const ROLE_ACTORS = {
  OPERATIONS: { name: "ops.lead@consultingfirm.com", label: "Operations (Maker)" },
  FINANCE: { name: "finance.controller@consultingfirm.com", label: "Finance (Checker)" },
  EXECUTIVE: { name: "managing.partner@consultingfirm.com", label: "Executive (Read-Only)" },
  ADMIN: { name: "platform.admin@consultingfirm.com", label: "Admin (Rules & Pools)" },
};

let currentRole = "OPERATIONS";

export function getActiveRole() {
  return currentRole;
}

export function setActiveRole(role) {
  if (ROLE_ACTORS[role]) {
    currentRole = role;
  }
}

export function getActiveActor() {
  return { role: currentRole, ...ROLE_ACTORS[currentRole] };
}

function authHeaders(extra = {}) {
  const actor = getActiveActor();
  return {
    "X-Actor-Role": actor.role,
    "X-Actor-Name": actor.name,
    ...extra,
  };
}

export async function apiRequest(path, options = {}) {
  const headers = authHeaders(options.headers || {});
  const fetchOpts = { ...options, headers };
  if (options.json !== undefined) {
    fetchOpts.body = JSON.stringify(options.json);
    fetchOpts.headers["Content-Type"] = "application/json";
    delete fetchOpts.json;
  }
  const res = await fetch(path, fetchOpts);
  const contentType = res.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await res.json()
    : await res.text();
  if (!res.ok) {
    const msg = typeof data === "object" && data?.detail ? data.detail : `HTTP ${res.status}`;
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return data;
}

export async function apiUpload(path, formData) {
  return apiRequest(path, {
    method: "POST",
    body: formData,
  });
}
