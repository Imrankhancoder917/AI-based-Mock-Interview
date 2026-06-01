document.addEventListener("DOMContentLoaded", () => {
  const toggles = document.querySelectorAll("[data-toggle-password]");

  toggles.forEach((toggle) => {
    toggle.addEventListener("click", () => {
      const targetId = toggle.getAttribute("data-target");
      const input = targetId ? document.getElementById(targetId) : null;

      if (!input) {
        return;
      }

      const isPassword = input.type === "password";
      input.type = isPassword ? "text" : "password";
      toggle.textContent = isPassword ? "Hide" : "Show";
    });
  });

  const forms = document.querySelectorAll(".auth-form");

  forms.forEach((form) => {
    form.addEventListener("submit", (event) => {
      const password = form.querySelector('#password');
      const confirmPassword = form.querySelector('#confirm_password');

      if (password && confirmPassword && password.value !== confirmPassword.value) {
        event.preventDefault();
        confirmPassword.classList.add("is-invalid");
        confirmPassword.focus();
      }
    });
  });
});