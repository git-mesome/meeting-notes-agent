/* 등록한 이름·표기: 확인 필요 항목에서 바로잡아 등록한 내용. 다음 회의록과 질문 답변에 참고 메모로 넘긴다. */

import { api } from "./api.js";
import { dateText } from "./format.js";
import { setScreen } from "./screen.js";
import { button, confirmSheet, el, toast } from "./ui.js";

export async function renderMemory() {
  const page = setScreen({ back: true });
  const items = await api("/api/memory");
  const rows = items.map((item) =>
    el(
      "li",
      { class: "voice-row" },
      el(
        "div",
        {},
        el("span", { class: "note-title", text: item.question }),
        el("span", { class: "meta", text: `확인: ${item.answer} · ${dateText(item.created_at)}` }),
      ),
      button("삭제", {
        onclick: async () => {
          const agreed = await confirmSheet({
            title: "이 표기를 지울까요?",
            body: "다음 회의록부터 이 내용을 참고하지 않아요. 지금까지 만든 회의록은 그대로예요.",
            action: "지우기",
            danger: true,
          });
          if (!agreed) return;
          try {
            await api(`/api/memory/${item.id}`, { method: "DELETE" });
            toast("지웠어요");
            renderMemory();
          } catch (error) {
            toast(error.message, true);
          }
        },
      }),
    ),
  );
  page.append(
    el(
      "section",
      { class: "hero" },
      el("h1", { text: "등록한 이름·표기" }),
      el("p", { text: "확인 필요 항목에서 바로잡은 이름과 표기예요. 다음 회의록을 쓰고 질문에 답할 때 참고 메모로 함께 넘겨요." }),
    ),
    el(
      "div",
      { class: "card" },
      rows.length
        ? el("ul", { class: "note-list" }, ...rows)
        : el("p", {
            class: "empty",
            text: "아직 등록한 이름·표기가 없어요. 회의록의 확인 필요 항목을 체크할 때 등록할 수 있어요.",
          }),
    ),
    el("p", {
      class: "hint",
      text: "AI 모델을 다시 학습시키지는 않아요. 회의에 나오지 않은 내용을 회의록에 새로 넣지도 않아요. 잘못 등록한 내용은 지워 주세요.",
    }),
  );
}
