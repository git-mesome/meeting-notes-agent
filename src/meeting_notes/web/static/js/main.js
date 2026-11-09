/* 화면 시작점. 화면 모듈을 불러오고 주소가 바뀔 때마다 맞는 화면을 그린다. */

import { route } from "./router.js";
import { state } from "./state.js";

if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

window.addEventListener("hashchange", route);
window.addEventListener("beforeunload", (event) => {
  if (state.unsaved) event.preventDefault();
});
route();
