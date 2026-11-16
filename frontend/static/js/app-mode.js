(() => {
  const messageScreen = document.getElementById("message-mode");
  const callScreen = document.getElementById("call-static-screen");
  const modeButtons = [...document.querySelectorAll("#mode-nav [data-mode]")];
  if (!messageScreen || !callScreen || !modeButtons.length) return;

  function showMode(mode) {
    const isCall = mode === "call";
    messageScreen.hidden = isCall;
    callScreen.hidden = !isCall;
    modeButtons.forEach((button) => {
      const active = button.dataset.mode === mode;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  modeButtons.forEach((button) => {
    button.addEventListener("click", () => showMode(button.dataset.mode));
  });
  document.querySelectorAll("[data-open-mode]").forEach((button) => {
    button.addEventListener("click", () => showMode(button.dataset.openMode));
  });

  showMode("message");
})();
