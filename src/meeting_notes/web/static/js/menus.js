/* 회의록 화면의 더보기 메뉴와 양식 바꾸기. */

import { api, jsonOptions, loadTemplates } from "./api.js";
import { route } from "./router.js";
import { renderEditor } from "./notes.js";
import { deleteJob } from "./screen.js";
import { confirmSheet, el, icon, openSheet, toast } from "./ui.js";

export async function openTemplateMenu(job) {
  let templates;
  try {
    templates = await loadTemplates();
  } catch (error) {
    toast(error.message, true);
    return;
  }
  openSheet((close) => [
    el("h2", { text: "어떤 양식으로 다시 쓸까요?" }),
    el("p", { text: "전사는 다시 하지 않고 회의록만 새로 써요." }),
    el(
      "div",
      { class: "sheet-menu template-menu" },
      ...templates.map((template) =>
        el(
          "button",
          {
            class: "sheet-item",
            type: "button",
            onclick: async () => {
              close();
              const agreed = await confirmSheet({
                title: `'${template.label}' 양식으로 다시 쓸까요?`,
                body: "지금 회의록은 새 내용으로 바뀌고, 직접 수정한 내용도 사라져요. API 비용이 들어요.",
                action: "다시 쓰기",
              });
              if (!agreed) return;
              try {
                await api(`/api/jobs/${job.id}/regenerate`, jsonOptions("POST", { template: template.key }));
                route();
              } catch (error) {
                toast(error.message, true);
              }
            },
          },
          el(
            "span",
            { class: "template-text" },
            el("strong", { text: template.label }),
            el("small", { text: template.description }),
          ),
          template.key === job.template ? el("span", { class: "badge", text: "지금 양식" }) : null,
        ),
      ),
    ),
  ]);
}

export function openMoreMenu(job, { onDocuments }) {
  openSheet((close) => [
    el(
      "div",
      { class: "sheet-menu" },
      el(
        "button",
        {
          class: "sheet-item",
          type: "button",
          onclick: () => {
            close();
            openTemplateMenu(job);
          },
        },
        icon("rewrite"),
        "다른 양식으로 다시 쓰기",
      ),
      el(
        "button",
        {
          class: "sheet-item",
          type: "button",
          onclick: () => {
            close();
            onDocuments();
          },
        },
        icon("upload"),
        "회의 자료 붙이기",
      ),
      el(
        "button",
        {
          class: "sheet-item",
          type: "button",
          onclick: () => {
            close();
            renderEditor(job);
          },
        },
        icon("pencil"),
        "마크다운으로 전체 수정",
      ),
      el(
        "a",
        { class: "sheet-item", href: `/api/jobs/${job.id}/download`, onclick: close },
        icon("download"),
        "내려받기",
      ),
      el(
        "a",
        { class: "sheet-item", href: `/api/jobs/${job.id}/share`, onclick: close },
        icon("download"),
        "공유용 HTML 내려받기",
      ),
      el(
        "button",
        {
          class: "sheet-item danger",
          type: "button",
          onclick: () => {
            close();
            deleteJob(job);
          },
        },
        icon("trash"),
        "삭제하기",
      ),
    ),
  ]);
}

