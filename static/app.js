"use strict";

const root = document.getElementById("app");
const POLL_MS = 5000;
const ACCEPT = ".m4a,.mp3,.wav,.flac,.ogg,.aac,.mp4,.webm,audio/*";
const TIME_REF = /\[(\d{1,2}:\d{2}(?::\d{2})?)\]/;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const SVG_NS = "http://www.w3.org/2000/svg";

const ICONS = {
  upload: "M12 16V4m0 0L7 9m5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
  check: "M5 12.5 10 17.5 19 7.5",
  pencil: "M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4",
  download: "M12 4v12m0 0 5-5m-5 5-5-5M4 20h16",
  trash: "M4 7h16M10 11v6m4-6v6M6 7l1 13h10l1-13M9 7V4h6v3",
  back: "M15 5l-7 7 7 7",
  next: "M9 5l7 7-7 7",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
  bell: "M6 16V11a6 6 0 1 1 12 0v5l2 2H4zM10 21h4",
  voice: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  send: "M12 19V5m0 0l-6 6m6-6l6 6",
  rewrite: "M4 12a8 8 0 0 1 14-5.3L20 9m0-5v5h-5M20 12a8 8 0 0 1-14 5.3L4 15m0 5v-5h5",
  issue: "M9 4h6v3H9zM7 6H5v15h14V6h-2M9 14l2 2 4-4",
  play: "M8 5l11 7-11 7z",
  stop: "M7 7h10v10H7z",
  alert: "M12 8v5m0 3.5h.01M12 3l9.5 17h-19z",
};
const PLAY_ICON = "M7 4l13 8-13 8z";
const PAUSE_ICON = "M6 4h4v16H6zM14 4h4v16h-4z";

let pollTimer = null;
let cleanup = null;
let unsaved = false;
let templatesCache = null;
let trackerCache = null;

async function trackerStatus() {
  if (!trackerCache) trackerCache = await api("/api/tracker").catch(() => ({ enabled: false }));
  return trackerCache;
}

function issueKey(item) {
  if (!item.url) return el("span", { class: "issue-key", text: item.key });
  return el("a", { class: "issue-key", href: item.url, target: "_blank", rel: "noopener", text: item.key });
}
let selectedTemplate = "general";

async function loadTemplates() {
  if (!templatesCache) templatesCache = await api("/api/templates");
  return templatesCache;
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  node.append(...children.filter((child) => child !== null && child !== undefined));
  return node;
}

function icon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const shape = document.createElementNS(SVG_NS, "path");
  shape.setAttribute("d", ICONS[name]);
  svg.append(shape);
  return svg;
}

function button(label, { variant = "soft", onclick, disabled, iconName } = {}) {
  return el(
    "button",
    { class: `button ${variant}`, type: "button", onclick, disabled },
    iconName ? icon(iconName) : null,
    label,
  );
}

function toast(message, isError = false, action = null) {
  document.querySelector(".toast")?.remove();
  const node = el("div", { class: `toast ${isError ? "error" : ""}`, role: isError ? "alert" : "status" }, el("span", { text: message }));
  if (action) {
    node.append(
      el("button", {
        type: "button",
        class: "toast-action",
        text: action.label,
        onclick: () => {
          node.remove();
          action.onclick();
        },
      }),
    );
  }
  // 열린 창이 있으면 그 위에 보여야 가려지지 않는다.
  const openDialogs = document.querySelectorAll("dialog[open]");
  (openDialogs[openDialogs.length - 1] || document.body).append(node);
  setTimeout(() => node.remove(), action ? 10000 : isError ? 4500 : 2500);
}

/* 아래에서 올라오는 창 */

function openSheet(build) {
  const sheet = el("dialog", { class: "sheet" });
  const close = () => sheet.close();
  sheet.append(el("div", { class: "sheet-body" }, ...build(close)));
  sheet.addEventListener("click", (event) => {
    if (event.target === sheet) close();
  });
  sheet.addEventListener("close", () => sheet.remove());
  document.body.append(sheet);
  sheet.showModal();
  return sheet;
}

function confirmSheet({ title, body, action, danger = false }) {
  return new Promise((resolve) => {
    let result = false;
    const sheet = openSheet((close) => [
      el("h2", { text: title }),
      body ? el("p", { text: body }) : null,
      el(
        "div",
        { class: "sheet-actions" },
        button("취소", { onclick: close }),
        button(action, {
          variant: danger ? "danger" : "primary",
          onclick: () => {
            result = true;
            close();
          },
        }),
      ),
    ]);
    sheet.addEventListener("close", () => resolve(result));
  });
}

class ApiError extends Error {}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "요청을 처리하지 못했어요. 다시 시도해 주세요.";
    throw new ApiError(detail);
  }
  return body;
}

function jsonOptions(method, body) {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

function clock(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = String(total % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}` : `${String(minutes).padStart(2, "0")}:${secs}`;
}

function parseClock(text) {
  return text.split(":").reduce((sum, part) => sum * 60 + Number(part), 0);
}

function spanOfTime(seconds) {
  const minutes = Math.max(1, Math.round(seconds / 60));
  const hours = Math.floor(minutes / 60);
  if (!hours) return `${minutes}분`;
  return minutes % 60 ? `${hours}시간 ${minutes % 60}분` : `${hours}시간`;
}

function dateText(iso) {
  return new Intl.DateTimeFormat("ko-KR", {
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(iso));
}

function metaText(job) {
  return `${dateText(job.created_at)}, ${spanOfTime(job.duration_seconds)} 녹음`;
}

function displayName(job) {
  return job.title || job.name.replace(/\.[^.]+$/, "");
}

function headline(job) {
  if (job.status === "queued") return job.ahead ? "순서를 기다리고 있어요" : "곧 시작해요";
  if (job.status === "transcribing") return "말을 글로 옮기고 있어요";
  if (job.status === "writing") return "회의록을 쓰고 있어요";
  if (job.status === "canceled") return "처리를 멈췄어요";
  if (job.status === "failed") return "회의록을 만들지 못했어요";
  return "";
}

function detailText(job) {
  if (job.status === "queued") return job.ahead ? `앞에 ${job.ahead}건이 있어요` : "";
  if (job.status === "transcribing") {
    const left = job.estimated_seconds - job.elapsed_seconds;
    return left > 0 ? `약 ${spanOfTime(left)} 남았어요` : "예상보다 오래 걸리고 있어요";
  }
  if (job.status === "writing") return "거의 다 됐어요";
  if (job.status === "canceled") return `다시 시작하면 약 ${spanOfTime(job.estimated_seconds)} 걸려요`;
  if (job.status === "failed") return job.error;
  return "";
}

function progress(job) {
  if (job.status === "transcribing") return Math.min(0.95, job.elapsed_seconds / job.estimated_seconds);
  if (job.status === "writing") return 0.97;
  return 0;
}

function isActive(job) {
  return ["queued", "transcribing", "writing"].includes(job.status);
}

function isWorking(job) {
  return job.status === "transcribing" || job.status === "writing";
}

function meter(fraction) {
  const fill = el("div", { class: "meter-fill" });
  fill.style.width = `${Math.round(fraction * 100)}%`;
  return el("div", { class: "meter" }, fill);
}

function badge(job, animate = false) {
  if (job.status === "done" && job.confirmed_at) {
    return el("span", { class: `badge confirmed ${animate ? "pop" : ""}` }, icon("check"), "확정");
  }
  if (job.status === "done") return el("span", { class: "badge draft", text: "초안" });
  if (job.status === "failed") return el("span", { class: "badge failed", text: "실패" });
  if (job.status === "canceled") return el("span", { class: "badge", text: "멈춤" });
  if (job.status === "queued") return el("span", { class: "badge", text: "대기" });
  return el("span", { class: "badge working", text: "처리 중" });
}

function topbar({ back = false, right = null } = {}) {
  const left = back
    ? el("a", { class: "icon-button", href: "#/", "aria-label": "목록으로" }, icon("back"))
    : el("a", { class: "brand", href: "#/" }, el("img", { src: "/static/favicon.svg", alt: "" }), "회의록");
  return el("header", { class: "topbar" }, left, right);
}

function setScreen({ wide = false, back = false, right = null } = {}) {
  clearTimeout(pollTimer);
  if (cleanup) cleanup();
  cleanup = null;
  unsaved = false;
  const page = el("main", { class: wide ? "page wide" : "page" });
  root.replaceChildren(topbar({ back, right }), page);
  window.scrollTo(0, 0);
  return page;
}

async function deleteJob(job) {
  const agreed = await confirmSheet({
    title: "이 회의록을 삭제할까요?",
    body: "녹음과 전사문도 함께 지워지고, 되돌릴 수 없어요.",
    action: "삭제",
    danger: true,
  });
  if (!agreed) return;
  try {
    await api(`/api/jobs/${job.id}`, { method: "DELETE" });
    toast("삭제했어요");
    location.hash = "#/";
  } catch (error) {
    toast(error.message, true);
  }
}

/* 목록 */

function templateChips(templates) {
  const chips = templates.map((template) =>
    el("button", {
      class: "chip",
      type: "button",
      text: template.label,
      "aria-pressed": String(template.key === selectedTemplate),
      onclick: (event) => {
        selectedTemplate = template.key;
        for (const chip of chips) chip.setAttribute("aria-pressed", String(chip === event.currentTarget));
        hint.textContent = template.description;
      },
    }),
  );
  const current = templates.find((template) => template.key === selectedTemplate);
  const hint = el("p", { class: "chip-hint", text: current ? current.description : "" });
  return el(
    "div",
    { class: "template-picker" },
    el("div", { class: "chips", role: "group", "aria-label": "회의 종류" }, ...chips),
    hint,
  );
}

function uploadSection(onUploaded) {
  const meterBox = el("div", { class: "upload-meter" });
  const input = el("input", { type: "file", accept: ACCEPT, id: "audio-file" });
  const labelText = el("span", { text: "녹음 올리기" });
  const label = el("label", { class: "upload-button", for: "audio-file" }, icon("upload"), labelText);

  input.addEventListener("change", () => {
    const file = input.files[0];
    if (!file) return;
    input.disabled = true;
    label.setAttribute("aria-disabled", "true");
    labelText.textContent = "올리는 중";
    const fill = el("div", { class: "meter-fill" });
    fill.style.width = "0%";
    meterBox.replaceChildren(el("div", { class: "meter" }, fill));

    const finish = () => {
      input.disabled = false;
      input.value = "";
      label.removeAttribute("aria-disabled");
      labelText.textContent = "녹음 올리기";
      meterBox.replaceChildren();
    };

    const request = new XMLHttpRequest();
    request.open("POST", `/api/jobs?template=${encodeURIComponent(selectedTemplate)}`);
    request.responseType = "json";
    request.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable) return;
      const percent = Math.round((event.loaded / event.total) * 100);
      fill.style.width = `${percent}%`;
      labelText.textContent = percent < 100 ? `올리는 중 ${percent}%` : "파일을 확인하는 중";
    });
    request.addEventListener("load", () => {
      finish();
      if (request.status === 201) {
        toast("올렸어요. 다 되면 여기에 나타나요");
        onUploaded();
      } else {
        const detail = request.response && request.response.detail;
        toast(typeof detail === "string" ? detail : "파일을 올리지 못했어요. 다시 시도해 주세요.", true);
      }
    });
    request.addEventListener("error", () => {
      finish();
      toast("연결이 끊겼어요. 노트북이 켜져 있는지 확인해 주세요.", true);
    });
    const form = new FormData();
    form.append("file", file);
    request.send(form);
  });

  return el("div", { class: "upload" }, input, el("div", { class: "upload-bar" }, meterBox, label));
}

function noteRow(job) {
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

function highlighted(text, query) {
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

function searchResult(result, query) {
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

function searchBox(list) {
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

/* 완료 알림 */

function base64UrlToBytes(text) {
  const raw = atob(text.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(text.length / 4) * 4, "="));
  return Uint8Array.from(raw, (char) => char.charCodeAt(0));
}

async function pushStatus() {
  if (!window.isSecureContext) return "insecure";
  const standalone = window.navigator.standalone === true || window.matchMedia("(display-mode: standalone)").matches;
  const isIos = /iP(hone|ad|od)/.test(navigator.userAgent);
  if (isIos && !standalone) return "install";
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  const registration = await navigator.serviceWorker.register("/sw.js");
  const subscription = await registration.pushManager.getSubscription();
  return subscription ? "on" : "ready";
}

async function turnOnPush() {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    toast("알림을 허용해야 받을 수 있어요", true);
    return false;
  }
  const registration = await navigator.serviceWorker.ready;
  const { key } = await api("/api/push/key");
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: base64UrlToBytes(key),
  });
  const { endpoint, keys } = subscription.toJSON();
  await api("/api/push/subscribe", jsonOptions("POST", { endpoint, keys: { p256dh: keys.p256dh, auth: keys.auth } }));
  toast("이제 끝나면 알려 드릴게요");
  return true;
}

function pushCard() {
  const card = el("section", { class: "card push-card", hidden: true });
  const show = (title, body, action) => {
    card.replaceChildren(
      el("div", { class: "push-icon" }, icon("bell")),
      el("div", { class: "push-text" }, el("strong", { text: title }), body ? el("span", { text: body }) : null),
      action,
    );
    card.hidden = false;
  };
  pushStatus()
    .then((status) => {
      if (status === "ready") {
        const on = button("켜기", {
          variant: "primary",
          onclick: async () => {
            on.disabled = true;
            try {
              if (await turnOnPush()) card.hidden = true;
              else on.disabled = false;
            } catch (error) {
              toast("알림을 켜지 못했어요. 잠시 후 다시 시도해 주세요.", true);
              on.disabled = false;
            }
          },
        });
        show("다 되면 알려 드릴까요?", "오래 걸리는 회의도 기다리지 않아도 돼요.", on);
      } else if (status === "install") {
        show("다 되면 알림을 받아 보세요", "공유 버튼에서 '홈 화면에 추가'를 누른 뒤, 홈 화면의 회의록 앱에서 켤 수 있어요.");
      } else if (status === "insecure") {
        show("완료 알림은 HTTPS 주소에서 켤 수 있어요", "지금은 HTTP로 접속 중이에요.");
      } else if (status === "denied") {
        show("알림이 꺼져 있어요", "기기 설정에서 회의록 알림을 허용해 주세요.");
      }
    })
    .catch(() => {});
  return card;
}

async function renderList() {
  const page = setScreen();
  const list = el("section", { "aria-label": "내 회의록" });
  const search = searchBox(list);
  const refresh = async () => {
    clearTimeout(pollTimer);
    let jobs;
    try {
      jobs = await api("/api/jobs");
    } catch (error) {
      // 핸드폰 연결이 잠깐 끊겨도 다시 받아 온다.
      pollTimer = setTimeout(refresh, POLL_MS);
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
      el("p", { class: "hint", text: "아이폰 음성 메모는 공유 메뉴에서 '파일에 저장'한 뒤 고르면 돼요." }),
      el("a", { class: "manage-link", href: "#/voices" }, icon("voice"), "등록한 목소리 관리"),
    );
    if (jobs.some(isActive)) pollTimer = setTimeout(refresh, POLL_MS);
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

/* 마크다운 표시: 회의록에 쓰는 문법만 처리하고 DOM으로 만들어 HTML 삽입을 막는다 */

function inline(text, onTime) {
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

function tableRow(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function renderTable(lines, onTime) {
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

function renderNotes(markdown, onTime) {
  const container = el("article", { class: "notes" });
  const lines = markdown.split("\n");
  let parent = null;
  let list = null;
  let ordered = null;
  const section = (extra = "") => {
    parent = el("section", { class: `card ${extra}` });
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
      section(heading.startsWith("확인 필요") ? "check" : "").append(el("h2", { text: heading }));
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
      list.append(el("li", {}, ...inline(trimmed.slice(2), onTime)));
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

/* 상세 */

function renderRibbon(turns, duration, speakers, seek, onName) {
  const ribbon = el(
    "section",
    { class: "ribbon card" },
    el("h2", { text: "누가 얼마나 말했나요" }),
    el("p", { class: "ribbon-hint", text: "이름을 누르면 들어 보고 바꿀 수 있어요" }),
  );
  const cursors = [];
  for (const speaker of speakers.filter((item) => item.known)) {
    const track = el("div", {
      class: "ribbon-track",
      onclick: (event) => {
        const box = event.currentTarget.getBoundingClientRect();
        seek(((event.clientX - box.left) / box.width) * duration);
      },
    });
    for (const turn of turns.filter((item) => item.speaker === speaker.label)) {
      const block = el("i");
      block.style.left = `${(turn.start / duration) * 100}%`;
      block.style.width = `${((turn.end - turn.start) / duration) * 100}%`;
      track.append(block);
    }
    const cursor = el("span", { class: "ribbon-cursor", hidden: true });
    cursor.style.left = "0%";
    cursors.push(cursor);
    track.append(cursor);
    ribbon.append(
      el(
        "div",
        { class: `ribbon-row speaker-${speaker.color}` },
        el(
          "button",
          {
            class: "ribbon-name",
            type: "button",
            "aria-label": `${speaker.name} 이름 바꾸기`,
            onclick: () => onName(speaker),
          },
          el("span", { class: "ribbon-name-text", text: speaker.name }),
          speaker.auto ? el("span", { class: "auto-tag", text: "자동" }) : icon("pencil"),
        ),
        el("span", { class: "ribbon-share", text: `${speaker.share}%` }),
        track,
      ),
    );
  }
  return {
    node: ribbon,
    setTime(time) {
      for (const cursor of cursors) {
        cursor.hidden = false;
        cursor.style.left = `${(time / duration) * 100}%`;
      }
    },
  };
}

function playIcon() {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const shape = document.createElementNS(SVG_NS, "path");
  shape.setAttribute("d", PLAY_ICON);
  svg.append(shape);
  return { svg, shape };
}

function currentTurnIndex(turns, time) {
  let found = -1;
  for (let index = 0; index < turns.length; index += 1) {
    if (turns[index].start > time) break;
    found = index;
  }
  return found;
}

function renderEditor(job) {
  const page = setScreen({
    right: el("button", {
      class: "text-link",
      type: "button",
      text: "취소",
      onclick: async () => {
        if (unsaved) {
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
  // 화면과 같은 이름으로 보여 주고, 아직 정하지 않은 "화자 N"은 저장할 때 원래 라벨로 되돌린다.
  // 그래야 나중에 이름을 정해도 본문에 반영된다.
  const names = new Map(job.speakers.map((item) => [item.label, item.name]));
  const shown = job.notes.replace(/SPEAKER_\d+/g, (label) => names.get(label) || label);
  const defaults = job.speakers
    .filter((item) => item.known && !item.custom)
    .sort((a, b) => b.default_name.length - a.default_name.length);
  const toStored = (text) =>
    defaults.reduce((result, item) => result.replaceAll(item.default_name, item.label), text);

  const area = el("textarea", { "aria-label": "회의록 내용" });
  area.value = shown;
  area.addEventListener("input", () => {
    unsaved = area.value !== shown;
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

function renderAsk(job, seek, friendly) {
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

/* 이슈 트래커 등록 */

function selectBox(label, options, selected) {
  const select = el("select", { class: "select", "aria-label": label });
  for (const [value, text] of options) {
    const option = el("option", { value, text });
    if (value === selected) option.selected = true;
    select.append(option);
  }
  return select;
}

function labeled(text, control) {
  return el("label", { class: "draft-field" }, el("span", { text }), control);
}

function draftRow(draft, data, alreadyRegistered) {
  const source = data.actions[draft.source] || { task: "", evidence: "" };
  const choices = [["create", "새 이슈로 만들기"]];
  if (data.issues.length) choices.push(["comment", "기존 이슈에 댓글 달기"]);
  choices.push(["skip", "빼기"]);
  const initial = alreadyRegistered ? "skip" : draft.action;
  const action = selectBox("처리 방법", choices, initial);

  const title = el("input", { class: "text-input", type: "text", maxlength: 200, "aria-label": "이슈 제목" });
  title.value = draft.title || source.task;
  const assignee = selectBox("담당", [["", "담당 없음"], ...data.people.map((name) => [name, name])], draft.assignees[0] || "");
  const tag = selectBox("태그", [["", "태그 없음"], ...data.tags.map((name) => [name, name])], draft.tags[0] || "");
  const parent = selectBox("상위 이슈", [["", "상위 없음"], ...data.epics.map((epic) => [epic.key, `${epic.key} ${epic.title}`])], draft.parent || "");
  const description = el("textarea", { class: "draft-text", "aria-label": "이슈 설명" });
  description.value = draft.description || `## 배경\n- 회의 ${source.evidence}\n\n## 완료 조건\n- [ ] ${source.task}`;
  const comment = el("textarea", { class: "draft-text", "aria-label": "댓글 내용" });
  comment.value = draft.comment || `회의에서 나온 할 일: ${source.task} ${source.evidence}`;
  const target = selectBox(
    "댓글 달 이슈",
    data.issues.map((issue) => [issue.key, `${issue.key} ${issue.title}`]),
    draft.existing_key,
  );

  const createFields = el(
    "div",
    { class: "draft-fields" },
    labeled("제목", title),
    el("div", { class: "draft-selects" }, labeled("담당", assignee), labeled("태그", tag), labeled("상위 이슈", parent)),
    el("details", { class: "draft-details" }, el("summary", { text: "설명 보기·고치기" }), description),
  );
  const commentFields = el(
    "div",
    { class: "draft-fields" },
    labeled("댓글 달 이슈", target),
    comment,
  );
  const skipNote = el("p", { class: "draft-skip", text: alreadyRegistered ? "이미 등록한 할 일이에요." : draft.reason || "등록하지 않아요." });
  const show = () => {
    createFields.hidden = action.value !== "create";
    commentFields.hidden = action.value !== "comment";
    skipNote.hidden = action.value !== "skip";
  };
  action.addEventListener("change", show);
  show();

  const node = el(
    "div",
    { class: "issue-draft" },
    el("div", { class: "draft-head" }, el("span", { class: "draft-source" }, source.task, " ", el("span", { text: source.evidence })), action),
    createFields,
    commentFields,
    skipNote,
  );
  const value = () => {
    if (action.value === "create") {
      return {
        kind: "create",
        payload: {
          source: draft.source,
          title: title.value.trim(),
          description: description.value,
          category: draft.category,
          priority: draft.priority,
          assignees: assignee.value ? [assignee.value] : [],
          tags: tag.value ? [tag.value] : [],
          parent: parent.value,
          due_date: draft.due_date || "",
        },
      };
    }
    if (action.value === "comment") {
      return { kind: "comment", payload: { source: draft.source, key: target.value, text: comment.value.trim() } };
    }
    return null;
  };
  return { node, value };
}

function draftsReady(job) {
  const target = `#/jobs/${job.id}?issues=1`;
  toast("이슈 초안을 다 만들었어요", false, {
    label: "보기",
    onclick: () => {
      if (location.hash === target) route();
      else location.hash = target;
    },
  });
  if (document.hidden && "Notification" in window && Notification.permission === "granted" && "serviceWorker" in navigator) {
    navigator.serviceWorker.ready
      .then((registration) =>
        registration.showNotification("이슈 초안을 다 만들었어요", {
          body: "회의록 화면에서 확인하고 등록해 주세요.",
          icon: "/static/icons/icon-192.png",
          data: { url: `/${target}` },
        }),
      )
      .catch(() => {});
  }
}

function openIssueSheet(job, status, onDone, { refresh = false } = {}) {
  const pending = el("p", { class: "qa-pending", text: "할 일을 이슈 초안으로 만들고 있어요" });
  const body = el(
    "div",
    { class: "issue-body" },
    pending,
    el("p", { class: "hint", text: "할 일 수에 따라 30초에서 1분쯤 걸려요. 창을 닫아도 계속 만들고, 다 되면 알려 드려요." }),
  );
  let loading = true;
  const started = Date.now();
  const timer = setInterval(() => {
    pending.textContent = `할 일을 이슈 초안으로 만들고 있어요 · ${Math.round((Date.now() - started) / 1000)}초`;
  }, 1000);
  const heading = el("h2", { text: `${status.name}에 등록할 할 일` });
  const intro = el("p", {
    text: `${status.destination ? `${status.destination}에 올라가요. ` : ""}고치거나 뺄 항목을 확인해 주세요.`,
  });
  let closeSheet = null;
  const sheet = openSheet((close) => {
    closeSheet = close;
    return [heading, intro, body];
  });
  sheet.classList.add("tall");
  sheet.addEventListener("close", () => {
    if (loading) toast("창을 닫아도 초안은 계속 만들어요. 다 되면 알려 드릴게요.");
  });

  api(`/api/jobs/${job.id}/issues/drafts${refresh ? "?refresh=true" : ""}`, { method: "POST" })
    .then((data) => {
      loading = false;
      if (!sheet.open) {
        draftsReady(job);
        return;
      }
      const done = new Set(data.registered.map((item) => item.source));
      const rows = data.drafts.map((draft) => draftRow(draft, data, done.has(draft.source)));
      const submit = button("등록하기", {
        variant: "primary",
        onclick: async () => {
          const picked = rows.map((row) => row.value()).filter(Boolean);
          const create = picked.filter((item) => item.kind === "create").map((item) => item.payload);
          const comments = picked.filter((item) => item.kind === "comment").map((item) => item.payload);
          if (!create.length && !comments.length) {
            toast("등록할 항목을 골라 주세요", true);
            return;
          }
          if (create.some((item) => item.title.length < 2)) {
            toast("이슈 제목을 두 글자 이상 적어 주세요", true);
            return;
          }
          if (comments.some((item) => !item.text)) {
            toast("댓글 내용을 적어 주세요", true);
            return;
          }
          const parts = [create.length ? `새 이슈 ${create.length}건` : "", comments.length ? `댓글 ${comments.length}건` : ""];
          const agreed = await confirmSheet({
            title: `${status.name}에 등록할까요?`,
            body: `${parts.filter(Boolean).join(", ")}을 ${status.destination || status.name}에 올려요. 팀원 모두에게 보여요.`,
            action: "등록",
          });
          if (!agreed) return;
          submit.disabled = true;
          try {
            const result = await api(`/api/jobs/${job.id}/issues`, jsonOptions("POST", { create, comments }));
            heading.textContent = `${status.name}에 등록했어요`;
            intro.textContent = `키를 누르면 ${status.name}에서 열려요.`;
            body.replaceChildren(
              el(
                "ul",
                { class: "issue-results" },
                ...result.results.map((item) =>
                  el(
                    "li",
                    {},
                    issueKey(item),
                    item.kind === "create" ? item.title : "댓글을 남겼어요",
                  ),
                ),
              ),
              el("p", { class: "hint", text: "커밋 메시지에 이슈 키를 넣으면 커밋이 이슈에 연결되고, main에 들어오면 완료 여부를 자동으로 판단해요." }),
              el("div", { class: "sheet-actions" }, button("닫기", { variant: "primary", onclick: closeSheet })),
            );
            toast(`${status.name}에 등록했어요`);
            sheet.addEventListener("close", onDone, { once: true });
          } catch (error) {
            toast(error.message, true);
            // 일부만 올라갔으면 같은 항목을 다시 올리지 않도록 창을 닫고 등록 상태를 새로 불러온다.
            const latest = await api(`/api/jobs/${job.id}`).catch(() => null);
            if (latest && (latest.issues || []).length > data.registered.length) {
              sheet.addEventListener("close", onDone, { once: true });
              closeSheet();
              return;
            }
            submit.disabled = false;
          }
        },
      });
      const redo = el("button", {
        type: "button",
        class: "text-button",
        text: "다시 만들기",
        onclick: () => {
          closeSheet();
          openIssueSheet(job, status, onDone, { refresh: true });
        },
      });
      body.replaceChildren(
        el("p", { class: "drafted-at" }, `${dateText(data.drafted_at)}에 만든 초안이에요. `, redo),
        el("div", { class: "draft-list" }, ...rows.map((row) => row.node)),
        el("div", { class: "sheet-actions sticky" }, button("취소", { onclick: closeSheet }), submit),
      );
    })
    .catch((error) => {
      loading = false;
      if (!sheet.open) {
        toast(error.message, true);
        return;
      }
      body.replaceChildren(el("p", { class: "page-message", role: "alert", text: error.message }));
    })
    .finally(() => clearInterval(timer));
  sheet.addEventListener("close", () => clearInterval(timer));
}

async function openTemplateMenu(job) {
  let templates;
  try {
    templates = await loadTemplates();
  } catch (error) {
    toast(error.message, true);
    return;
  }
  openSheet((close) => [
    el("h2", { text: "어떤 양식으로 다시 쓸까요?" }),
    el("p", { text: "전사는 다시 하지 않고 회의록만 새로 써요." }),
    el(
      "div",
      { class: "sheet-menu template-menu" },
      ...templates.map((template) =>
        el(
          "button",
          {
            class: "sheet-item",
            type: "button",
            onclick: async () => {
              close();
              const agreed = await confirmSheet({
                title: `'${template.label}' 양식으로 다시 쓸까요?`,
                body: "지금 회의록은 새 내용으로 바뀌고, 직접 수정한 내용도 사라져요. API 비용이 들어요.",
                action: "다시 쓰기",
              });
              if (!agreed) return;
              try {
                await api(`/api/jobs/${job.id}/regenerate`, jsonOptions("POST", { template: template.key }));
                route();
              } catch (error) {
                toast(error.message, true);
              }
            },
          },
          el(
            "span",
            { class: "template-text" },
            el("strong", { text: template.label }),
            el("small", { text: template.description }),
          ),
          template.key === job.template ? el("span", { class: "badge", text: "지금 양식" }) : null,
        ),
      ),
    ),
  ]);
}

function openMoreMenu(job) {
  openSheet((close) => [
    el(
      "div",
      { class: "sheet-menu" },
      el(
        "button",
        {
          class: "sheet-item",
          type: "button",
          onclick: () => {
            close();
            openTemplateMenu(job);
          },
        },
        icon("rewrite"),
        "다른 양식으로 다시 쓰기",
      ),
      el(
        "button",
        {
          class: "sheet-item",
          type: "button",
          onclick: () => {
            close();
            renderEditor(job);
          },
        },
        icon("pencil"),
        "수정하기",
      ),
      el(
        "a",
        { class: "sheet-item", href: `/api/jobs/${job.id}/download`, onclick: close },
        icon("download"),
        "내려받기",
      ),
      el(
        "button",
        {
          class: "sheet-item danger",
          type: "button",
          onclick: () => {
            close();
            deleteJob(job);
          },
        },
        icon("trash"),
        "삭제하기",
      ),
    ),
  ]);
}

function renderDetail(job, { justConfirmed = false, restore = null, startAt = null, openIssues = false } = {}) {
  const page = setScreen({
    wide: true,
    back: true,
    right: el(
      "button",
      { class: "icon-button", type: "button", "aria-label": "더보기", onclick: () => openMoreMenu(job) },
      icon("more"),
    ),
  });
  const { turns, duration_seconds: duration } = job;
  const speakers = new Map(job.speakers.map((item) => [item.label, item]));
  const friendly = (text) => text.replace(/SPEAKER_\d+/g, (label) => speakers.get(label)?.name || label);

  const audio = el("audio", { src: `/api/jobs/${job.id}/audio`, preload: "metadata" });
  const play = playIcon();
  const playButton = el(
    "button",
    {
      class: "dock-play",
      type: "button",
      "aria-label": "재생",
      onclick: () => (audio.paused ? audio.play() : audio.pause()),
    },
    play.svg,
  );
  const timeLabel = el("span", { class: "dock-time", text: `00:00 / ${clock(duration)}` });
  const lineLabel = el("span", { class: "dock-line", text: "시각을 누르면 들을 수 있어요" });

  const lineNodes = turns.map((turn) => {
    const speaker = speakers.get(turn.speaker);
    return el(
      "li",
      {},
      el(
        "div",
        { class: `transcript-head speaker-${speaker.color}` },
        el("button", {
          class: "time-ref",
          type: "button",
          text: clock(turn.start),
          "aria-label": `${clock(turn.start)}부터 듣기`,
          onclick: () => seek(turn.start),
        }),
        speaker.known
          ? el("button", {
              class: "speaker-name",
              type: "button",
              text: speaker.name,
              "aria-label": `${speaker.name} 이름 바꾸기`,
              onclick: () => openSpeakerSheet(speaker),
            })
          : speaker.name,
      ),
      turn.text,
    );
  });
  const transcript = el("ol", { class: "transcript", "aria-label": "전사문" }, ...lineNodes);

  let currentIndex = -1;
  function showTurn(time, scroll) {
    const index = currentTurnIndex(turns, time);
    if (index === currentIndex && !scroll) return;
    if (lineNodes[currentIndex]) lineNodes[currentIndex].classList.remove("current");
    currentIndex = index;
    if (index < 0) return;
    const turn = turns[index];
    lineNodes[index].classList.add("current");
    lineLabel.textContent = `${speakers.get(turn.speaker).name}: ${turn.text}`;
    if (scroll && transcript.offsetParent && transcript.scrollHeight > transcript.clientHeight) {
      const offset = lineNodes[index].offsetTop - transcript.offsetTop - transcript.clientHeight / 3;
      transcript.scrollTo({ top: offset, behavior: reducedMotion.matches ? "auto" : "smooth" });
    }
  }

  function seek(time) {
    audio.currentTime = time;
    showTurn(time, true);
    audio.play().catch(() => {});
  }

  function currentView() {
    return { scrollY: window.scrollY, view: activeView, sideView, time: audio.currentTime };
  }

  function openSpeakerSheet(speaker) {
    const samples = turns
      .filter((turn) => turn.speaker === speaker.label)
      .sort((a, b) => b.end - b.start - (a.end - a.start))
      .slice(0, 5);
    let sampleIndex = 0;
    let sampleEnd = null;
    const stopAtSampleEnd = () => {
      if (sampleEnd !== null && audio.currentTime >= sampleEnd) {
        audio.pause();
        sampleEnd = null;
      }
    };
    audio.addEventListener("timeupdate", stopAtSampleEnd);

    const quote = el("p", { class: "sample-text", text: "무슨 말을 했는지 들어 보고 이름을 정해 보세요." });
    const listen = button("들어 보기", {
      iconName: "play",
      onclick: () => {
        const sample = samples[sampleIndex];
        quote.textContent = `${clock(sample.start)}  ${sample.text}`;
        sampleEnd = sample.end;
        seek(sample.start);
        sampleIndex = (sampleIndex + 1) % samples.length;
        if (samples.length > 1) listen.lastChild.textContent = "다른 부분 듣기";
      },
    });
    const input = el("input", {
      class: "text-input",
      type: "text",
      maxlength: 20,
      placeholder: speaker.default_name,
      "aria-label": "화자 이름",
      autocomplete: "off",
    });
    input.value = speaker.custom ? speaker.name : "";
    const remember = el("input", { type: "checkbox", id: "remember-voice" });

    const view = currentView();
    const sheet = openSheet((close) => {
      const save = el("button", { class: "button primary", type: "submit", text: "저장" });
      return [
        el("h2", { text: "이 사람은 누구인가요?" }),
        speaker.auto
          ? el("p", { class: "auto-note", text: "목소리로 자동 인식한 이름이에요. 틀렸다면 고쳐 주세요." })
          : null,
        el("div", { class: "sample" }, quote, listen),
        el(
          "form",
          {
            onsubmit: async (event) => {
              event.preventDefault();
              save.disabled = true;
              try {
                const updated = await api(
                  `/api/jobs/${job.id}/speakers/${speaker.label}`,
                  jsonOptions("PUT", { name: input.value, remember: remember.checked }),
                );
                close();
                toast(input.value.trim() ? "이름을 바꿨어요" : "기본 이름으로 되돌렸어요");
                renderDetail(updated, { restore: view });
              } catch (error) {
                toast(error.message, true);
                save.disabled = false;
              }
            },
          },
          input,
          el("p", { class: "input-hint", text: `비워 두면 '${speaker.default_name}'로 표시돼요.` }),
          speaker.has_voice
            ? el(
                "label",
                { class: "check-row", for: "remember-voice" },
                remember,
                el(
                  "span",
                  {},
                  el("strong", { text: "다음 회의에서도 이 목소리 알아보기" }),
                  el("small", { text: "본인 동의를 받은 사람만 켜 주세요. 목소리 특징은 이 기기에만 저장돼요." }),
                ),
              )
            : null,
          el("div", { class: "sheet-actions" }, button("취소", { onclick: close }), save),
        ),
      ];
    });
    sheet.addEventListener("close", () => {
      audio.removeEventListener("timeupdate", stopAtSampleEnd);
      if (sampleEnd !== null) audio.pause();
      sampleEnd = null;
    });
  }

  const ribbon = renderRibbon(turns, duration, job.speakers, seek, openSpeakerSheet);

  audio.addEventListener("timeupdate", () => {
    timeLabel.textContent = `${clock(audio.currentTime)} / ${clock(duration)}`;
    ribbon.setTime(audio.currentTime);
    showTurn(audio.currentTime, false);
  });
  audio.addEventListener("play", () => {
    play.shape.setAttribute("d", PAUSE_ICON);
    playButton.setAttribute("aria-label", "일시 정지");
  });
  audio.addEventListener("pause", () => {
    play.shape.setAttribute("d", PLAY_ICON);
    playButton.setAttribute("aria-label", "재생");
  });
  cleanup = () => audio.pause();

  const notesPane = el("div", {}, renderNotes(friendly(job.notes), seek));
  const transcriptCard = el("div", { class: "card" }, transcript);
  const askCard = renderAsk(job, seek, friendly);

  let activeView = restore?.view || (startAt !== null ? "transcript" : "notes");
  let sideView = restore?.sideView || "transcript";
  const tabButton = (view, label) =>
    el("button", {
      type: "button",
      role: "tab",
      "data-view": view,
      text: label,
      onclick: () => setView(view),
    });
  const mobileTabs = el(
    "div",
    { class: "tabs", role: "tablist" },
    tabButton("notes", "회의록"),
    tabButton("transcript", "전사문"),
    tabButton("ask", "질문하기"),
  );
  const sideTabs = el(
    "div",
    { class: "side-tabs", role: "tablist" },
    tabButton("transcript", "전사문"),
    tabButton("ask", "질문하기"),
  );
  const sidePane = el("div", { class: "side" }, sideTabs, transcriptCard, askCard);
  function setView(view) {
    activeView = view;
    if (view !== "notes") sideView = view;
    for (const tab of mobileTabs.children) tab.setAttribute("aria-selected", String(tab.dataset.view === view));
    for (const tab of sideTabs.children) tab.setAttribute("aria-selected", String(tab.dataset.view === sideView));
    notesPane.toggleAttribute("hidden-on-mobile", view !== "notes");
    sidePane.toggleAttribute("hidden-on-mobile", view === "notes");
    transcriptCard.hidden = sideView !== "transcript";
    askCard.hidden = sideView !== "ask";
  }
  setView(activeView);

  trackerStatus().then((status) => {
    if (!status.enabled) return;
    const section = [...notesPane.querySelectorAll("section")].find((item) =>
      item.querySelector("h2")?.textContent.startsWith("액션 아이템"),
    );
    if (!section) return;
    const registered = job.issues || [];
    const openDrafts = () =>
      openIssueSheet(job, status, () =>
        api(`/api/jobs/${job.id}`).then((updated) => renderDetail(updated, { restore: currentView() })),
      );
    if (openIssues) openDrafts();
    // 등록 버튼은 "액션 아이템" 제목 줄 오른쪽 끝에 둔다.
    const heading = section.querySelector("h2");
    const head = el("div", { class: "section-head" });
    heading.replaceWith(head);
    head.append(
      heading,
      button(registered.length ? `${status.name}에 더 등록` : `${status.name}에 등록`, { iconName: "issue", onclick: openDrafts }),
    );
    if (registered.length) head.after(el("p", { class: "issue-done" }, "등록함 ", ...registered.map(issueKey)));
  });

  const confirmButton = job.confirmed_at
    ? button("확정됨", { variant: "done", disabled: true, iconName: "check" })
    : button("확정하기", {
        variant: "primary",
        onclick: async () => {
          confirmButton.disabled = true;
          try {
            const updated = await api(`/api/jobs/${job.id}/confirm`, { method: "POST" });
            toast("회의록을 확정했어요");
            renderDetail(updated, { justConfirmed: true, restore: currentView() });
          } catch (error) {
            toast(error.message, true);
            confirmButton.disabled = false;
          }
        },
      });

  page.append(
    el(
      "header",
      { class: "doc-head" },
      badge(job, justConfirmed),
      el("h1", { text: friendly(displayName(job)) }),
      el("span", { class: "meta", text: `${metaText(job)}${job.edited ? ", 수정함" : ""}` }),
    ),
    ribbon.node,
    mobileTabs,
    el("div", { class: "panes" }, notesPane, sidePane),
    audio,
    el(
      "div",
      { class: "dock" },
      playButton,
      el("div", { class: "dock-text" }, timeLabel, lineLabel),
      confirmButton,
    ),
  );

  if (startAt !== null) {
    showTurn(startAt, true);
    audio.addEventListener("loadedmetadata", () => {
      audio.currentTime = startAt;
    }, { once: true });
    const index = currentTurnIndex(turns, startAt);
    if (lineNodes[index]) lineNodes[index].scrollIntoView({ block: "center" });
  }

  if (restore) {
    window.scrollTo(0, restore.scrollY);
    if (restore.time) {
      audio.addEventListener("loadedmetadata", () => {
        audio.currentTime = restore.time;
      }, { once: true });
    }
  }
}

/* 등록한 목소리 */

async function renderVoices() {
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
        el("span", { class: "meta", text: `회의 ${voice.samples}건에서 등록, ${dateText(voice.updated_at)}` }),
      ),
      button("삭제", {
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
      }),
    ),
  );
  page.append(
    el(
      "section",
      { class: "hero" },
      el("h1", { text: "등록한 목소리" }),
      el("p", { text: "등록한 사람은 다음 회의에서 자동으로 이름이 붙어요. 목소리 특징은 이 기기에만 저장돼요." }),
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
    el("p", { class: "hint", text: "목소리는 생체 정보예요. 본인 동의를 받은 사람만 등록해 주세요." }),
  );
}

function statusMark(job) {
  if (job.status === "failed") return el("div", { class: "status-mark failed" }, icon("alert"));
  if (job.status === "canceled") return el("div", { class: "status-mark stopped" }, icon("stop"));
  return el(
    "div",
    { class: "status-mark" },
    el("div", { class: "wave", "aria-hidden": "true" }, el("i"), el("i"), el("i"), el("i"), el("i")),
  );
}

function renderWaiting(job) {
  const page = setScreen({ back: true });
  const title = el("h1", { text: headline(job) });
  const state = el("p", { class: "state", "aria-live": "polite", text: detailText(job) });
  const meterBox = el("div", {}, isWorking(job) ? meter(progress(job)) : null);
  const content = el(
    "div",
    { class: "waiting" },
    statusMark(job),
    title,
    state,
    meterBox,
    el("p", { class: "file", text: `${displayName(job)}, ${spanOfTime(job.duration_seconds)} 녹음` }),
  );
  const bar = el("div", { class: "bottom-bar-inner" });

  if (isActive(job)) {
    content.append(el("p", { class: "note", text: "이 화면을 닫아도 괜찮아요. 끝날 때까지 노트북만 켜 두세요." }));
    const stop = button("처리 멈추기", {
      onclick: async () => {
        const agreed = await confirmSheet({
          title: "처리를 멈출까요?",
          body: "지금까지 옮긴 내용은 사라지고, 다시 시작하면 처음부터 해요.",
          action: "멈추기",
          danger: true,
        });
        if (!agreed) return;
        stop.disabled = true;
        try {
          await api(`/api/jobs/${job.id}/cancel`, { method: "POST" });
          route();
        } catch (error) {
          toast(error.message, true);
          stop.disabled = false;
        }
      },
    });
    bar.append(stop);

    const refresh = async () => {
      let latest;
      try {
        latest = await api(`/api/jobs/${job.id}`);
      } catch (error) {
        pollTimer = setTimeout(refresh, POLL_MS);
        return;
      }
      if (latest.status !== job.status) {
        route();
        return;
      }
      title.textContent = headline(latest);
      state.textContent = detailText(latest);
      meterBox.replaceChildren(...(isWorking(latest) ? [meter(progress(latest))] : []));
      pollTimer = setTimeout(refresh, POLL_MS);
    };
    pollTimer = setTimeout(refresh, POLL_MS);
  } else {
    const restart = button("다시 시작", {
      variant: "primary",
      onclick: async () => {
        restart.disabled = true;
        try {
          await api(`/api/jobs/${job.id}/retry`, { method: "POST" });
          route();
        } catch (error) {
          toast(error.message, true);
          restart.disabled = false;
        }
      },
    });
    bar.append(button("삭제", { onclick: () => deleteJob(job) }), restart);
  }

  page.append(content, el("div", { class: "bottom-bar" }, bar));
}

/* 화면 전환 */

function showError(message) {
  const page = setScreen({ back: true });
  page.append(el("p", { class: "page-message", role: "alert", text: message }));
}

async function route() {
  document.querySelectorAll("dialog.sheet").forEach((sheet) => sheet.close());
  const match = location.hash.match(/^#\/jobs\/([0-9a-f]{32})(?:\?(t=\d+|issues=1))?$/);
  try {
    if (location.hash === "#/voices") {
      await renderVoices();
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

if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

window.addEventListener("hashchange", route);
window.addEventListener("beforeunload", (event) => {
  if (unsaved) event.preventDefault();
});
route();
