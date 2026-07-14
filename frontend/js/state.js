export const state = {
  wardId: null,
  wardLabel: "",
  token: null,
  name: null,
  isAdmin: false,
};

export function resetAuth() {
  state.token = null;
  state.name = null;
  state.isAdmin = false;
}

export function resetWard() {
  state.wardId = null;
  state.wardLabel = "";
  resetAuth();
}
