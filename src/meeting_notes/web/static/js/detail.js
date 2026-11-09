/* 회의록 화면: 화자 띠, 재생, 회의록·전사문·질문 탭. */

import { api, jsonOptions } from "./api.js";
import { renderAsk } from "./ask.js";
import { badge, clock, displayName, metaText } from "./format.js";
import { issueKey, openIssueSheet, trackerStatus } from "./issues.js";
import { openMoreMenu } from "./menus.js";
import { attachSectionEditors } from "./edit.js";
import { renderNotes } from "./notes.js";
import { setScreen } from "./screen.js";
import { reducedMotion, state } from "./state.js";
import { PAUSE_ICON, PLAY_ICON, SVG_NS, button, el, icon, openSheet, toast } from "./ui.js";

/* 상세 */

export function renderRibbon(turns, duration, speakers, seek, onName) {
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

export function playIcon() {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const shape = document.createElementNS(SVG_NS, "path");
  shape.setAttribute("d", PLAY_ICON);
  svg.append(shape);
  return { svg, shape };
}

export function currentTurnIndex(turns, time) {
  let found = -1;
  for (let index = 0; index < turns.length; index += 1) {
    if (turns[index].start > time) break;
    found = index;
  }
  return found;
}

export function renderDetail(job, { justConfirmed = false, restore = null, startAt = null, openIssues = false } = {}) {
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
  state.cleanup = () => audio.pause();

  // 확인 필요 항목의 체크는 바로 저장한다. 내용은 그대로라 화면을 다시 그리지 않는다.
  const onCheck = async (index, done) => {
    const updated = await api(`/api/jobs/${job.id}/checks/${index}`, jsonOptions("PUT", { done }));
    job.notes = updated.notes;
  };
  const article = renderNotes(friendly(job.notes), seek, { onCheck });
  attachSectionEditors(article, job, (updated) => renderDetail(updated, { restore: currentView() }));
  const notesPane = el("div", {}, article);
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
    // 등록 버튼은 "액션 아이템" 제목 줄 오른쪽, 수정 버튼 앞에 둔다.
    section.querySelector(".section-actions").prepend(
      button(registered.length ? `${status.name}에 더 등록` : `${status.name}에 등록`, { iconName: "issue", onclick: openDrafts }),
    );
    if (registered.length) {
      section.querySelector(".section-head").after(el("p", { class: "issue-done", "data-ui": "" }, "등록함 ", ...registered.map(issueKey)));
    }
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

