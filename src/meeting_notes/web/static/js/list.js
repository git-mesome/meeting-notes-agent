/* 첫 화면: 녹음 올리기, 양식 고르기, 검색, 회의 목록. */

import { api, loadTemplates, uploadFiles } from "./api.js";
import { badge, clock, dateText, detailText, displayName, headline, isActive, isWorking, metaText, progress, spanOfTime } from "./format.js";
import { pushCard } from "./push.js";
import { setScreen } from "./screen.js";
import { ACCEPT, MAX_RECORDINGS, POLL_MS, state } from "./state.js";
import { button, el, icon, meter, openSheet, toast } from "./ui.js";

/* 목록 */

export function templateChips(templates) {
  const chips = templates.map((template) =>
    el("button", {
      class: "chip",
      type: "button",
      text: template.label,
      "aria-pressed": String(template.key === state.selectedTemplate),
      onclick: (event) => {
        state.selectedTemplate = template.key;
        for (const chip of chips) chip.setAttribute("aria-pressed", String(chip === event.currentTarget));
        hint.textContent = template.description;
      },
    }),
  );
  const current = templates.find((template) => template.key === state.selectedTemplate);
  const hint = el("p", { class: "chip-hint", text: current ? current.description : "" });
  return el(
    "div",
    { class: "template-picker" },
    el("div", { class: "chips", role: "group", "aria-label": "회의 종류" }, ...chips),
    hint,
  );
}

/* 녹음을 여럿 고르면 이을 순서를 확인받는다. 이름 순서로 놓고 위로 올려 바꾼다. 취소하면 null. */
function orderSheet(files) {
  const stem = (file) => file.name.replace(/\.[^.]+$/, "");
  const order = [...files].sort((a, b) => stem(a).localeCompare(stem(b), "ko", { numeric: true }));
  const list = el("ol", { class: "note-list document-list" });
  const render = () =>
    list.replaceChildren(
      ...order.map((file, index) =>
        el(
          "li",
          { class: "voice-row" },
          el("span", { class: "document-text" }, el("span", { class: "note-title", text: `${index + 1}. ${file.name}` })),
          index
            ? button("위로", {
                onclick: () => {
                  [order[index - 1], order[index]] = [order[index], order[index - 1]];
                  render();
                },
              })
            : null,
        ),
      ),
    );
  render();
  return new Promise((resolve) => {
    let result = null;
    const sheet = openSheet((close) => [
      el("h2", { text: `녹음 ${files.length}개로 회의록 하나를 만들까요?` }),
      el("p", { text: "이 순서대로 이어서 글로 옮겨요. 순서가 다르면 바꿔 주세요." }),
      list,
      el(
        "div",
        { class: "sheet-actions" },
        button("취소", { onclick: close }),
        button("올리기", {
          variant: "primary",
          onclick: () => {
            result = order;
            close();
          },
        }),
      ),
    ]);
    sheet.addEventListener("close", () => resolve(result));
  });
}

export function uploadSection(onUploaded) {
  const meterBox = el("div", { class: "upload-meter" });
  const input = el("input", { type: "file", accept: ACCEPT, multiple: true, id: "audio-file" });
  const labelText = el("span", { text: "녹음 올리기" });
  const label = el("label", { class: "upload-button", for: "audio-file" }, icon("upload"), labelText);

  input.addEventListener("change", async () => {
    let files = [...input.files];
    if (files.length > MAX_RECORDINGS) {
      toast(`녹음은 한 회의에 ${MAX_RECORDINGS}개까지 올릴 수 있어요.`, true);
      files = [];
    } else if (files.length > 1) {
      files = (await orderSheet(files)) || [];
    }
    if (!files.length) {
      input.value = "";
      return;
    }
    input.disabled = true;
    label.setAttribute("aria-disabled", "true");
    labelText.textContent = "올리는 중";
    const fill = el("div", { class: "meter-fill" });
    fill.style.width = "0%";
    meterBox.replaceChildren(el("div", { class: "meter" }, fill));

    try {
      await uploadFiles(`/api/jobs?template=${encodeURIComponent(state.selectedTemplate)}`, files, (fraction) => {
        const percent = Math.round(fraction * 100);
        fill.style.width = `${percent}%`;
        labelText.textContent = percent < 100 ? `올리는 중 ${percent}%` : "파일을 확인하는 중";
      });
      toast("올렸어요. 다 되면 여기에 나타나요");
      onUploaded();
    } catch (error) {
      toast(error.message, true);
    } finally {
      input.disabled = false;
      input.value = "";
      label.removeAttribute("aria-disabled");
      labelText.textContent = "녹음 올리기";
      meterBox.replaceChildren();
    }
  });

  return el("div", { class: "upload" }, input, el("div", { class: "upload-bar" }, meterBox, label));
}

export function noteRow(job) {
  const body = el(
    "div",
    {},
    el("span", { class: "note-title", text: displayName(job) }),
    el("span", { class: "meta", text: metaText(job) }),
  );
  if (isWorking(job)) body.append(meter(progress(job)));
  if (job.status !== "done") {
    const summary = [headline(job), detailText(job)].filter(Boolean).join(", ");
    const tone = job.status === "failed" ? "failed" : job.status === "canceled" ? "quiet" : "";
    body.append(el("div", { class: `note-state ${tone}`, text: job.status === "failed" ? headline(job) : summary }));
  }
  return el("li", {}, el("a", { class: "note-row", href: `#/jobs/${job.id}` }, body, badge(job), icon("next")));
}

export function highlighted(text, query) {
  const letters = [...query].filter((char) => char.trim()).map((char) => char.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!letters.length) return [text];
  const pattern = new RegExp(letters.join("\\s*"), "gi");
  const parts = [];
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    parts.push(text.slice(last, match.index), el("mark", { text: match[0] }));
    last = match.index + match[0].length;
  }
  parts.push(text.slice(last));
  return parts;
}

export function searchResult(result, query) {
  const rows = [];
  if (result.notes) {
    rows.push(
      el(
        "a",
        { class: "search-hit", href: `#/jobs/${result.id}` },
        el("span", { class: "search-tag", text: "회의록" }),
        el("span", {}, ...highlighted(result.notes, query)),
      ),
    );
  }
  for (const hit of result.hits) {
    rows.push(
      el(
        "a",
        { class: "search-hit", href: `#/jobs/${result.id}?t=${Math.floor(hit.start)}` },
        el("span", { class: "search-tag", text: clock(hit.start) }),
        el("span", {}, `${hit.speaker}: `, ...highlighted(hit.text, query)),
      ),
    );
  }
  const extra = result.hit_count - result.hits.length;
  return el(
    "div",
    { class: "card search-result" },
    el(
      "a",
      { class: "search-title", href: `#/jobs/${result.id}` },
      el("span", { class: "note-title" }, ...highlighted(result.title, query)),
      el("span", { class: "meta", text: `${dateText(result.created_at)}, ${spanOfTime(result.duration_seconds)} 녹음` }),
    ),
    ...rows,
    extra > 0 ? el("p", { class: "search-more", text: `전사문에서 ${extra}곳 더 나왔어요` }) : null,
  );
}

export function searchBox(list) {
  const results = el("section", { class: "search-results", "aria-live": "polite", hidden: true });
  let timer = null;
  let latest = 0;
  const run = async (query) => {
    const ticket = ++latest;
    try {
      const found = await api(`/api/search?q=${encodeURIComponent(query)}`);
      if (ticket !== latest) return;
      results.replaceChildren(
        ...(found.length
          ? found.map((result) => searchResult(result, query))
          : [el("p", { class: "empty card", text: `'${query}'이 나온 회의가 없어요.` })]),
      );
    } catch (error) {
      if (ticket === latest) toast(error.message, true);
    }
  };
  const input = el("input", {
    class: "search-input",
    type: "search",
    placeholder: "지난 회의에서 찾기",
    "aria-label": "회의록 검색",
    autocomplete: "off",
    enterkeyhint: "search",
    oninput: () => {
      clearTimeout(timer);
      const query = input.value.trim();
      results.hidden = !query;
      list.hidden = Boolean(query);
      if (!query) {
        latest += 1;
        results.replaceChildren();
        return;
      }
      timer = setTimeout(() => run(query), 250);
    },
  });
  return {
    box: el("label", { class: "search-box" }, icon("search"), input),
    results,
  };
}

export async function renderList() {
  const me = await api("/api/me").catch(() => ({ login: false }));
  const page = setScreen({
    right: me.login ? el("a", { class: "user-link", href: "/auth/logout" }, el("span", { text: me.name }), "로그아웃") : null,
  });
  const list = el("section", { "aria-label": "내 회의록" });
  const search = searchBox(list);
  const refresh = async () => {
    clearTimeout(state.pollTimer);
    let jobs;
    try {
      jobs = await api("/api/jobs");
    } catch (error) {
      // 핸드폰 연결이 잠깐 끊겨도 다시 받아 온다.
      state.pollTimer = setTimeout(refresh, POLL_MS);
      if (list.childElementCount) return;
      throw error;
    }
    const ordered = [...jobs.filter(isActive), ...jobs.filter((job) => !isActive(job))];
    list.replaceChildren(
      el("h2", { class: "section-title", text: "내 회의록" }),
      el(
        "div",
        { class: "card" },
        ordered.length
          ? el("ul", { class: "note-list" }, ...ordered.map(noteRow))
          : el("p", { class: "empty", text: "아직 회의록이 없어요. 첫 녹음을 올려 보세요." }),
      ),
      el("p", {
        class: "hint",
        text:
          "아이폰 음성 메모는 '파일에 저장'한 뒤 고르거나, 아이폰 단축어로 바로 올릴 수 있어요. " +
          "녹음이 여러 개로 나뉘었으면 함께 고르거나, 회의록 더보기에서 나중에 더 올려요.",
      }),
      el(
        "div",
        { class: "manage-links" },
        el("a", { class: "manage-link", href: "#/voices" }, icon("voice"), "등록한 목소리 관리"),
        el("a", { class: "manage-link", href: "#/memory" }, icon("check"), "등록한 이름·표기 관리"),
        el("a", { class: "manage-link", href: "#/shortcut" }, icon("phone"), "아이폰 단축어"),
      ),
    );
    if (jobs.some(isActive)) state.pollTimer = setTimeout(refresh, POLL_MS);
  };
  const title = el("h1", {}, "녹음만 올리면", el("br"), "회의록이 완성돼요");
  const templates = await loadTemplates();
  page.append(
    el(
      "section",
      { class: "hero" },
      title,
      el("p", { text: "누가 무슨 말을 했는지 정리해 초안까지 만들어 드려요." }),
      templateChips(templates),
      uploadSection(refresh),
    ),
    pushCard(),
    search.box,
    search.results,
    list,
  );
  await refresh();
}

