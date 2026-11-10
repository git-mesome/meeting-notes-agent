/* 회의를 올린 사람, 참석자, 공개 범위. 참석자는 올린 사람이 정한다(jobs/access.py). */

import { api, jsonOptions } from "./api.js";
import { button, el, openSheet, toast } from "./ui.js";

/* 회의록 머리글에 붙는 한 줄. 로그인을 켜기 전에 올린 회의는 올린 사람이 없어 비운다. */
export function peopleLine(job) {
  if (!job.owner) return null;
  const parts = [`올린 사람 ${job.owner.name}`];
  if (job.attendees.length) parts.push(`참석자 ${job.attendees.map((person) => person.name).join(", ")}`);
  if (job.private) parts.push("참석자만 보기");
  return el("span", { class: "meta people-line", text: parts.join(" · ") });
}

/* 참석자와 "참석자만 보기"를 정하는 창. 저장하면 onSaved(최신 작업)를 부른다. */
export async function openPeopleSheet(job, onSaved) {
  let users;
  try {
    users = await api("/api/users");
  } catch (error) {
    toast(error.message, true);
    return;
  }
  const chosen = new Set(job.attendees.map((person) => person.sub));
  const rows = users
    .filter((person) => person.sub !== job.owner?.sub)
    .map((person) => {
      const box = el("input", { type: "checkbox", value: person.sub });
      box.checked = chosen.has(person.sub);
      return el("li", { "data-name": person.name }, el("label", { class: "person-row" }, box, el("span", { text: person.name })));
    });
  const list = el("ul", { class: "people-list" }, ...rows);
  // 사람이 많으면 이름으로 좁혀 고른다.
  const filter = el("input", { class: "text-input", type: "search", placeholder: "이름으로 찾기", "aria-label": "이름으로 찾기" });
  filter.addEventListener("input", () => {
    const query = filter.value.trim();
    for (const row of rows) row.hidden = Boolean(query) && !row.dataset.name.includes(query);
  });
  const privateBox = el("input", { type: "checkbox", id: "private-meeting" });
  privateBox.checked = job.private;

  openSheet((close) => {
    const save = button("저장", {
      variant: "primary",
      onclick: async () => {
        save.disabled = true;
        const attendees = [...list.querySelectorAll("input:checked")].map((box) => box.value);
        try {
          const updated = await api(`/api/jobs/${job.id}/access`, jsonOptions("PUT", { attendees, private: privateBox.checked }));
          close();
          toast("참석자와 공개 범위를 바꿨어요");
          onSaved(updated);
        } catch (error) {
          toast(error.message, true);
          save.disabled = false;
        }
      },
    });
    return [
      el("h2", { text: "참석자와 공개 범위" }),
      el("p", { text: "참석자는 이 회의록을 함께 고칠 수 있어요. 이 사이트에 한 번 이상 로그인한 사람만 고를 수 있어요." }),
      rows.length > 8 ? filter : null,
      rows.length
        ? list
        : el("p", { class: "empty", text: "아직 고를 사람이 없어요. 참석자가 이 사이트에 한 번 로그인하면 여기에 나타나요." }),
      el(
        "label",
        { class: "check-row", for: "private-meeting" },
        privateBox,
        el(
          "span",
          {},
          el("strong", { text: "참석자만 보기" }),
          el("small", { text: "켜면 올린 사람과 참석자, 관리자만 이 회의를 보고 검색할 수 있어요." }),
        ),
      ),
      el("div", { class: "sheet-actions" }, button("취소", { onclick: close }), save),
    ];
  });
}
