const tabButtons = document.querySelectorAll("[data-tab-target]");
const tabs = document.querySelectorAll("[data-tab]");
tabButtons.forEach((button) => button.addEventListener("click", () => {
  tabButtons.forEach((item) => item.classList.remove("active"));
  tabs.forEach((tab) => tab.classList.remove("active"));
  button.classList.add("active");
  document.querySelector(`[data-tab='${button.dataset.tabTarget}']`)?.classList.add("active");
}));
