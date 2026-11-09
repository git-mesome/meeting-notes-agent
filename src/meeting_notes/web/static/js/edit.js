/* 회의록 카드를 그 자리에서 고친다. 고친 카드만 마크다운으로 되돌려 회의록 전체에서 바꿔 끼운다. */

import { api, jsonOptions } from "./api.js";
import { storedText } from "./notes.js";
import { state } from "./state.js";
import { button, el, icon, toast } from "./ui.js";

// 한 줄로 고치는 곳. 목록은 ul/ol 전체를 고칠 수 있게 해서 Enter로 항목을 더할 수 있다.
const SINGLE_LINE = "h3, p, td > div, .check-text";

/* 화면 → 마크다운 */

export function inlineText(node) {
  let out = "";
  for (const child of node.childNodes) {
    if (child.nodeType === Node.TEXT_NODE) {
      out += child.textContent;
    } else if (child.nodeType !== Node.ELEMENT_NODE || child.matches("input, [data-ui]")) {
      continue;
    } else if (child.matches("button.time-ref")) {
      out += `[${child.textContent.trim()}]`;
    } else if (child.matches("strong, b")) {
      const inner = inlineText(child).trim();
      if (inner) out += `**${inner}**`;
    } else if (child.matches("br")) {
      out += " ";
    } else {
      out += ` ${inlineText(child)}`;
    }
  }
  return out.replace(/​/g, "").replace(/\s+/g, " ");
}

export function sectionMarkdown(section, headingLine) {
  const lines = [headingLine];
  const text = (node) => inlineText(node).trim();
  for (const node of section.children) {
    if (node.matches("[data-ui]")) continue;
    if (node.matches("h3") && text(node)) {
      lines.push(`### ${text(node)}`);
    } else if (node.matches("ul")) {
      for (const item of node.children) {
        if (item.matches(".check-item")) {
          const body = text(item.querySelector(".check-text"));
          if (body) lines.push(`- ${item.querySelector("input").checked ? "[x] " : ""}${body}`);
        } else if (text(item)) {
          lines.push(`- ${text(item)}`);
        }
      }
    } else if (node.matches("ol")) {
      const items = [...node.children].map(text).filter(Boolean);
      items.forEach((item, index) => lines.push(`${index + 1}. ${item}`));
    } else if (node.matches("table")) {
      const head = [...node.querySelectorAll("thead th")].map((cell) => cell.textContent.trim());
      lines.push(`| ${head.join(" | ")} |`, `|${head.map(() => "---").join("|")}|`);
      for (const row of node.querySelectorAll("tbody tr")) {
        // 표 칸 안의 | 는 칸을 나누므로 바꾼다.
        const cells = [...row.children].map((cell) => text(cell).replaceAll("|", "/"));
        if (cells.some(Boolean)) lines.push(`| ${cells.join(" | ")} |`);
      }
    } else if (node.matches("p") && text(node)) {
      lines.push(text(node));
    }
  }
  return lines.join("\n");
}

export function splitSections(notes) {
  const parts = notes.split(/^(?=## )/m);
  const lead = parts[0].startsWith("## ") ? "" : parts.shift();
  return { lead, sections: parts };
}

export function replaceSection(notes, index, markdown) {
  const { lead, sections } = splitSections(notes);
  sections[index] = `${markdown.trimEnd()}\n\n`;
  return `${lead}${sections.join("")}`.trimEnd() + "\n";
}

/* 고치기 */

function editables(section) {
  // 화면 순서대로 고른다. 확인 필요 목록은 항목 글자만 고치고 체크 상자는 그대로 둔다.
  return [...section.querySelectorAll(`${SINGLE_LINE}, ul, ol`)].filter(
    (node) => !node.closest("[data-ui]") && !(node.matches("ul") && node.querySelector(".check-item")),
  );
}

function emptyRow(table) {
  const head = [...table.querySelectorAll("thead th")].map((cell) => cell.textContent.trim());
  return el("tr", {}, ...head.map((label) => el("td", { "data-label": label }, el("div", {}))));
}

function startEditing(section, job, onSaved) {
  const article = section.closest(".notes");
  if (article.querySelector("section.editing")) {
    toast("고치고 있는 칸을 먼저 저장하거나 취소해 주세요", true);
    return;
  }
  const index = Number(section.dataset.index);
  const headingLine = splitSections(job.notes).sections[index].split("\n", 1)[0];
  const actions = section.querySelector(".section-actions");
  section.classList.add("editing");

  const fields = editables(section);
  for (const field of fields) {
    field.contentEditable = "true";
    field.classList.add("editable");
    field.addEventListener("keydown", (event) => {
      if (event.key === "Escape") cancel.click();
      // 제목, 문단, 표 칸은 한 줄이다. 목록은 Enter로 항목을 더한다.
      if (event.key === "Enter" && field.matches(SINGLE_LINE)) event.preventDefault();
    });
  }
  for (const chip of section.querySelectorAll(".time-ref")) chip.contentEditable = "false";
  fields[0]?.focus();

  const onInput = () => {
    state.unsaved = true;
  };
  // 다른 곳에서 복사한 서식은 버리고 글자만 붙인다.
  const onPaste = (event) => {
    event.preventDefault();
    document.execCommand("insertText", false, event.clipboardData.getData("text/plain").replace(/\s+/g, " "));
  };
  section.addEventListener("input", onInput);
  section.addEventListener("paste", onPaste);

  const addRows = [...section.querySelectorAll("table")].map((table) => {
    const add = el("button", {
      class: "text-button add-row",
      type: "button",
      "data-ui": "",
      text: "+ 행 추가",
      onclick: () => {
        const row = emptyRow(table);
        table.querySelector("tbody").append(row);
        for (const cell of row.querySelectorAll("td > div")) {
          cell.contentEditable = "true";
          cell.classList.add("editable");
          cell.addEventListener("keydown", (event) => event.key === "Enter" && event.preventDefault());
        }
        row.querySelector("td > div").focus();
      },
    });
    table.after(add);
    return add;
  });

  const finish = () => {
    state.unsaved = false;
    section.classList.remove("editing");
    section.removeEventListener("input", onInput);
    section.removeEventListener("paste", onPaste);
    addRows.forEach((add) => add.remove());
  };
  const cancel = button("취소", {
    onclick: () => {
      finish();
      onSaved(job); // 고치기 전 모습으로 다시 그린다
    },
  });
  const save = button("저장", {
    variant: "primary",
    onclick: async () => {
      save.disabled = true;
      const notes = replaceSection(job.notes, index, storedText(job)(sectionMarkdown(section, headingLine)));
      try {
        const updated = await api(`/api/jobs/${job.id}/notes`, jsonOptions("PUT", { notes }));
        finish();
        toast("저장했어요");
        onSaved(updated);
      } catch (error) {
        toast(error.message, true);
        save.disabled = false;
      }
    },
  });
  actions.replaceChildren(cancel, save);
}

export function attachSectionEditors(article, job, onSaved) {
  for (const section of article.querySelectorAll("section[data-index]")) {
    // 좁은 화면에서는 연필 아이콘만 보인다(css/responsive.css).
    const edit = el(
      "button",
      { class: "button soft edit-button", type: "button", "aria-label": "수정", onclick: () => startEditing(section, job, onSaved) },
      icon("pencil"),
      el("span", { class: "edit-label", text: "수정" }),
    );
    section.querySelector(".section-actions").append(edit);
  }
}
