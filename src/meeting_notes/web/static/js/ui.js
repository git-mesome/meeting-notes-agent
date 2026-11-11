/* 화면 부품: 요소 만들기, 아이콘, 버튼, 알림, 아래에서 올라오는 창. */

export const SVG_NS = "http://www.w3.org/2000/svg";

export const ICONS = {
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
  people: "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21v-1a5 5 0 0 1 5-5h4a5 5 0 0 1 5 5v1M16 3.5a4 4 0 0 1 0 7M22 21v-1a5 5 0 0 0-3.5-4.8",
  send: "M12 19V5m0 0l-6 6m6-6l6 6",
  rewrite: "M4 12a8 8 0 0 1 14-5.3L20 9m0-5v5h-5M20 12a8 8 0 0 1-14 5.3L4 15m0 5v-5h5",
  issue: "M9 4h6v3H9zM7 6H5v15h14V6h-2M9 14l2 2 4-4",
  play: "M8 5l11 7-11 7z",
  stop: "M7 7h10v10H7z",
  alert: "M12 8v5m0 3.5h.01M12 3l9.5 17h-19z",
  phone: "M8 3h8a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM11 18h2",
};
export const PLAY_ICON = "M7 4l13 8-13 8z";
export const PAUSE_ICON = "M6 4h4v16H6zM14 4h4v16h-4z";

export function el(tag, props = {}, ...children) {
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

export function icon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const shape = document.createElementNS(SVG_NS, "path");
  shape.setAttribute("d", ICONS[name]);
  svg.append(shape);
  return svg;
}

export function button(label, { variant = "soft", onclick, disabled, iconName } = {}) {
  return el(
    "button",
    { class: `button ${variant}`, type: "button", onclick, disabled },
    iconName ? icon(iconName) : null,
    label,
  );
}

export function toast(message, isError = false, action = null) {
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

export function openSheet(build) {
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

export function confirmSheet({ title, body, action, danger = false }) {
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

export function meter(fraction) {
  const fill = el("div", { class: "meter-fill" });
  fill.style.width = `${Math.round(fraction * 100)}%`;
  return el("div", { class: "meter" }, fill);
}

