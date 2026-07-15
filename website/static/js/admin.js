const loginForm = document.querySelector("[data-admin-login]");
const statusNode = document.querySelector("[data-admin-status]");
const queueNode = document.querySelector("[data-feedback-queue]");
const statsNode = document.querySelector("[data-admin-stats]");

const token = () => sessionStorage.getItem("aestron-admin-token") || "";
const headers = () => ({ "Content-Type": "application/json", Authorization: `Bearer ${token()}` });

async function loadAdmin() {
  statusNode.textContent = "Loading…";
  const [feedbackResponse, statsResponse] = await Promise.all([
    fetch("/api/v1/admin/feedback", { headers: headers() }),
    fetch("/api/v1/admin/stats", { headers: headers() }),
  ]);
  if (!feedbackResponse.ok || !statsResponse.ok) throw new Error("Authentication failed or the admin API is unavailable.");
  const feedback = await feedbackResponse.json();
  const stats = await statsResponse.json();
  statusNode.textContent = `${feedback.length} recent items loaded.`;
  statsNode.innerHTML = Object.entries(stats.feedback).map(([name, count]) => `<span>${escapeHtml(name)}: <b>${count}</b></span>`).join("");
  queueNode.innerHTML = feedback.map(renderFeedback).join("") || "<p>No feedback yet.</p>";
  queueNode.querySelectorAll("[data-status]").forEach((button) => button.addEventListener("click", () => updateStatus(button.dataset.id, button.dataset.status)));
}

function renderFeedback(item) {
  const actions = ["reviewing", "planned", "resolved", "rejected"].map((state) => `<button data-id="${item.id}" data-status="${state}">${state}</button>`).join("");
  return `<article class="feedback-item"><div class="feedback-meta"><span>#${item.id} · ${escapeHtml(item.kind)} · ${escapeHtml(item.status)}</span><time>${new Date(item.created_at).toLocaleString()}</time></div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.body)}</p><div class="feedback-actions">${actions}</div></article>`;
}

async function updateStatus(id, newStatus) {
  const response = await fetch(`/api/v1/admin/feedback/${id}`, { method: "PATCH", headers: headers(), body: JSON.stringify({ status: newStatus }) });
  if (!response.ok) { statusNode.textContent = "Could not update the item."; return; }
  await loadAdmin();
}

function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = String(value ?? "");
  return node.innerHTML;
}

loginForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  sessionStorage.setItem("aestron-admin-token", new FormData(loginForm).get("token"));
  try { await loadAdmin(); } catch (error) { statusNode.textContent = error.message; }
});
if (token()) loadAdmin().catch(() => sessionStorage.removeItem("aestron-admin-token"));
