/* 아이폰 단축어 설정 안내와 업로드 키. 단축어는 로그인을 할 수 없어 키로 누가 올렸는지 알린다(auth/upload_keys.py). */

import { api } from "./api.js";
import { dateText } from "./format.js";
import { setScreen } from "./screen.js";
import { button, confirmSheet, el, toast } from "./ui.js";

// HTTP 주소에서는 클립보드를 쓸 수 없어, 글자를 골라 두고 길게 눌러 복사하게 한다.
function copyField(value, label) {
  const input = el("input", {
    class: "text-input copy-input",
    type: "text",
    readonly: true,
    value,
    "aria-label": label,
    onfocus: (event) => event.target.select(),
  });
  const copy = button("복사", {
    onclick: async () => {
      try {
        await navigator.clipboard.writeText(value);
        toast("복사했어요");
      } catch {
        input.focus();
        toast("글자를 길게 눌러 복사해 주세요");
      }
    },
  });
  return el("div", { class: "copy-field" }, input, copy);
}

function keyCard(createdAt, fresh) {
  const issue = async () => {
    if (createdAt) {
      const agreed = await confirmSheet({
        title: "키를 새로 받을까요?",
        body: "지금 단축어에 넣은 키는 더 이상 쓸 수 없어요. 새 키를 단축어에 다시 넣어야 해요.",
        action: "새로 받기",
      });
      if (!agreed) return;
    }
    try {
      renderShortcut(await api("/api/upload-key", { method: "POST" }));
    } catch (error) {
      toast(error.message, true);
    }
  };
  const revoke = async () => {
    const agreed = await confirmSheet({
      title: "키를 지울까요?",
      body: "이 키를 넣은 단축어로는 더 이상 올릴 수 없어요.",
      action: "지우기",
      danger: true,
    });
    if (!agreed) return;
    try {
      await api("/api/upload-key", { method: "DELETE" });
      toast("지웠어요");
      renderShortcut();
    } catch (error) {
      toast(error.message, true);
    }
  };

  let body;
  if (fresh) {
    body = [
      copyField(`Bearer ${fresh.key}`, "업로드 키"),
      el("p", { class: "input-hint", text: "이 화면을 떠나면 키를 다시 볼 수 없어요. 단축어에 넣은 뒤에 나가 주세요." }),
    ];
  } else if (createdAt) {
    body = [
      el("p", { class: "meta", text: `${dateText(createdAt)}에 받은 키를 쓰고 있어요.` }),
      el("div", { class: "key-actions" }, button("새로 받기", { onclick: issue }), button("지우기", { variant: "quiet", onclick: revoke })),
    ];
  } else {
    body = [el("div", { class: "key-actions" }, button("키 받기", { variant: "primary", onclick: issue }))];
  }
  return el(
    "section",
    { class: "card shortcut-card" },
    el("h2", { text: "업로드 키" }),
    el("p", { text: "단축어로 올린 녹음은 키를 받은 사람이 올린 회의가 돼요. 이 키로는 녹음을 올리는 일만 할 수 있어요." }),
    ...body,
  );
}

/* fresh는 방금 받은 키다. 받은 화면에서만 원문을 보여 준다. */
export async function renderShortcut(fresh = null) {
  const page = setScreen({ back: true });
  const me = await api("/api/me");
  const createdAt = me.login ? fresh?.created_at || (await api("/api/upload-key")).created_at : null;
  const steps = [
    el("li", { text: "단축어 앱에서 새 단축어를 만들고, 단축어 설정에서 '공유 시트에 표시'를 켜요." }),
    el("li", {}, "'URL 콘텐츠 가져오기' 동작을 넣고 URL에 아래 주소를 넣어요.", copyField(`${location.origin}/api/jobs`, "올릴 주소")),
    el("li", { text: "방법은 POST, 요청 본문은 '파일'로 바꾸고 파일에 '단축어 입력'을 넣어요." }),
    me.login ? el("li", { text: "헤더를 하나 추가해 키에 Authorization, 값에 위에서 받은 업로드 키를 넣어요." }) : null,
    el("li", { text: "음성 메모에서 녹음을 열고 공유 버튼을 눌러 만든 단축어를 고르면 올라가요." }),
  ];
  page.append(
    el(
      "section",
      { class: "hero" },
      el("h1", { text: "아이폰 단축어로 올리기" }),
      el("p", { text: "음성 메모의 공유 버튼에서 바로 회의록을 올리는 단축어를 만들어요." }),
    ),
    // append는 null을 "null" 글자로 넣으므로 빼고 넘긴다.
    ...[me.login ? keyCard(createdAt, fresh) : null].filter(Boolean),
    el("section", { class: "card shortcut-card" }, el("h2", { text: "단축어 만들기" }), el("ol", { class: "shortcut-steps" }, ...steps)),
    el("p", { class: "hint", text: "회의 종류는 '일반 회의'로 올라가요. 회의록을 연 뒤 더보기에서 다른 양식으로 다시 쓸 수 있어요." }),
  );
}
