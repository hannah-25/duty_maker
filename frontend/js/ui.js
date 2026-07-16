/**
 * 비동기 작업이 도는 동안 버튼을 잠근다. 근무표 생성처럼 오래 걸리는 작업에서
 * 중복 클릭으로 요청이 여러 번 나가는 것을 막는다.
 *
 * 실패해도 반드시 잠금이 풀리도록 finally에서 되돌린다. 화면이 다시 그려져
 * 버튼이 DOM에서 사라진 뒤일 수도 있지만, 그때도 이 조작은 무해하다.
 */
export async function withBusy(button, fn, busyLabel) {
  if (!button || button.disabled) return undefined;
  const previousLabel = button.textContent;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  if (busyLabel) button.textContent = busyLabel;
  try {
    return await fn();
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    if (busyLabel) button.textContent = previousLabel;
  }
}

/** 클릭 핸들러를 withBusy로 감싸 등록한다. */
export function onClickBusy(button, fn, busyLabel) {
  if (!button) return;
  button.addEventListener("click", () => withBusy(button, fn, busyLabel));
}
