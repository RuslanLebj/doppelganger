"use strict";

(() => {
  const key = "doppelganger-theme";
  const system = window.matchMedia("(prefers-color-scheme: dark)");
  const valid = (value) => (["light", "dark"].includes(value) ? value : null);
  let preference = null;

  try {
    preference = valid(localStorage.getItem(key));
  } catch {
    // The page remains usable when browser storage is unavailable.
  }

  function apply() {
    const theme = preference || (system.matches ? "dark" : "light");
    document.documentElement.dataset.theme = theme;
    const label =
      theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему";
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.title = label;
      button.setAttribute("aria-label", label);
      button.setAttribute("aria-pressed", String(theme === "dark"));
    });
  }

  // Apply before CSS loads to avoid flashing the other theme during navigation.
  apply();

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        preference =
          document.documentElement.dataset.theme === "dark" ? "light" : "dark";
        try {
          localStorage.setItem(key, preference);
        } catch {
          // Switching still works for this page without persistent storage.
        }
        apply();
      });
    });
    apply();
  });

  system.addEventListener("change", () => {
    if (!preference) apply();
  });
  window.addEventListener("storage", (event) => {
    if (event.key === key || event.key === null) {
      preference = valid(event.newValue);
      apply();
    }
  });
})();
