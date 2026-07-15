const header = document.querySelector("[data-header]");
const menuButton = document.querySelector("[data-menu-button]");
const menu = document.querySelector("[data-menu]");

window.addEventListener("scroll", () => header?.classList.toggle("compact", window.scrollY > 24), { passive: true });
menuButton?.addEventListener("click", () => {
  const open = menu?.classList.toggle("open") ?? false;
  menuButton.setAttribute("aria-expanded", String(open));
});
menu?.querySelectorAll("a").forEach((link) => link.addEventListener("click", () => {
  menu.classList.remove("open");
  menuButton?.setAttribute("aria-expanded", "false");
}));

window.addEventListener("load", () => {
  if (!window.gsap || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  window.gsap.registerPlugin(window.ScrollTrigger);
  const heroItems = document.querySelectorAll(".hero-copy > *");
  const matchCard = document.querySelector(".match-card");
  if (heroItems.length) window.gsap.from(heroItems, { opacity: 0, y: 28, duration: .8, stagger: .1, ease: "power3.out" });
  if (matchCard) {
    window.gsap.from(matchCard, { opacity: 0, scale: .9, rotate: -7, duration: 1.1, delay: .2, ease: "expo.out" });
    window.gsap.to(matchCard, { y: -14, duration: 2.8, repeat: -1, yoyo: true, ease: "sine.inOut" });
  }
  window.gsap.utils.toArray(".reveal").forEach((element) => {
    if (element.closest(".hero")) return;
    window.gsap.from(element, { scrollTrigger: { trigger: element, start: "top 86%" }, opacity: 0, y: 36, duration: .85, ease: "power3.out" });
  });
  window.gsap.to(".grid-plane", { backgroundPositionY: "180px", ease: "none", scrollTrigger: { scrub: 1 } });
});

const feedbackForm = document.querySelector("[data-feedback-form]");
feedbackForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = feedbackForm.querySelector("[data-form-status]");
  const button = feedbackForm.querySelector("button[type='submit']");
  const data = Object.fromEntries(new FormData(feedbackForm).entries());
  button.disabled = true;
  status.textContent = "Sending…";
  status.className = "";
  try {
    const response = await fetch("/api/v1/feedback", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Submission failed.");
    status.textContent = `Received as #${result.id}. Thank you.`;
    status.className = "success";
    feedbackForm.reset();
  } catch (error) {
    status.textContent = error.message;
    status.className = "error";
  } finally {
    button.disabled = false;
  }
});
