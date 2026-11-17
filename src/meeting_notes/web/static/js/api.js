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

/* 녹음 파일을 올린다. fetch로는 올린 정도를 알 수 없어 XMLHttpRequest를 쓰고, onProgress(0~1)로 알린다. */
export function uploadFiles(path, files, onProgress) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", path);
    request.responseType = "json";
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    });
    request.addEventListener("load", () => {
      if (request.status === 401) {
        goToLogin();
        reject(new ApiError("로그인이 필요해요."));
      } else if (request.status >= 200 && request.status < 300) {
        resolve(request.response);
      } else {
        const detail = request.response && request.response.detail;
        reject(new ApiError(typeof detail === "string" ? detail : "파일을 올리지 못했어요. 다시 시도해 주세요."));
      }
    });
    request.addEventListener("error", () => reject(new ApiError("연결이 끊겼어요. 노트북이 켜져 있는지 확인해 주세요.")));
    const form = new FormData();
    for (const file of files) form.append("file", file);
    request.send(form);
  });
}

export function jsonOptions(method, body) {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

