/* 상단 바와 화면 전환, 회의 삭제. */

import { api } from "./api.js";
import { root, state } from "./state.js";
import { confirmSheet, el, icon, toast } from "./ui.js";

export function topbar({ back = false, right = null } = {}) {
  const left = back
    ? el("a", { class: "icon-button", href: "#/", "aria-label": "목록으로" }, icon("back"))
    : el("a", { class: "brand", href: "#/" }, el("img", { src: "/static/favicon.svg", alt: "" }), "회의록");
  return el("header", { class: "topbar" }, left, right);
}

export function setScreen({ wide = false, back = false, right = null } = {}) {
  clearTimeout(state.pollTimer);
  if (state.cleanup) state.cleanup();
  state.cleanup = null;
  state.unsaved = false;
  const page = el("main", { class: wide ? "page wide" : "page" });
  root.replaceChildren(topbar({ back, right }), page);
  window.scrollTo(0, 0);
  return page;
}

export async function deleteJob(job) {
  const agreed = await confirmSheet({
    title: "이 회의록을 삭제할까요?",
    body: "녹음과 전사문도 함께 지워지고, 되돌릴 수 없어요.",
    action: "삭제",
    danger: true,
  });
  if (!agreed) return;
  try {
    await api(`/api/jobs/${job.id}`, { method: "DELETE" });
    toast("삭제했어요");
    location.hash = "#/";
  } catch (error) {
    toast(error.message, true);
  }
}

