/* 서버 API 호출. 로그인이 풀렸으면 SSO 로그인으로 보낸다. */

import { state } from "./state.js";

export async function loadTemplates() {
  if (!state.templatesCache) state.templatesCache = await api("/api/templates");
  return state.templatesCache;
}

export class ApiError extends Error {}

export function goToLogin() {
  // 로그인이 풀렸으면 SSO 로그인으로 보내고, 돌아오면 보던 화면을 연다.
  location.href = `/auth/login?next=${encodeURIComponent(`/${location.hash}`)}`;
}

export async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (response.status === 401) {
    goToLogin();
    throw new ApiError("로그인이 필요해요.");
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "요청을 처리하지 못했어요. 다시 시도해 주세요.";
    throw new ApiError(detail);
  }
  return body;
}

export function jsonOptions(method, body) {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

