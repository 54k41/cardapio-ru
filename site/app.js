/* Cardápio RU – front-end estático.
   Busca data/cardapio-<campus>.json; se falhar, usa cache local (localStorage). */

const MEAL_ORDER = ["cafe", "almoco", "jantar"];
const MEAL_NAMES = {
  cafe: "Café da manhã",
  almoco: "Almoço",
  jantar: "Jantar",
};
const HIGHLIGHT = ["Prato Principal Padrão"]; // itens com destaque visual
const SHORT_NAMES = { cafe: "Café", almoco: "Almoço", jantar: "Jantar" };

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

function weekStartISO(iso) {
  // Segunda-feira da semana de `iso` (semanas do RU começam na segunda)
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() - (dt.getDay() + 6) % 7);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
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
    try {
      const cached = localStorage.getItem(`cardapio-cache-${id}`);
      if (cached) return { json: JSON.parse(cached), stale: true };
    } catch (cacheErr) {
      console.warn("Cache local inválido:", cacheErr);
    }
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
  const isos = Object.keys(state.data.days);
  // cardápio de uma semana anterior à atual (PDF novo ainda não publicado)
  const outdated = isos.length && weekStartISO(todayISO()) > isos[isos.length - 1];
  if (state.stale || outdated) {
    banner.textContent = state.stale
      ? "⚠ Não foi possível atualizar agora — exibindo o último cardápio salvo."
      : "⚠ Exibindo o cardápio da semana anterior — a atualização da semana ainda não foi publicada.";
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
    btn.setAttribute("aria-pressed", iso === state.selectedDay);
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
  // ajusta as abas de refeição às refeições DISPONÍVEIS no dia selecionado
  // (ex.: FAL não tem jantar; FAL não tem café no sábado; FCTS não tem
  // jantar no sábado) — sem dados no dia, a aba fica oculta
  const order = state.data.meals_order || MEAL_ORDER;
  const dayMenu = (state.data.days || {})[state.selectedDay] || {};
  let available = order.filter(m => dayMenu[m] && dayMenu[m].length);
  if (!available.length) available = order; // dia sem dados: mostra todas
  // seleção pode ser de outro campus/dia (ex.: "principal" do Executivo);
  // prefere almoço, o padrão dos campi tabelados
  if (!available.includes(state.selectedMeal)) {
    state.selectedMeal = available.includes("almoco") ? "almoco" : available[0];
  }
  const names = Object.assign({}, MEAL_NAMES, state.data.meals_names || {});
  document.querySelectorAll(".meal-switch button").forEach(btn => {
    const meal = btn.dataset.meal;
    const shown = available.includes(meal);
    btn.hidden = !shown;
    if (!shown) return;
    const active = meal === state.selectedMeal;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active);
    // rótulo pode variar por campus (ex.: "Cardápio" no Executivo); o curto
    // nunca pode receber o nome completo — senão estoura o botão no mobile
    const label = names[meal] || meal;
    const long = btn.querySelector(".long"), short = btn.querySelector(".short");
    if (long) long.textContent = label;
    if (short) short.textContent = SHORT_NAMES[meal] || label;
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

  // marca o seletor e o título da página
  const sel = document.getElementById("campus-select");
  if (sel) sel.value = id;
  const meta = CAMPUS.find(c => c.id === id);
  document.title = `Cardápio RU · ${meta ? meta.name : "UnB"}`;

  state.data = null;
  state.stale = false;
  state.selectedDay = null;
  document.getElementById("menu-card").innerHTML =
    `<div class="unavailable"><span class="big">⏳</span> Carregando…</div>`;

  const { json, stale } = await loadCampus(id);
  if (state.campus !== id) return; // o usuário trocou de campus enquanto carregava

  state.data = json;
  state.stale = stale;

  if (json && Object.keys(json.days).length) {
    const isos = Object.keys(json.days);
    const today = todayISO();
    // sem dia atual/ futuro no cardápio, mostra o dia mais recente disponível
    // (o banner de "semana anterior" sinaliza a situação)
    state.selectedDay = isos.includes(today)
      ? today
      : isos.find(i => i >= today) || isos[isos.length - 1];
    const order = json.meals_order || MEAL_ORDER;
    if (!order.includes(state.selectedMeal)) state.selectedMeal = order.includes("almoco") ? "almoco" : order[0];
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
      if (!state.data) return; // ainda carregando
      state.selectedMeal = btn.dataset.meal;
      renderMealSwitch();
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

  // troca de campus ao navegar por hash (ex.: colar um link #fcte depois do load)
  window.addEventListener("hashchange", () => {
    const id = CAMPUS.find(c => c.id === location.hash.replace("#", ""))?.id;
    if (id && id !== state.campus) selectCampus(id, { updateHash: false });
  });
})();
