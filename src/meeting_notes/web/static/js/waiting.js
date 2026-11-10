/* 처리 중인 회의 화면. */

import { api } from "./api.js";
import { documentsText, openDocumentsSheet } from "./documents.js";
import { detailText, displayName, headline, isActive, isWorking, progress, spanOfTime } from "./format.js";
import { route } from "./router.js";
import { deleteJob, setScreen } from "./screen.js";
import { POLL_MS, state } from "./state.js";
import { button, confirmSheet, el, icon, meter, toast } from "./ui.js";

export function statusMark(job) {
  if (job.status === "failed") return el("div", { class: "status-mark failed" }, icon("alert"));
  if (job.status === "canceled") return el("div", { class: "status-mark stopped" }, icon("stop"));
  return el(
    "div",
    { class: "status-mark" },
    el("div", { class: "wave", "aria-hidden": "true" }, el("i"), el("i"), el("i"), el("i"), el("i")),
  );
}

export function renderWaiting(job) {
  const page = setScreen({ back: true });
  const title = el("h1", { text: headline(job) });
  const state = el("p", { class: "state", "aria-live": "polite", text: detailText(job) });
  const meterBox = el("div", {}, isWorking(job) ? meter(progress(job)) : null);
  const content = el(
    "div",
    { class: "waiting" },
    statusMark(job),
    title,
    state,
    meterBox,
    el("p", { class: "file", text: `${displayName(job)}, ${spanOfTime(job.duration_seconds)} 녹음` }),
  );
  const bar = el("div", { class: "bottom-bar-inner" });

  if (isActive(job)) {
    const documentsLine = el("p", { class: "note", text: documentsText(job) });
    content.append(
      documentsLine,
      el("p", { class: "note", text: "이 화면을 닫아도 괜찮아요. 끝날 때까지 노트북만 켜 두세요." }),
    );
    const attach = button("회의 자료 붙이기", {
      iconName: "upload",
      onclick: () => openDocumentsSheet(job, (updated) => {
        job.documents = updated.documents;
        documentsLine.textContent = documentsText(updated);
      }),
    });
    const stop = button("처리 멈추기", {
      onclick: async () => {
        const agreed = await confirmSheet({
          title: "처리를 멈출까요?",
          body: "지금까지 옮긴 내용은 사라지고, 다시 시작하면 처음부터 해요.",
          action: "멈추기",
          danger: true,
        });
        if (!agreed) return;
        stop.disabled = true;
        try {
          await api(`/api/jobs/${job.id}/cancel`, { method: "POST" });
          route();
        } catch (error) {
          toast(error.message, true);
          stop.disabled = false;
        }
      },
    });
    // 고칠 수 없는 사람은 진행 상황만 본다(jobs/access.py).
    if (job.access.edit) bar.append(stop, attach);

    const refresh = async () => {
      let latest;
      try {
        latest = await api(`/api/jobs/${job.id}`);
      } catch (error) {
        state.pollTimer = setTimeout(refresh, POLL_MS);
        return;
      }
      if (latest.status !== job.status) {
        route();
        return;
      }
      title.textContent = headline(latest);
      state.textContent = detailText(latest);
      documentsLine.textContent = documentsText(latest);
      meterBox.replaceChildren(...(isWorking(latest) ? [meter(progress(latest))] : []));
      state.pollTimer = setTimeout(refresh, POLL_MS);
    };
    state.pollTimer = setTimeout(refresh, POLL_MS);
  } else {
    const restart = button("다시 시작", {
      variant: "primary",
      onclick: async () => {
        restart.disabled = true;
        try {
          await api(`/api/jobs/${job.id}/retry`, { method: "POST" });
          route();
        } catch (error) {
          toast(error.message, true);
          restart.disabled = false;
        }
      },
    });
    if (job.access.manage) bar.append(button("삭제", { onclick: () => deleteJob(job) }));
    if (job.access.edit) bar.append(restart);
  }

  page.append(content, el("div", { class: "bottom-bar" }, bar));
}

