(() => {
  const $ = (id) => document.getElementById(id);
  const authPanel = $("auth-panel"), appContent = $("app-content");
  const usernameInput = $("auth-username-input"), passwordInput = $("auth-password-input");
  const error = $("auth-error");

  function showSignedIn(user) {
    window.ArenaCurrentUser=user;
    document.body.dataset.authenticated = "true";
    document.body.dataset.userRole = user.role;
    $("account-role").textContent = user.role === "admin" ? "Vai trò: Quản trị viên" : "Vai trò: Người dùng";
    authPanel.hidden = true;
    appContent.hidden = false;
    $("auth-username").textContent = user.username;
    $("account-controls").hidden = false;
    $("admin-tools").hidden = user.role !== "admin";
    if (window.ArenaHistory) window.ArenaHistory.refreshAll();
    document.dispatchEvent(new CustomEvent("arena:authenticated",{detail:{user}}));
  }

  async function send(path, body) {
    const response = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    let data = {};
    try { data = await response.json(); } catch (_) { /* empty response */ }
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map((item) => item.msg).join("; ") : data.detail;
      throw new Error(detail || response.statusText || "Không thể đăng nhập.");
    }
    return data;
  }

  async function authenticate(mode) {
    error.hidden = true;
    const username = usernameInput.value.trim();
    const password = passwordInput.value;
    if (mode === "register" && password.length < 3) {
      error.textContent = "Mật khẩu cần có ít nhất 3 ký tự.";
      error.hidden = false;
      return;
    }
    try {
      await send(`/api/auth/${mode}`, { username, password });
      window.location.reload();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    }
  }

  $("auth-login").addEventListener("click", () => authenticate("login"));
  $("auth-register").addEventListener("click", () => authenticate("register"));
  passwordInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") authenticate("login");
  });
  $("auth-logout").addEventListener("click", async () => {
    try { await fetch("/api/auth/logout", { method: "POST" }); } finally { window.location.reload(); }
  });

  fetch("/api/auth/me")
    .then(async (response) => {
      if (!response.ok) return null;
      return response.json();
    })
    .then((user) => { if (user) showSignedIn(user); })
    .catch(() => {});
})();
