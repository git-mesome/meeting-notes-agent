/* 회의록 마크다운 표시와 수정. HTML을 넣지 않고 DOM으로 만들어 스크립트 삽입을 막는다. */

import { api, jsonOptions } from "./api.js";
import { renderDetail } from "./detail.js";
import { parseClock } from "./format.js";
import { setScreen } from "./screen.js";
import { TIME_REF, state } from "./state.js";
import { button, confirmSheet, el, toast } from "./ui.js";

/* 마크다운 표시: 회의록에 쓰는 문법만 처리하고 DOM으로 만들어 HTML 삽입을 막는다 */

export function inline(text, onTime) {
  const parts = [];
  const pattern = /(\*\*[^*]+\*\*|\[\d{1,2}:\d{2}(?::\d{2})?\])/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    parts.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("**")) {
      parts.push(el("strong", {}, ...inline(token.slice(2, -2), onTime)));
    } else {
      const time = token.match(TIME_REF)[1];
      parts.push(
        el("button", {
          class: "time-ref",
          type: "button",
          text: time,
          "aria-label": `${time}부터 듣기`,
          onclick: () => onTime(parseClock(time)),
        }),
      );
    }
    last = match.index + token.length;
  }
  parts.push(text.slice(last));
  return parts;
}

export function tableRow(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

export function renderTable(lines, onTime) {
  const rows = lines.map(tableRow).filter((cells) => !cells.every((cell) => /^:?-+:?$/.test(cell)));
  const [head, ...body] = rows;
  return el(
    "table",
    {},
    el("thead", {}, el("tr", {}, ...head.map((cell) => el("th", { scope: "col", text: cell })))),
    el(
      "tbody",
      {},
      ...body.map((cells) =>
        el(
          "tr",
          {},
          ...cells.map((cell, index) => el("td", { "data-label": head[index] }, el("div", {}, ...inline(cell, onTime)))),
        ),
      ),
    ),
  );
}

// "확인 필요" 항목. 오른쪽 체크 상자로 직접 확인했는지 표시한다.
function checkItem(text, done, index, onTime, onCheck) {
  const box = el("input", { type: "checkbox", class: "check-box", "aria-label": "확인함" });
  box.checked = done;
  const item = el(
    "li",
    { class: `check-item${done ? " done" : ""}` },
    el("span", { class: "check-text" }, ...inline(text, onTime)),
    el("label", { class: "check-hit", "data-ui": "" }, box),
  );
  box.addEventListener("change", async () => {
    item.classList.toggle("done", box.checked);
    if (!onCheck) return;
    try {
      await onCheck(index, box.checked);
    } catch (error) {
      box.checked = !box.checked;
      item.classList.toggle("done", box.checked);
      toast(error.message, true);
    }
  });
  return item;
}

export function renderNotes(markdown, onTime, { onCheck } = {}) {
  const container = el("article", { class: "notes" });
  const lines = markdown.split("\n");
  let parent = null;
  let list = null;
  let ordered = null;
  let sectionIndex = -1;
  let checkIndex = -1;
  const section = (extra = "", index = null) => {
    parent = el("section", { class: `card ${extra}` });
    if (index !== null) parent.dataset.index = String(index);
    container.append(parent);
    return parent;
  };
  for (let index = 0; index < lines.length; index += 1) {
    const trimmed = lines[index].trim();
    if (!trimmed.startsWith("- ")) list = null;
    if (!/^\d+\.\s/.test(trimmed)) ordered = null;
    if (!trimmed || trimmed.startsWith("# ")) continue;
    if (trimmed.startsWith("## ")) {
      const heading = trimmed.slice(3);
      sectionIndex += 1;
      // 제목 줄 오른쪽(.section-actions)에 수정, 이슈 등록 같은 버튼이 붙는다.
      section(heading.startsWith("확인 필요") ? "check" : "", sectionIndex).append(
        el("div", { class: "section-head", "data-ui": "" }, el("h2", { text: heading }), el("div", { class: "section-actions" })),
      );
      continue;
    }
    const target = parent || section();
    if (trimmed.startsWith("### ")) {
      target.append(el("h3", {}, ...inline(trimmed.slice(4), onTime)));
    } else if (/^\d+\.\s/.test(trimmed)) {
      if (!ordered) {
        ordered = el("ol");
        target.append(ordered);
      }
      ordered.append(el("li", {}, ...inline(trimmed.replace(/^\d+\.\s/, ""), onTime)));
    } else if (trimmed.startsWith("- ")) {
      if (!list) {
        list = el("ul");
        target.append(list);
      }
      if (target.classList.contains("check")) {
        checkIndex += 1;
        const marker = trimmed.slice(2).match(/^\[([ xX])\]\s*/);
        const text = marker ? trimmed.slice(2 + marker[0].length) : trimmed.slice(2);
        list.append(checkItem(text, Boolean(marker) && marker[1] !== " ", checkIndex, onTime, onCheck));
      } else {
        list.append(el("li", {}, ...inline(trimmed.slice(2), onTime)));
      }
    } else if (trimmed.startsWith("|")) {
      const tableLines = [];
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        tableLines.push(lines[index]);
        index += 1;
      }
      index -= 1;
      target.append(renderTable(tableLines, onTime));
    } else {
      target.append(el("p", {}, ...inline(trimmed, onTime)));
    }
  }
  return container;
}

// 화면에는 화자 라벨 대신 이름을 보여 준다. 저장할 때는 아직 정하지 않은 "화자 N"만 원래 라벨로 되돌려,
// 나중에 이름을 정해도 본문에 반영되게 한다.
export function storedText(job) {
  const defaults = job.speakers
    .filter((item) => item.known && !item.custom)
    .sort((a, b) => b.default_name.length - a.default_name.length);
  return (text) => defaults.reduce((result, item) => result.replaceAll(item.default_name, item.label), text);
}

export function renderEditor(job) {
  const page = setScreen({
    right: el("button", {
      class: "text-link",
      type: "button",
      text: "취소",
      onclick: async () => {
        if (state.unsaved) {
          const agreed = await confirmSheet({
            title: "수정을 그만둘까요?",
            body: "저장하지 않은 내용은 사라져요.",
            action: "그만두기",
            danger: true,
          });
          if (!agreed) return;
        }
        renderDetail(job);
      },
    }),
  });
  const names = new Map(job.speakers.map((item) => [item.label, item.name]));
  const shown = job.notes.replace(/SPEAKER_\d+/g, (label) => names.get(label) || label);
  const toStored = storedText(job);

  const area = el("textarea", { "aria-label": "회의록 내용" });
  area.value = shown;
  area.addEventListener("input", () => {
    state.unsaved = area.value !== shown;
  });
  const save = button("저장하기", {
    variant: "primary",
    onclick: async () => {
      save.disabled = true;
      try {
        const updated = await api(`/api/jobs/${job.id}/notes`, jsonOptions("PUT", { notes: toStored(area.value) }));
        toast("저장했어요");
        renderDetail(updated);
      } catch (error) {
        toast(error.message, true);
        save.disabled = false;
      }
    },
  });
  page.append(
    el("div", { class: "editor" }, area),
    el("div", { class: "bottom-bar" }, el("div", { class: "bottom-bar-inner" }, save)),
  );
}

