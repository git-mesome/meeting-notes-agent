import { ApiError, api } from "./api.js";
import { renderDetail } from "./detail.js";
import { renderList } from "./list.js";
import { setScreen } from "./screen.js";
import { el } from "./ui.js";
import { renderMemory } from "./memory.js";
import { renderShortcut } from "./shortcut.js";
import { renderVoices } from "./voices.js";
import { renderWaiting } from "./waiting.js";

/* 화면 전환: 주소(#/...)에 맞는 화면을 그린다 */

export function showError(message) {
  const page = setScreen({ back: true });
  page.append(el("p", { class: "page-message", role: "alert", text: message }));
}

export async function route() {
  document.querySelectorAll("dialog.sheet").forEach((sheet) => sheet.close());
  const match = location.hash.match(/^#\/jobs\/([0-9a-f]{32})(?:\?(t=\d+|issues=1))?$/);
  try {
    if (location.hash === "#/voices") {
      await renderVoices();
      return;
    }
    if (location.hash === "#/memory") {
      await renderMemory();
      return;
    }
    if (location.hash === "#/shortcut") {
      await renderShortcut();
      return;
    }
    if (!match) {
      await renderList();
      return;
    }
    const job = await api(`/api/jobs/${match[1]}`);
    const params = new URLSearchParams(match[2] || "");
    if (params.has("issues")) history.replaceState(null, "", `#/jobs/${job.id}`);
    if (job.status === "done") {
      renderDetail(job, { startAt: params.has("t") ? Number(params.get("t")) : null, openIssues: params.has("issues") });
    } else {
      renderWaiting(job);
    }
  } catch (error) {
    if (error instanceof ApiError) {
      showError(error.message);
    } else {
      showError("노트북에 연결할 수 없어요. 노트북과 Tailscale이 켜져 있는지 확인한 뒤 새로고침해 주세요.");
    }
  }
}
