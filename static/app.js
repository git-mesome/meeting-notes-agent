"use strict";

const root = document.getElementById("app");
const POLL_MS = 5000;
const ACCEPT = ".m4a,.mp3,.wav,.flac,.ogg,.aac,.mp4,.webm,audio/*";
const TIME_REF = /\[(\d{1,2}:\d{2}(?::\d{2})?)\]/;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const SVG_NS = "http://www.w3.org/2000/svg";

const ICONS = {
  upload: "M12 16V4m0 0L7 9m5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
  calendar: "M7 3v3m10-3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z",
  clock: "M12 7v5l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
  check: "M5 12.5 10 17.5 19 7.5",
  pencil: "M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4",
  download: "M12 4v12m0 0 5-5m-5 5-5-5M4 20h16",
  trash: "M4 7h16M10 11v6m4-6v6M6 7l1 13h10l1-13M9 7V4h6v3",
  back: "M15 5l-7 7 7 7",
  stop: "M7 7h10v10H7z",
  restart: "M4 12a8 8 0 0 1 14-5.3L20 9m0-5v5h-5M20 12a8 8 0 0 1-14 5.3L4 15m0 5v-5h5",
};
const PLAY_ICON = "M7 4l13 8-13 8z";
const PAUSE_ICON = "M6 4h4v16H6zM14 4h4v16h-4z";

let pollTimer = null;
let cleanup = null;
let unsaved = false;

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

function button(label, options = {}) {
  const { iconName, variant, onclick, disabled } = options;
  return el(
    "button",
    { class: ["button", variant].filter(Boolean).join(" "), type: "button", onclick, disabled },
    iconName ? icon(iconName) : null,
    label,
  );
}

class ApiError extends Error {}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "요청을 처리하지 못했습니다. 다시 시도하세요.";
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

function metaRow(job, ...extras) {
  return el(
    "div",
    { class: "meta" },
    el("span", {}, icon("calendar"), dateText(job.created_at)),
    el("span", {}, icon("clock"), spanOfTime(job.duration_seconds)),
    ...extras,
  );
}

function stateText(job) {
  if (job.status === "queued") {
    return job.ahead ? `대기 중입니다. 앞에 ${job.ahead}건이 있습니다.` : "곧 시작합니다.";
  }
  if (job.status === "transcribing") {
    const left = job.estimated_seconds - job.elapsed_seconds;
    if (left <= 0) return "말을 글로 옮기는 중입니다. 예상보다 오래 걸리고 있습니다.";
    return `말을 글로 옮기는 중입니다. 약 ${spanOfTime(left)} 남았습니다.`;
  }
  if (job.status === "writing") return "회의록을 쓰는 중입니다. 곧 끝납니다.";
  if (job.status === "canceled") return "처리를 중지했습니다.";
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

function statusPill(job, animate = false) {
  if (job.status === "done" && job.confirmed_at) {
    return el("span", { class: `pill confirmed ${animate ? "pop" : ""}` }, icon("check"), "확정");
  }
  if (job.status === "done") return el("span", { class: "pill draft", text: "초안" });
  if (job.status === "failed") return el("span", { class: "pill failed", text: "실패" });
  if (job.status === "canceled") return el("span", { class: "pill", text: "중지됨" });
  if (job.status === "queued") return el("span", { class: "pill", text: "대기 중" });
  return el("span", { class: "pill", text: "처리 중" });
}

function topbar() {
  return el(
    "header",
    { class: "topbar" },
    el(
      "a",
      { class: "brand", href: "#/" },
      el("img", { src: "/static/favicon.svg", alt: "" }),
      "회의록",
    ),
  );
}

function setScreen(wide = false) {
  clearTimeout(pollTimer);
  if (cleanup) cleanup();
  cleanup = null;
  unsaved = false;
  const page = el("main", { class: wide ? "page wide" : "page" });
  root.replaceChildren(topbar(), page);
  window.scrollTo(0, 0);
  return page;
}

async function deleteJob(job, alert) {
  const message = "이 회의록을 삭제할까요? 녹음, 전사문, 회의록이 모두 지워지고 되돌릴 수 없습니다.";
  if (!window.confirm(message)) return;
  try {
    await api(`/api/jobs/${job.id}`, { method: "DELETE" });
    location.hash = "#/";
  } catch (error) {
    alert.textContent = error.message;
  }
}

/* 목록 */

function uploadSection(onUploaded) {
  const alert = el("p", { class: "alert", role: "alert" });
  const status = el("div", { class: "upload-progress", "aria-live": "polite" });
  const input = el("input", { type: "file", accept: ACCEPT, id: "audio-file" });
  const label = el("label", { class: "upload-button", for: "audio-file" }, icon("upload"), "녹음 올리기");

  input.addEventListener("change", () => {
    const file = input.files[0];
    if (!file) return;
    alert.textContent = "";
    input.disabled = true;
    label.setAttribute("aria-disabled", "true");
    const progressText = el("span", { text: `${file.name} 올리는 중` });
    const fill = el("div", { class: "meter-fill" });
    fill.style.width = "0%";
    status.replaceChildren(progressText, el("div", { class: "meter" }, fill));

    const finish = () => {
      input.disabled = false;
      input.value = "";
      label.removeAttribute("aria-disabled");
      status.replaceChildren();
    };

    const request = new XMLHttpRequest();
    request.open("POST", "/api/jobs");
    request.responseType = "json";
    request.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable) return;
      const percent = Math.round((event.loaded / event.total) * 100);
      fill.style.width = `${percent}%`;
      progressText.textContent =
        percent < 100 ? `${file.name} 올리는 중 (${percent}%)` : `${file.name} 확인하는 중`;
    });
    request.addEventListener("load", () => {
      finish();
      if (request.status === 201) {
        onUploaded();
      } else {
        const detail = request.response && request.response.detail;
        alert.textContent = typeof detail === "string" ? detail : "파일을 올리지 못했습니다. 다시 시도하세요.";
      }
    });
    request.addEventListener("error", () => {
      finish();
      alert.textContent = "연결이 끊겨 파일을 올리지 못했습니다. 노트북이 켜져 있는지 확인하고 다시 시도하세요.";
    });
    const form = new FormData();
    form.append("file", file);
    request.send(form);
  });

  return el(
    "div",
    { class: "upload" },
    input,
    label,
    el("p", {
      class: "upload-hint",
      text: "1GB 이하의 녹음 파일을 올립니다. 아이폰 음성 메모는 공유 메뉴에서 파일에 저장한 뒤 고르세요.",
    }),
    status,
    alert,
  );
}

function noteCard(job) {
  const body = el(
    "div",
    {},
    el("span", { class: "note-title", text: job.title || job.name }),
    metaRow(job),
  );
  if (isWorking(job)) body.append(meter(progress(job)));
  if (job.status !== "done") {
    body.append(
      el("div", {
        class: `note-state ${job.status === "failed" ? "failed" : ""}`,
        text: stateText(job),
      }),
    );
  }
  return el("li", {}, el("a", { class: "note-card", href: `#/jobs/${job.id}` }, body, statusPill(job)));
}

async function renderList() {
  const page = setScreen();
  const list = el("section", { "aria-label": "내 회의록" });
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
      ordered.length
        ? el("ul", { class: "note-list" }, ...ordered.map(noteCard))
        : el("p", { class: "empty", text: "아직 회의록이 없습니다. 첫 녹음을 올리세요." }),
    );
    if (jobs.some(isActive)) pollTimer = setTimeout(refresh, POLL_MS);
  };
  page.append(
    el(
      "section",
      { class: "hero" },
      el("h1", { text: "회의가 끝나면, 녹음만 올리세요" }),
      el("p", { text: "말을 글로 옮기고 화자를 나눠 회의록 초안까지 만듭니다." }),
      uploadSection(refresh),
    ),
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
  let parent = container;
  let list = null;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed.startsWith("- ")) list = null;
    if (!trimmed) continue;
    if (trimmed.startsWith("# ")) continue;
    if (trimmed.startsWith("## ")) {
      const heading = trimmed.slice(3);
      const isCheck = heading.startsWith("확인 필요");
      parent = isCheck ? el("section", { class: "check" }) : container;
      if (isCheck) container.append(parent);
      parent.append(el("h2", { text: heading }));
    } else if (trimmed.startsWith("### ")) {
      parent.append(el("h3", { text: trimmed.slice(4) }));
    } else if (trimmed.startsWith("- ")) {
      if (!list) {
        list = el("ul");
        parent.append(list);
      }
      list.append(el("li", {}, ...inline(trimmed.slice(2), onTime)));
    } else if (trimmed.startsWith("|")) {
      const tableLines = [];
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        tableLines.push(lines[index]);
        index += 1;
      }
      index -= 1;
      parent.append(renderTable(tableLines, onTime));
    } else {
      parent.append(el("p", {}, ...inline(trimmed, onTime)));
    }
  }
  return container;
}

/* 상세 */

function speakerStats(turns, duration) {
  const totals = new Map();
  for (const turn of turns) {
    totals.set(turn.speaker, (totals.get(turn.speaker) || 0) + (turn.end - turn.start));
  }
  const sum = [...totals.values()].reduce((a, b) => a + b, 0) || duration || 1;
  return [...totals.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([speaker, seconds], index) => ({ speaker, share: Math.round((seconds / sum) * 100), index: index % 6 }));
}

function renderRibbon(turns, duration, stats, seek) {
  const ribbon = el("section", { class: "ribbon", "aria-label": "시간대별 화자" });
  const cursors = [];
  for (const { speaker, share, index } of stats.filter((item) => item.speaker !== "UNKNOWN")) {
    const track = el("div", {
      class: "ribbon-track",
      onclick: (event) => {
        const box = event.currentTarget.getBoundingClientRect();
        seek(((event.clientX - box.left) / box.width) * duration);
      },
    });
    for (const turn of turns.filter((item) => item.speaker === speaker)) {
      const block = el("i");
      block.style.left = `${(turn.start / duration) * 100}%`;
      block.style.width = `${((turn.end - turn.start) / duration) * 100}%`;
      track.append(block);
    }
    const cursor = el("span", { class: "ribbon-cursor" });
    cursor.style.left = "0%";
    cursors.push(cursor);
    track.append(cursor);
    ribbon.append(
      el(
        "div",
        { class: `ribbon-row speaker-${index}` },
        el("div", { class: "ribbon-label" }, `${speaker} `, el("span", { text: `${share}%` })),
        track,
      ),
    );
  }
  return {
    node: ribbon,
    setTime(time) {
      for (const cursor of cursors) cursor.style.left = `${(time / duration) * 100}%`;
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

function renderDetail(job, { justConfirmed = false } = {}) {
  const page = setScreen(true);
  const { turns, duration_seconds: duration } = job;
  const stats = speakerStats(turns, duration);
  const speakerIndex = new Map(stats.map((item) => [item.speaker, item.index]));

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
  const lineLabel = el("span", {
    class: "dock-line",
    text: "시각을 누르면 그 부분부터 들을 수 있습니다.",
  });

  const lineNodes = turns.map((turn, index) => {
    const speakerClass = `speaker-${speakerIndex.get(turn.speaker)}`;
    return el(
      "li",
      { "data-index": index },
      el(
        "div",
        { class: `transcript-head ${speakerClass}` },
        el("button", {
          class: "time-ref",
          type: "button",
          text: clock(turn.start),
          "aria-label": `${clock(turn.start)}부터 듣기`,
          onclick: () => seek(turn.start),
        }),
        turn.speaker,
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
    lineLabel.textContent = `${turn.speaker}: ${turn.text}`;
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

  const ribbon = renderRibbon(turns, duration, stats, seek);

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

  const notesPane = el("div", {}, renderNotes(job.notes, seek));
  const transcriptPane = el("div", { class: "transcript-panel" }, transcript);

  const notesTab = el("button", { type: "button", role: "tab", "aria-selected": "true", text: "회의록" });
  const transcriptTab = el("button", { type: "button", role: "tab", "aria-selected": "false", text: "전사문" });
  const selectTab = (showNotes) => {
    notesTab.setAttribute("aria-selected", String(showNotes));
    transcriptTab.setAttribute("aria-selected", String(!showNotes));
    notesPane.toggleAttribute("hidden-on-mobile", !showNotes);
    transcriptPane.toggleAttribute("hidden-on-mobile", showNotes);
  };
  notesTab.addEventListener("click", () => selectTab(true));
  transcriptTab.addEventListener("click", () => selectTab(false));
  selectTab(true);

  const alert = el("p", { class: "alert", role: "alert" });

  const startEditing = () => {
    const area = el("textarea", { "aria-label": "회의록 내용" });
    area.value = job.notes;
    area.addEventListener("input", () => {
      unsaved = area.value !== job.notes;
    });
    const save = button("저장", {
      variant: "primary",
      onclick: async () => {
        save.disabled = true;
        try {
          const updated = await api(`/api/jobs/${job.id}/notes`, jsonOptions("PUT", { notes: area.value }));
          renderDetail(updated);
        } catch (error) {
          alert.textContent = error.message;
          save.disabled = false;
        }
      },
    });
    const cancel = button("취소", {
      onclick: () => {
        if (unsaved && !window.confirm("저장하지 않은 수정 내용을 버릴까요?")) return;
        renderDetail(job);
      },
    });
    selectTab(true);
    notesPane.replaceChildren(
      el("div", { class: "editor" }, area, el("div", { class: "editor-actions" }, save, cancel)),
    );
    actions.hidden = true;
    backLink.hidden = true;
    area.focus();
  };

  const confirmButton = button(job.confirmed_at ? "확정됨" : "확정하기", {
    iconName: "check",
    variant: "primary",
    disabled: Boolean(job.confirmed_at),
    onclick: async () => {
      confirmButton.disabled = true;
      try {
        const updated = await api(`/api/jobs/${job.id}/confirm`, { method: "POST" });
        renderDetail(updated, { justConfirmed: true });
      } catch (error) {
        alert.textContent = error.message;
        confirmButton.disabled = false;
      }
    },
  });

  const actions = el(
    "div",
    { class: "actions" },
    confirmButton,
    button("수정", { iconName: "pencil", onclick: startEditing }),
    el(
      "a",
      { class: "button", href: `/api/jobs/${job.id}/download` },
      icon("download"),
      "내려받기",
    ),
    button("삭제", { iconName: "trash", variant: "danger", onclick: () => deleteJob(job, alert) }),
  );

  const backLink = el("a", { class: "back", href: "#/" }, icon("back"), "목록으로");

  page.append(
    backLink,
    el(
      "header",
      { class: "doc-head" },
      el("h1", { text: job.title || job.name }),
      metaRow(job, statusPill(job, justConfirmed), job.edited ? el("span", { text: "수정함" }) : null),
    ),
    actions,
    alert,
    ribbon.node,
    el("div", { class: "tabs", role: "tablist" }, notesTab, transcriptTab),
    el("div", { class: "panes" }, notesPane, transcriptPane),
    audio,
    el("div", { class: "dock" }, playButton, timeLabel, lineLabel),
  );
}

function renderWaiting(job) {
  const page = setScreen();
  const alert = el("p", { class: "alert", role: "alert" });
  const card = el(
    "div",
    { class: "waiting" },
    el("h1", { text: job.name }),
    metaRow(job, statusPill(job)),
  );
  const buttons = el("div", { class: "actions" });

  if (isActive(job)) {
    if (isWorking(job)) card.append(meter(progress(job)));
    card.append(
      el("p", { class: "state", "aria-live": "polite", text: stateText(job) }),
      el("p", { class: "note", text: "이 화면을 닫아도 처리는 계속됩니다. 끝날 때까지 노트북을 켜 두세요." }),
    );
    const stop = button("처리 중지", {
      iconName: "stop",
      onclick: async () => {
        if (!window.confirm("처리를 중지할까요? 진행 중인 전사는 사라지고, 다시 시작하면 처음부터 합니다.")) return;
        stop.disabled = true;
        try {
          await api(`/api/jobs/${job.id}/cancel`, { method: "POST" });
          route();
        } catch (error) {
          alert.textContent = error.message;
          stop.disabled = false;
        }
      },
    });
    buttons.append(stop);
    pollTimer = setTimeout(route, POLL_MS);
  } else {
    card.append(
      el("p", {
        class: `state ${job.status === "failed" ? "alert" : ""}`,
        role: job.status === "failed" ? "alert" : null,
        text: stateText(job),
      }),
      el("p", { class: "note", text: `다시 시작하면 전사에 약 ${spanOfTime(job.estimated_seconds)} 걸립니다.` }),
    );
    const restart = button("다시 시작", {
      iconName: "restart",
      variant: "primary",
      onclick: async () => {
        restart.disabled = true;
        try {
          await api(`/api/jobs/${job.id}/retry`, { method: "POST" });
          route();
        } catch (error) {
          alert.textContent = error.message;
          restart.disabled = false;
        }
      },
    });
    buttons.append(
      restart,
      button("삭제", { iconName: "trash", variant: "danger", onclick: () => deleteJob(job, alert) }),
    );
  }

  card.append(buttons, alert);
  page.append(
    el("div", { class: "page-center" }, el("a", { class: "back", href: "#/" }, icon("back"), "목록으로"), card),
  );
}

/* 화면 전환 */

function showError(message) {
  const page = setScreen();
  page.append(
    el("div", { class: "page-center" }, el("a", { class: "back", href: "#/" }, icon("back"), "목록으로"), el("p", { class: "alert", role: "alert", text: message })),
  );
}

async function route() {
  const match = location.hash.match(/^#\/jobs\/([0-9a-f]{32})$/);
  try {
    if (!match) {
      await renderList();
      return;
    }
    const job = await api(`/api/jobs/${match[1]}`);
    if (job.status === "done") renderDetail(job);
    else renderWaiting(job);
  } catch (error) {
    if (error instanceof ApiError) {
      showError(error.message);
    } else {
      showError("노트북에 연결할 수 없습니다. 노트북과 Tailscale이 켜져 있는지 확인한 뒤 새로고침하세요.");
    }
  }
}

window.addEventListener("hashchange", route);
window.addEventListener("beforeunload", (event) => {
  if (unsaved) event.preventDefault();
});
route();
