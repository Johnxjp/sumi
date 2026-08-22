const form = document.getElementById("search-form");
const queryInput = document.getElementById("query");
const topKInput = document.getElementById("top-k");
const runButton = document.getElementById("run");
const statusLine = document.getElementById("status");
const errorBanner = document.getElementById("errors");
const results = document.getElementById("results");
const cardTemplate = document.getElementById("card-template");

let currentQuery = "";

async function loadRetrievers() {
  try {
    const res = await fetch("/api/retrievers");
    const data = await res.json();
    statusLine.textContent = `${data.retrievers.length} retrievers configured`;
  } catch {
    statusLine.textContent = "could not reach backend";
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = queryInput.value.trim();
  if (!query) return;

  runButton.disabled = true;
  try {
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, top_k: Number(topKInput.value) || 10 }),
    });
    if (!res.ok) throw new Error(`search failed: ${res.status}`);
    const data = await res.json();
    currentQuery = data.query;
    renderErrors(data.retriever_errors);
    renderChunks(data.chunks);
  } catch (err) {
    errorBanner.hidden = false;
    errorBanner.textContent = String(err);
  } finally {
    runButton.disabled = false;
  }
});

function renderErrors(errors) {
  const names = Object.keys(errors);
  errorBanner.hidden = names.length === 0;
  errorBanner.textContent = names
    .map((name) => `${name} failed: ${errors[name]}`)
    .join(" — ");
}

function renderChunks(chunks) {
  results.replaceChildren();
  if (chunks.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No results.";
    results.append(empty);
    return;
  }
  for (const chunk of chunks) {
    results.append(buildCard(chunk));
  }
}

function buildCard(chunk) {
  const card = cardTemplate.content.firstElementChild.cloneNode(true);
  const textBlock = card.querySelector(".chunk-text");
  const showMore = card.querySelector(".show-more");
  const pills = card.querySelector(".pills");

  if (chunk.text) {
    textBlock.textContent = chunk.text;
  } else {
    textBlock.textContent = "(no text returned)";
    textBlock.classList.add("no-text");
  }
  textBlock.classList.add("clamped");
  requestAnimationFrame(() => {
    if (textBlock.scrollHeight > textBlock.clientHeight) showMore.hidden = false;
  });
  showMore.addEventListener("click", () => {
    const clamped = textBlock.classList.toggle("clamped");
    showMore.textContent = clamped ? "show more" : "show less";
  });

  for (const [key, value] of Object.entries(chunk.metadata || {})) {
    const pill = document.createElement("span");
    pill.className = "pill";
    pill.textContent = `${key}: ${value}`;
    pills.append(pill);
  }

  if (chunk.annotation !== null) setSelected(card, chunk.annotation);

  for (const button of card.querySelectorAll(".score-buttons button")) {
    button.addEventListener("click", () => {
      const score = Number(button.dataset.score);
      setSelected(card, score);
      saveAnnotation(card, chunk, score);
    });
  }
  return card;
}

function setSelected(card, score) {
  card.classList.add("annotated");
  card.querySelector(".badge").hidden = false;
  for (const button of card.querySelectorAll(".score-buttons button")) {
    button.classList.toggle("selected", Number(button.dataset.score) === score);
  }
}

async function saveAnnotation(card, chunk, score) {
  const saveStatus = card.querySelector(".save-status");
  saveStatus.classList.remove("error");
  saveStatus.textContent = "saving…";
  saveStatus.onclick = null;
  try {
    const res = await fetch("/api/annotations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: currentQuery,
        chunk_key: chunk.chunk_key,
        score,
        text: chunk.text,
        metadata: chunk.metadata,
        sources: chunk.sources,
      }),
    });
    if (!res.ok) throw new Error(`status ${res.status}`);
    saveStatus.textContent = "saved";
    setTimeout(() => {
      if (saveStatus.textContent === "saved") saveStatus.textContent = "";
    }, 1500);
  } catch {
    saveStatus.classList.add("error");
    saveStatus.textContent = "save failed — click to retry";
    saveStatus.onclick = () => saveAnnotation(card, chunk, score);
  }
}

loadRetrievers();
