/* 등록한 목소리 관리 화면. 목소리는 모두 같이 쓰고, 지우기는 등록한 사람과 관리자만 한다(speakers/voices.py). */

import { api } from "./api.js";
import { dateText } from "./format.js";
import { setScreen } from "./screen.js";
import { button, confirmSheet, el, toast } from "./ui.js";

/* 등록한 목소리 */

export async function renderVoices() {
  const page = setScreen({ back: true });
  const voices = await api("/api/voices");
  const rows = voices.map((voice) =>
    el(
      "li",
      { class: "voice-row" },
      el(
        "div",
        {},
        el("span", { class: "note-title", text: voice.name }),
        el("span", { class: "meta", text: voiceMeta(voice) }),
      ),
      // 지울 수 없는 사람에게는 삭제 버튼을 보이지 않는다.
      voice.can_delete ? deleteButton(voice) : null,
    ),
  );
  const locked = voices.some((voice) => !voice.can_delete);
  page.append(
    el(
      "section",
      { class: "hero" },
      el("h1", { text: "등록한 목소리" }),
      el("p", { text: "여기 있는 사람은 누가 올린 회의든 자동으로 이름이 붙어요. 목소리 특징은 회의록 서버 밖으로 보내지 않아요." }),
    ),
    el(
      "div",
      { class: "card" },
      rows.length
        ? el("ul", { class: "note-list" }, ...rows)
        : el("p", {
            class: "empty",
            text: "아직 등록한 목소리가 없어요. 회의록에서 화자 이름을 바꿀 때 등록할 수 있어요.",
          }),
    ),
    el("p", {
      class: "hint",
      text: locked
        ? "목소리는 생체 정보예요. 본인 동의를 받은 사람만 등록해 주세요. 다른 사람이 등록한 목소리는 등록한 사람이나 관리자에게 지워 달라고 해 주세요."
        : "목소리는 생체 정보예요. 본인 동의를 받은 사람만 등록해 주세요.",
    }),
  );
}

function voiceMeta(voice) {
  const by = voice.owner ? `${voice.owner.name}님이 ` : "";
  return `${by}회의 ${voice.samples}건에서 등록, ${dateText(voice.updated_at)}`;
}

function deleteButton(voice) {
  return button("삭제", {
    onclick: async () => {
      const agreed = await confirmSheet({
        title: `${voice.name}님의 목소리를 지울까요?`,
        body: "다음 회의부터 자동으로 알아보지 않아요. 이미 정한 이름은 그대로예요.",
        action: "지우기",
        danger: true,
      });
      if (!agreed) return;
      try {
        await api(`/api/voices/${voice.id}`, { method: "DELETE" });
        toast("지웠어요");
        renderVoices();
      } catch (error) {
        toast(error.message, true);
      }
    },
  });
}
