/* 회의에서 함께 본 자료 붙이기. */

import { api, jsonOptions } from "./api.js";
import { route } from "./router.js";
import { button, confirmSheet, el, icon, openSheet, toast } from "./ui.js";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.html,.htm";

function sizeText(bytes) {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)}MB` : `${Math.max(1, Math.round(bytes / 1024))}KB`;
}

export function documentsText(job) {
  return job.documents.length ? `자료 ${job.documents.length}개를 붙였어요. 회의록을 쓸 때 함께 봐요.` : "";
}

/* 자료 목록 창. 붙이거나 지운 게 있으면 창을 닫을 때 onClose(최신 작업)를 부른다.
   회의록을 고칠 수 없는 사람은 목록을 보고 내려받기만 한다(jobs/access.py). */
export function openDocumentsSheet(job, onClose) {
  const editable = job.access.edit;
  let latest = job;
  let changed = false;
  const list = el("ul", { class: "note-list document-list" });
  const picker = el("input", { class: "document-picker", type: "file", accept: ACCEPT, multiple: true, id: "document-file" });
  const add = el("label", { class: "button primary", for: "document-file" }, icon("upload"), "자료 추가");

  const remove = async (doc) => {
    try {
      latest = await api(`/api/jobs/${job.id}/documents/${encodeURIComponent(doc.name)}`, { method: "DELETE" });
      changed = true;
      renderList();
    } catch (error) {
      toast(error.message, true);
    }
  };

  function renderList() {
    const rows = latest.documents.map((doc) =>
      el(
        "li",
        { class: "voice-row" },
        el(
          "div",
          { class: "document-text" },
          el("a", {
            class: "note-title",
            href: `/api/jobs/${job.id}/documents/${encodeURIComponent(doc.name)}`,
            text: doc.name,
          }),
          el("span", { class: "meta", text: sizeText(doc.size) }),
        ),
        editable ? button("삭제", { onclick: () => remove(doc) }) : null,
      ),
    );
    list.replaceChildren(...(rows.length ? rows : [el("li", { class: "document-empty", text: "아직 붙인 자료가 없어요." })]));
  }

  picker.addEventListener("change", async () => {
    const files = [...picker.files];
    picker.value = "";
    picker.disabled = true;
    add.setAttribute("aria-disabled", "true");
    for (const file of files) {
      const form = new FormData();
      form.append("file", file);
      try {
        latest = await api(`/api/jobs/${job.id}/documents`, { method: "POST", body: form });
        changed = true;
        renderList();
      } catch (error) {
        toast(`${file.name}: ${error.message}`, true);
      }
    }
    picker.disabled = false;
    add.removeAttribute("aria-disabled");
  });

  const sheet = openSheet((close) => [
    el("h2", { text: "회의 자료" }),
    el("p", {
      text: "회의에서 같이 본 PDF나 화면 캡처를 붙이면 이름, 숫자, '이거'가 가리키는 내용을 더 정확하게 정리해요. 회의에서 말하지 않은 자료 내용은 회의록에 넣지 않아요.",
    }),
    list,
    editable
      ? el("p", { class: "input-hint", text: "PDF, 이미지, 텍스트, HTML 파일을 붙일 수 있어요. PPT나 엑셀은 PDF로 저장해서 올려 주세요." })
      : null,
    editable ? picker : null,
    el("div", { class: "sheet-actions" }, button("닫기", { onclick: close }), editable ? add : null),
  ]);
  sheet.addEventListener("close", () => {
    if (changed) onClose(latest);
  });
  renderList();
}

/* 회의록을 쓴 뒤에 자료가 바뀌었으면 다시 쓰라고 알린다. */
export function documentsNotice(job) {
  if (!job.documents_pending) return null;
  const rewrite = button("자료 반영해서 다시 쓰기", {
    variant: "primary",
    iconName: "rewrite",
    onclick: async () => {
      const agreed = await confirmSheet({
        title: "자료를 반영해서 다시 쓸까요?",
        body: "전사는 다시 하지 않고 회의록만 새로 써요. 직접 수정한 내용은 사라지고, API 비용이 들어요.",
        action: "다시 쓰기",
      });
      if (!agreed) return;
      rewrite.disabled = true;
      try {
        await api(`/api/jobs/${job.id}/regenerate`, jsonOptions("POST", { template: job.template }));
        route();
      } catch (error) {
        toast(error.message, true);
        rewrite.disabled = false;
      }
    },
  });
  return el(
    "section",
    { class: "card documents-notice" },
    el("p", { text: "붙이거나 지운 자료가 아직 회의록에 반영되지 않았어요." }),
    rewrite,
  );
}
