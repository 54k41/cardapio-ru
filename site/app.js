/* Cardápio RU – front-end estático.
   Busca data/cardapio.json; se falhar, usa cache local (localStorage). */

const MEAL_ORDER = ["cafe", "almoco", "jantar"];
const MEAL_NAMES = {
  cafe: "Café da manhã",
  almoco: "Almoço",
  jantar: "Jantar",
};
const HIGHLIGHT = ["Prato Principal Padrão", "Sopa"]; // itens com destaque visual

const DOW_LONG = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"];

let state = {
  data: null,
  stale: false,
  selectedDay: null,
  selectedMeal: "almoco",
};

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function loadData() {
  try {
    const res = await fetch("data/cardapio.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    localStorage.setItem("cardapio-cache", JSON.stringify(json));
    return { json, stale: false };
  } catch (e) {
    console.warn("Falha ao buscar cardápio:", e);
    const cached = localStorage.getItem("cardapio-cache");
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
  const items = dayMenu[state.selectedMeal];

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

function renderFooter() {
  const updatedAt = document.getElementById("updated-at");
  const sourceLink = document.getElementById("source-link");
  const { generated_at, sources } = state.data;

  updatedAt.textContent =
    `Atualizado em ${new Date(generated_at).toLocaleString("pt-BR")}` +
    (state.stale ? " · dados salvos" : "");

  const src = sources && sources.find(s => s.url);
  if (src) {
    sourceLink.href = src.url;
    sourceLink.hidden = false;
  }
}

function render() {
  if (!state.data) {
    document.getElementById("menu-card").innerHTML =
      `<div class="unavailable"><span class="big">🍽️</span>
       Não foi possível carregar o cardápio.<br>Verifique sua conexão e recarregue a página.</div>`;
    document.getElementById("day-tabs").innerHTML = "";
    return;
  }
  renderStatus();
  renderTabs();
  renderMenu();
  renderFooter();
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
  const { json, stale } = await loadData();
  state.data = json;
  state.stale = stale;

  if (!json || !Object.keys(json.days).length) {
    render();
    return;
  }

  const isos = Object.keys(json.days);
  const today = todayISO();
  state.selectedDay = isos.includes(today)
    ? today
    : isos.find(i => i >= today) || isos[0];

  if (json.meals_order) MEAL_ORDER.splice(0, MEAL_ORDER.length, ...json.meals_order);
  Object.assign(MEAL_NAMES, json.meals_names || {});
  render();
})();
