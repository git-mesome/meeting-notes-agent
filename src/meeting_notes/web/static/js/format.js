/* 시간, 날짜, 처리 상태를 화면 문구로 바꾼다. */

import { el, icon } from "./ui.js";

export function clock(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = String(total % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}` : `${String(minutes).padStart(2, "0")}:${secs}`;
}

export function parseClock(text) {
  return text.split(":").reduce((sum, part) => sum * 60 + Number(part), 0);
}

export function spanOfTime(seconds) {
  const minutes = Math.max(1, Math.round(seconds / 60));
  const hours = Math.floor(minutes / 60);
  if (!hours) return `${minutes}분`;
  return minutes % 60 ? `${hours}시간 ${minutes % 60}분` : `${hours}시간`;
}

export function dateText(iso) {
  return new Intl.DateTimeFormat("ko-KR", {
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function metaText(job) {
  return `${dateText(job.created_at)}, ${spanOfTime(job.duration_seconds)} 녹음`;
}

export function displayName(job) {
  return job.title || job.name.replace(/\.[^.]+$/, "");
}

export function headline(job) {
  if (job.status === "queued") return job.ahead ? "순서를 기다리고 있어요" : "곧 시작해요";
  if (job.status === "transcribing") return "말을 글로 옮기고 있어요";
  if (job.status === "writing") return "회의록을 쓰고 있어요";
  if (job.status === "canceled") return "처리를 멈췄어요";
  if (job.status === "failed") return "회의록을 만들지 못했어요";
  return "";
}

export function detailText(job) {
  if (job.status === "queued") return job.ahead ? `앞에 ${job.ahead}건이 있어요` : "";
  if (job.status === "transcribing") {
    const left = job.estimated_seconds - job.elapsed_seconds;
    return left > 0 ? `약 ${spanOfTime(left)} 남았어요` : "예상보다 오래 걸리고 있어요";
  }
  if (job.status === "writing") return "거의 다 됐어요";
  if (job.status === "canceled") return `다시 시작하면 약 ${spanOfTime(job.estimated_seconds)} 걸려요`;
  if (job.status === "failed") return job.error;
  return "";
}

export function progress(job) {
  if (job.status === "transcribing") return Math.min(0.95, job.elapsed_seconds / job.estimated_seconds);
  if (job.status === "writing") return 0.97;
  return 0;
}

export function isActive(job) {
  return ["queued", "transcribing", "writing"].includes(job.status);
}

export function isWorking(job) {
  return job.status === "transcribing" || job.status === "writing";
}

export function badge(job, animate = false) {
  if (job.status === "done" && job.confirmed_at) {
    return el("span", { class: `badge confirmed ${animate ? "pop" : ""}` }, icon("check"), "확정");
  }
  if (job.status === "done") return el("span", { class: "badge draft", text: "초안" });
  if (job.status === "failed") return el("span", { class: "badge failed", text: "실패" });
  if (job.status === "canceled") return el("span", { class: "badge", text: "멈춤" });
  if (job.status === "queued") return el("span", { class: "badge", text: "대기" });
  return el("span", { class: "badge working", text: "처리 중" });
}

