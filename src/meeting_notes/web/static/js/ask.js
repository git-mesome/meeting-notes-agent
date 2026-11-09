/* 회의 내용 질문. */

import { api, jsonOptions } from "./api.js";
import { el, icon, toast } from "./ui.js";

export function renderAsk(job, seek, friendly) {
  const history = el("div", { class: "qa-list" });
  const addItem = (question, answerNodes) => {
    const answer = el("div", { class: "qa-answer" }, ...answerNodes);
    const item = el("div", { class: "qa-item" }, el("p", { class: "qa-question", text: question }), answer);
    history.append(item);
    return { item, answer };
  };
  const answerNodes = (text) =>
    friendly(text)
      .split("\n")
      .filter((line) => line.trim())
      .map((line) => el("p", {}, ...inline(line, seek)));
  for (const item of job.questions) addItem(item.question, answerNodes(item.answer));

  const input = el("input", {
    class: "text-input qa-input",
    type: "text",
    maxlength: 500,
    placeholder: "회의 내용을 물어보세요",
    "aria-label": "질문",
    autocomplete: "off",
    enterkeyhint: "send",
  });
  const send = el(
    "button",
    { class: "qa-send", type: "submit", "aria-label": "질문 보내기" },
    icon("send"),
  );
  const ask = async (question) => {
    const pending = addItem(question, [el("p", { class: "qa-pending", text: "답을 찾고 있어요" })]);
    suggestions.hidden = true;
    send.disabled = true;
    pending.item.scrollIntoView({ block: "nearest" });
    try {
      const result = await api(`/api/jobs/${job.id}/ask`, jsonOptions("POST", { question }));
      pending.answer.replaceChildren(...answerNodes(result.answer));
    } catch (error) {
      pending.item.remove();
      toast(error.message, true);
      input.value = question;
    }
    send.disabled = false;
  };
  const suggestions = el(
    "div",
    { class: "chips qa-suggestions", hidden: job.questions.length > 0 },
    ...["결정된 내용만 알려 줘", "누가 무슨 일을 맡았어?", "아직 정해지지 않은 건 뭐야?"].map((text) =>
      el("button", { class: "chip", type: "button", text, onclick: () => ask(text) }),
    ),
  );
  const form = el(
    "form",
    {
      class: "qa-form",
      onsubmit: (event) => {
        event.preventDefault();
        const question = input.value.trim();
        if (!question || send.disabled) return;
        input.value = "";
        ask(question);
      },
    },
    input,
    send,
  );
  return el(
    "section",
    { class: "card ask" },
    el("h2", { text: "회의에 대해 물어보세요" }),
    el("p", { class: "ask-note", text: "답변에는 근거 시각이 함께 나와요. 질문할 때마다 API 비용이 조금 들어요." }),
    history,
    suggestions,
    form,
  );
}

