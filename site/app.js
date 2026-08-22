/* Cardápio RU – front-end estático.
   Busca data/cardapio-<campus>.json; se falhar, usa cache local (localStorage). */

const MEAL_ORDER = ["cafe", "almoco", "jantar"];
const MEAL_NAMES = {
  cafe: "Café da manhã",
  almoco: "Almoço",
  jantar: "Jantar",
};
const HIGHLIGHT = ["Prato Principal Padrão"]; // itens com destaque visual

const DOW_LONG = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"];

const CAMPUS = [
  { id: "darcy",     name: "Darcy Ribeiro" },
  { id: "executivo", name: "Executivo" },
  { id: "fcts",      name: "Ceilândia · FCTS" },
  { id: "fcte",      name: "Gama · FCTE" },
  { id: "fup",       name: "Planaltina · FUP" },
  { id: "fal",       name: "FAL" },
];
const DEFAULT_CAMPUS = "darcy";

let state = {
  campus: null,
  data: null,
  stale: false,
  selectedDay: null,
  selectedMeal: "almoco",
};

function todayISO() {
  // Data de hoje no fuso de Brasília (UTC-3), independente do relógio do dispositivo
  const now = new Date();
  const bsb = new Date(now.getTime() - 3 * 60 * 60 * 1000 + now.getTimezoneOffset() * 60 * 1000);
  return `${bsb.getFullYear()}-${String(bsb.getMonth() + 1).padStart(2, "0")}-${String(bsb.getDate()).padStart(2, "0")}`;
}

function campusFile(id) {
  return `data/cardapio-${id}.json`;
}

async function loadCampus(id) {
  try {
    const res = await fetch(campusFile(id), { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    localStorage.setItem(`cardapio-cache-${id}`, JSON.stringify(json));
    return { json, stale: false };
  } catch (e) {
    console.warn("Falha ao buscar cardápio:", e);
    const cached = localStorage.getItem(`cardapio-cache-${id}`);
    if (cached) return { json: JSON.parse(cached), stale: true };
    return { json: null, stale: false };
  }
}

function fmtDay(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return { dow: DOW_LONG[dt.getDay()], dom: d };
}

function renderStatus() {
  const banner = document.getElementById("status-banner");
  if (state.stale) {
    banner.textContent = "⚠ Não foi possível atualizar agora — exibindo o último cardápio salvo.";
    banner.hidden = false;
  } else {
    banner.hidden = true;
  }
}

function renderTabs() {
  const tabs = document.getElementById("day-tabs");
  const isos = Object.keys(state.data.days);
  const today = todayISO();
  tabs.innerHTML = "";
  for (const iso of isos) {
    const { dow, dom } = fmtDay(iso);
    const btn = document.createElement("button");
    btn.className = "day-tab" + (iso === state.selectedDay ? " active" : "");
    if (iso === today) btn.title = "Hoje";
    btn.innerHTML = `<span class="dow">${dow}${iso === today ? " · hoje" : ""}</span><span class="dom">${dom}</span>`;
    btn.addEventListener("click", () => {
      state.selectedDay = iso;
      render();
    });
    tabs.appendChild(btn);
  }
  const active = tabs.querySelector(".day-tab.active");
  if (active) active.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
}

function renderMenu() {
  const card = document.getElementById("menu-card");
  const dayMenu = state.data.days[state.selectedDay] || {};
  const mealKey = state.data.meals_order.includes(state.selectedMeal)
    ? state.selectedMeal : state.data.meals_order[0];
  const items = dayMenu[mealKey];

  card.style.animation = "none";
  void card.offsetWidth; // reinicia a animação
  card.style.animation = "";

  if (!items || !items.length) {
    card.innerHTML = `<div class="unavailable"><span class="big">🍽️</span>
      Cardápio indisponível para esta refeição.</div>`;
    return;
  }

  const dl = document.createElement("dl");
  for (const it of items) {
    const wrap = document.createElement("div");
    wrap.className = "menu-item" + (HIGHLIGHT.includes(it.label) ? " highlight" : "");
    const dt = document.createElement("dt");
    dt.textContent = it.label;
    const dd = document.createElement("dd");
    dd.textContent = it.value;
    wrap.append(dt, dd);
    dl.appendChild(wrap);
  }
  card.innerHTML = "";
  card.appendChild(dl);
}

function renderMealSwitch() {
  // ajusta as abas de refeição às refeições disponíveis no campus atual
  const order = state.data.meals_order || MEAL_ORDER;
  if (!order.includes(state.selectedMeal)) state.selectedMeal = order[0];
  const names = Object.assign({}, MEAL_NAMES, state.data.meals_names || {});
  document.querySelectorAll(".meal-switch button").forEach(btn => {
    const meal = btn.dataset.meal;
    const available = order.includes(meal);
    btn.style.display = available ? "" : "none";
    btn.hidden = !available;
    if (!available) return;
    btn.classList.toggle("active", meal === state.selectedMeal);
    // rótulo pode variar por campus (ex.: "Cardápio" no Executivo)
    const label = names[meal] || meal;
    const long = btn.querySelector(".long"), short = btn.querySelector(".short");
    if (long) long.textContent = label;
    if (short) short.textContent = label;
  });
}

function renderFooter() {
  const updatedAt = document.getElementById("updated-at");
  const sourceLink = document.getElementById("source-link");
  const { generated_at, sources } = state.data;

  // generated_at vem em horário de Brasília (-03:00); exibir como está
  const raw = String(generated_at).replace(/-0?3:?00$/, "");
  const dt = new Date(raw.endsWith("Z") ? raw : raw + "-03:00");
  updatedAt.textContent =
    "Atualizado em " + dt.toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" }) +
    (state.stale ? " · dados salvos" : "");

  const src = sources && sources.find(s => s.url);
  if (src && src.url) {
    sourceLink.href = src.url;
    sourceLink.hidden = false;
  } else {
    sourceLink.hidden = true;
  }
}

function render() {
  if (!state.data || !Object.keys(state.data.days || {}).length) {
    document.getElementById("menu-card").innerHTML =
      `<div class="unavailable"><span class="big">🍽️</span>
       Não foi possível carregar o cardápio deste campus.<br>Verifique sua conexão e recarregue a página.</div>`;
    document.getElementById("day-tabs").innerHTML = "";
    return;
  }
  renderStatus();
  renderTabs();
  renderMealSwitch();
  renderMenu();
  renderFooter();
}

async function selectCampus(id, { updateHash = true } = {}) {
  state.campus = id;
  localStorage.setItem("cardapio-campus", id);
  if (updateHash) history.replaceState(null, "", `#${id}`);

  // marca o seletor
  const sel = document.getElementById("campus-select");
  if (sel) sel.value = id;

  state.data = null;
  state.stale = false;
  state.selectedDay = null;
  document.getElementById("menu-card").innerHTML =
    `<div class="unavailable"><span class="big">⏳</span> Carregando…</div>`;

  const { json, stale } = await loadCampus(id);
  state.data = json;
  state.stale = stale;

  if (json && Object.keys(json.days).length) {
    const isos = Object.keys(json.days);
    const today = todayISO();
    state.selectedDay = isos.includes(today)
      ? today
      : isos.find(i => i >= today) || isos[0];
    const order = json.meals_order || MEAL_ORDER;
    if (!order.includes(state.selectedMeal)) state.selectedMeal = order[0];
  }
  render();
}

function setupCampusSelect() {
  const sel = document.getElementById("campus-select");
  sel.value = state.campus;
  sel.addEventListener("change", () => selectCampus(sel.value));
}

function setupMealSwitch() {
  document.querySelectorAll(".meal-switch button").forEach(btn => {
    btn.addEventListener("click", () => {
      state.selectedMeal = btn.dataset.meal;
      document.querySelectorAll(".meal-switch button").forEach(b =>
        b.classList.toggle("active", b === btn));
      renderMenu();
    });
  });
}

(async function init() {
  setupMealSwitch();

  // campus inicial: hash da URL > preferência salva > padrão
  const fromHash = location.hash.replace("#", "");
  const saved = localStorage.getItem("cardapio-campus");
  let campus = CAMPUS.find(c => c.id === fromHash)?.id
            || CAMPUS.find(c => c.id === saved)?.id
            || DEFAULT_CAMPUS;

  await selectCampus(campus, { updateHash: false });
  setupCampusSelect();
})();
