/* 회의록을 만든 뒤 녹음 더 올리기. 새 녹음만 글로 옮겨 뒤에 잇고 회의록은 다시 쓴다(pipeline/recordings.py). */

import { uploadFiles } from "./api.js";
import { route } from "./router.js";
import { ACCEPT } from "./state.js";
import { confirmSheet, el, openSheet, toast } from "./ui.js";

async function send(job, file) {
  const agreed = await confirmSheet({
    title: "이 회의 뒤에 녹음을 이어 붙일까요?",
    body: `'${file.name}'만 새로 글로 옮겨 붙이고 회의록은 다시 써요. 직접 고친 내용은 사라지고, 정해 둔 화자 이름은 그대로예요. API 비용이 들어요.`,
    action: "이어 붙이기",
  });
  if (!agreed) return;
  const fill = el("div", { class: "meter-fill" });
  fill.style.width = "0%";
  const status = el("p", { text: "올리는 중 0%" });
  const sheet = openSheet(() => [
    el("h2", { text: "녹음을 올리고 있어요" }),
    status,
    el("div", { class: "meter sheet-meter" }, fill),
  ]);
  let failure = null;
  try {
    await uploadFiles(`/api/jobs/${job.id}/recordings`, [file], (fraction) => {
      const percent = Math.round(fraction * 100);
      fill.style.width = `${percent}%`;
      status.textContent = percent < 100 ? `올리는 중 ${percent}%` : "파일을 확인하는 중";
    });
  } catch (error) {
    failure = error;
  }
  // 알림은 열린 창 안에 붙으므로 창을 먼저 닫아야 알림이 함께 사라지지 않는다.
  sheet.close();
  if (failure) {
    toast(failure.message, true);
    return;
  }
  toast("올렸어요. 새 녹음을 글로 옮긴 뒤 회의록을 다시 써요");
  route();
}

/* 더보기 메뉴를 누른 동작 안에서 파일 고르기를 연다. 아이폰은 문서에 붙은 입력란만 열어 준다. */
export function pickRecording(job) {
  const input = el("input", { class: "document-picker", type: "file", accept: ACCEPT });
  input.addEventListener("change", () => {
    const file = input.files[0];
    input.remove();
    if (file) send(job, file);
  });
  input.addEventListener("cancel", () => input.remove());
  document.body.append(input);
  input.click();
}
