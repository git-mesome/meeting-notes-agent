/* 처리 완료 웹 푸시 켜기. */

import { api, jsonOptions } from "./api.js";
import { button, el, icon, toast } from "./ui.js";

/* 완료 알림 */

export function base64UrlToBytes(text) {
  const raw = atob(text.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(text.length / 4) * 4, "="));
  return Uint8Array.from(raw, (char) => char.charCodeAt(0));
}

export async function pushStatus() {
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

export async function turnOnPush() {
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

export function pushCard() {
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

