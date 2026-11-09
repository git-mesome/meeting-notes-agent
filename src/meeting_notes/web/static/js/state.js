/* 여러 화면이 같이 쓰는 상수와 상태. */

export const root = document.getElementById("app");
export const POLL_MS = 5000;
export const ACCEPT = ".m4a,.mp3,.wav,.flac,.ogg,.aac,.mp4,.webm,audio/*";
export const TIME_REF = /\[(\d{1,2}:\d{2}(?::\d{2})?)\]/;
export const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

// 여러 화면이 같이 쓰는 값. 모듈 사이에서는 let 변수를 다시 넣을 수 없어 객체 하나에 둔다.
export const state = {
  pollTimer: null, // 목록과 처리 화면의 새로고침 타이머
  cleanup: null, // 화면을 떠날 때 정리할 일
  unsaved: false, // 회의록 수정 중 저장하지 않은 내용
  templatesCache: null,
  trackerCache: null,
  selectedTemplate: "general",
};
