/* 액션 아이템을 이슈 트래커에 등록하는 창. */

import { api, jsonOptions } from "./api.js";
import { dateText } from "./format.js";
import { route } from "./router.js";
import { state } from "./state.js";
import { button, confirmSheet, el, icon, openSheet, toast } from "./ui.js";

export async function trackerStatus() {
  if (!state.trackerCache) state.trackerCache = await api("/api/tracker").catch(() => ({ enabled: false }));
  return state.trackerCache;
}

export function issueKey(item) {
  if (!item.url) return el("span", { class: "issue-key", text: item.key });
  return el("a", { class: "issue-key", href: item.url, target: "_blank", rel: "noopener", text: item.key });
}
/* 이슈 트래커 등록 */

export function selectBox(label, options, selected) {
  const select = el("select", { class: "select", "aria-label": label });
  for (const [value, text] of options) {
    const option = el("option", { value, text });
    if (value === selected) option.selected = true;
    select.append(option);
  }
  return select;
}

export function labeled(text, control) {
  return el("label", { class: "draft-field" }, el("span", { text }), control);
}

export function draftRow(draft, data, alreadyRegistered) {
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

export function draftsReady(job) {
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

export function openIssueSheet(job, status, onDone, { refresh = false } = {}) {
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

