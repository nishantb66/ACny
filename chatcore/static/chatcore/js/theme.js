(() => {
  const THEME_KEY = "pulsepair-theme";
  const root = document.documentElement;
  const toggles = document.querySelectorAll("#themeToggleBtn");

  const getStoredTheme = () => {
    try {
      return localStorage.getItem(THEME_KEY);
    } catch (_error) {
      return null;
    }
  };

  const saveTheme = (value) => {
    try {
      localStorage.setItem(THEME_KEY, value);
    } catch (_error) {
      // no-op
    }
  };

  const isDark = () => root.dataset.theme === "dark";

  const updateToggleLabels = () => {
    const dark = isDark();
    toggles.forEach((button) => {
      button.textContent = dark ? "Light" : "Dark";
      button.setAttribute("aria-pressed", dark ? "true" : "false");
    });
  };

  const applyTheme = (theme) => {
    if (theme === "dark") {
      root.dataset.theme = "dark";
      saveTheme("dark");
    } else {
      delete root.dataset.theme;
      saveTheme("light");
    }
    updateToggleLabels();
  };

  toggles.forEach((button) => {
    button.addEventListener("click", () => {
      applyTheme(isDark() ? "light" : "dark");
    });
  });

  applyTheme(getStoredTheme() === "dark" ? "dark" : "light");
})();
