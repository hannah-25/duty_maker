import { state } from "./state.js";
import { renderWardSelect } from "./views/ward-select.js";
import { renderLogin } from "./views/login.js";
import { renderApp } from "./views/app.js";

const root = document.getElementById("app-root");

export function navigate() {
  if (!state.wardId) {
    renderWardSelect(root, navigate);
  } else if (!state.token) {
    renderLogin(root, navigate);
  } else {
    renderApp(root, navigate);
  }
}
