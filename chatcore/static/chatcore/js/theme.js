(() => {
  const THEME_KEY = "pulsepair-theme";
  const root = document.documentElement;
  const toggles = document.querySelectorAll("#themeToggleBtn");
  const THEME_DARK = "dark";
  const THEME_LIGHT = "light";

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

  const isDark = () => root.dataset.theme === THEME_DARK;

  const updateToggleLabels = () => {
    const dark = isDark();
    toggles.forEach((button) => {
      button.textContent = dark ? "Light" : "Dark";
      button.setAttribute("aria-pressed", dark ? "true" : "false");
      button.dataset.mode = dark ? THEME_DARK : THEME_LIGHT;
    });
  };

  const applyTheme = (theme) => {
    if (theme === THEME_DARK) {
      root.dataset.theme = THEME_DARK;
      saveTheme(THEME_DARK);
      root.style.colorScheme = THEME_DARK;
    } else {
      delete root.dataset.theme;
      saveTheme(THEME_LIGHT);
      root.style.colorScheme = THEME_LIGHT;
    }
    updateToggleLabels();
  };

  toggles.forEach((button) => {
    button.addEventListener("click", () => {
      applyTheme(isDark() ? THEME_LIGHT : THEME_DARK);
    });
  });

  applyTheme(getStoredTheme() === THEME_DARK ? THEME_DARK : THEME_LIGHT);
})();
