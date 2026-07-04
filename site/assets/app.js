const cards = Array.from(document.querySelectorAll(".event-card"));
const list = document.querySelector("#event-list");
const controls = {
  keyword: document.querySelector("#keyword"),
  genre: document.querySelector("#genre"),
  format: document.querySelector("#format"),
  eventType: document.querySelector("#event-type"),
  fee: document.querySelector("#fee"),
  month: document.querySelector("#month"),
  deadlineOpen: document.querySelector("#deadline-open"),
  sort: document.querySelector("#sort"),
};

function normalize(value) {
  return String(value || "")
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[\s\-_ー]+/g, "");
}

async function sha256(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function pdfQueryHashes(query) {
  const value = normalize(query);
  if (value.length < 2 || !crypto.subtle) return [];
  const grams = new Set();
  for (const size of [2, 3]) {
    for (let index = 0; index <= value.length - size; index += 1) {
      grams.add(value.slice(index, index + size));
    }
  }
  return Promise.all(Array.from(grams).map(sha256));
}

async function applyFilters() {
  const query = normalize(controls.keyword?.value);
  const queryHashes = await pdfQueryHashes(query);
  const now = new Date();
  let visible = 0;

  for (const card of cards) {
    const plainMatch = !query || normalize(card.dataset.search).includes(query);
    const availableHashes = new Set(
      (card.dataset.pdfHashes || "").split(",").filter(Boolean)
    );
    const pdfMatch =
      queryHashes.length > 0 &&
      queryHashes.every((hash) => availableHashes.has(hash));
    const deadline = card.dataset.deadline
      ? new Date(card.dataset.deadline)
      : null;
    const matches =
      (plainMatch || pdfMatch) &&
      (!controls.genre.value ||
        card.dataset.genre.split("|").includes(controls.genre.value)) &&
      (!controls.format.value ||
        card.dataset.format === controls.format.value) &&
      (!controls.eventType.value ||
        card.dataset.eventType === controls.eventType.value) &&
      (!controls.fee.value || card.dataset.fee === controls.fee.value) &&
      (!controls.month.value ||
        card.dataset.date.startsWith(controls.month.value)) &&
      (!controls.deadlineOpen.checked || (deadline && deadline >= now));
    card.hidden = !matches;
    const hit = card.querySelector(".pdf-hit");
    if (hit) hit.hidden = !pdfMatch || plainMatch;
    if (matches) visible += 1;
  }

  sortCards();
  document.querySelector("#result-count").textContent = String(visible);
  document.querySelector("#no-results").hidden = visible !== 0;
  const labels = [
    controls.genre.value,
    controls.format.value,
    controls.eventType.value,
    controls.fee.value,
    controls.month.value,
    controls.deadlineOpen.checked ? "申込受付中" : "",
  ].filter(Boolean);
  document.querySelector("#active-filters").textContent = labels.length
    ? `選択中: ${labels.join(" / ")}`
    : "すべての条件";
}

function sortCards() {
  const mode = controls.sort.value;
  const sorted = [...cards].sort((a, b) => {
    if (mode === "title") {
      return a.querySelector("h3").textContent.localeCompare(
        b.querySelector("h3").textContent,
        "ja"
      );
    }
    const key = mode === "deadline" ? "deadline" : "date";
    return (a.dataset[key] || "9999").localeCompare(
      b.dataset[key] || "9999"
    );
  });
  sorted.forEach((card) => list.appendChild(card));
}

function loadQueryParameters() {
  const params = new URLSearchParams(location.search);
  if (params.get("q")) controls.keyword.value = params.get("q");
  if (params.get("genre")) controls.genre.value = params.get("genre");
  if (params.get("format")) controls.format.value = params.get("format");
}

Object.values(controls)
  .filter(Boolean)
  .forEach((control) => {
    control.addEventListener(
      control.tagName === "INPUT" && control.type === "search"
        ? "input"
        : "change",
      applyFilters
    );
  });

document.querySelector("#clear-filters")?.addEventListener("click", () => {
  Object.entries(controls).forEach(([name, control]) => {
    if (!control || name === "sort") return;
    if (control.type === "checkbox") control.checked = false;
    else control.value = "";
  });
  applyFilters();
  controls.keyword.focus();
});

loadQueryParameters();
applyFilters();
