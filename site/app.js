/* Cardápio RU · UnB — front-end estático (Opção A · Editorial UnB).
 *
 * Sem dependências. Busca data/cardapio-<campus>.json, mantém em memória os
 * campi já visitados (troca instantânea) e cai para o cache local quando não
 * há rede (subsolo do ICC/Minhocão).
 */

"use strict";

const MEAL_ORDER = ["cafe", "almoco", "jantar"];
const MEAL_LABELS = { cafe: "Café", almoco: "Almoço", jantar: "Jantar", principal: "Cardápio" };
const DOW_LONG = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"];
const DOW_SHORT = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
const MONTH_SHORT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

const CAMPUS = [
  { id: "darcy", name: "Darcy Ribeiro" },
  { id: "executivo", name: "Executivo" },
  { id: "fcts", name: "Ceilândia · FCTS" },
  { id: "fcte", name: "Gama · FCTE" },
  { id: "fup", name: "Planaltina · FUP" },
  { id: "fal", name: "FAL · Fazenda" }
];
const DEFAULT_CAMPUS = "darcy";

/* Preferência alimentar. Os PDFs tabelados publicam três variantes do prato
   principal (e do complemento do café); o Executivo publica um cardápio só,
   então o seletor some quando não há o que escolher. */
const DIET_KEY = "cardapio-dieta";
const DIET_DEFAULT = "padrao";
const DIET_LABEL = { padrao: "Padrão", ovolacto: "Ovolacto", estrito: "Estrito" };

const state = {
  campus: null,
  data: null,
  stale: false,
  days: [],
  weeks: [],
  weekIndex: 0,
  selectedDay: null,
  selectedMeal: "almoco",
  mealPinned: false,
  diet: DIET_DEFAULT,
  hasDiet: false
};

/* ---------------------------------------------------------------------------
   Utilidades de armazenamento (localStorage pode lançar exceção: modo privado
   do Safari, cota estourada, storage bloqueado por política)
--------------------------------------------------------------------------- */
function storeGet(key) {
  try {
    return localStorage.getItem(key);
  } catch (e) {
    console.warn("localStorage indisponível para leitura:", e);
    return null;
  }
}

function storeSet(key, value) {
  try {
    localStorage.setItem(key, value);
    return true;
  } catch (e) {
    console.warn("localStorage indisponível para escrita:", e);
    return false;
  }
}

/* ---------------------------------------------------------------------------
   Datas (Brasília, UTC-3 sem horário de verão desde 2019)
--------------------------------------------------------------------------- */
function bsbNow() {
  // Desloca o instante pelo offset de Brasília e lê em UTC: assim o fuso do
  // aparelho não entra na conta (getTimezoneOffset erra na transição do DST)
  return new Date(Date.now() - 3 * 60 * 60 * 1000);
}

function todayISO() {
  return bsbNow().toISOString().slice(0, 10);
}

function parseISO(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function isoOf(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

/* segunda-feira da semana de `iso` (as semanas do RU começam na segunda) */
function weekStartISO(iso) {
  const dt = parseISO(iso);
  dt.setDate(dt.getDate() - (dt.getDay() + 6) % 7);
  return isoOf(dt);
}

/* Refeição provável agora: o RU abre o café cedo, almoço no meio do dia e o
   jantar à noite. Fora do horário (madrugada), mostra o almoço do dia — é a
   próxima refeição servida. */
function mealForNow() {
  const now = bsbNow();
  const h = now.getUTCHours() + now.getUTCMinutes() / 60;
  if (h >= 4 && h < 10.5) return "cafe";
  if (h >= 10.5 && h < 15.5) return "almoco";
  if (h >= 15.5 && h < 21) return "jantar";
  return "almoco";
}

function fmtWeekLabel(weekStart, days) {
  const first = days.length ? days[0] : weekStart;
  const last = days.length ? days[days.length - 1] : weekStart;
  const a = parseISO(first);
  const b = parseISO(last);
  if (a.getMonth() === b.getMonth()) {
    return `${a.getDate()} a ${b.getDate()} de ${MONTH_SHORT[b.getMonth()]}`;
  }
  return `${a.getDate()} ${MONTH_SHORT[a.getMonth()]} a ${b.getDate()} ${MONTH_SHORT[b.getMonth()]}`;
}

/* ---------------------------------------------------------------------------
   Normalização de rótulos (comparação sem acento/caixa)
--------------------------------------------------------------------------- */
const ACCENTS = /[\u0300-\u036f]/g;

function norm(text) {
  return (text || "").toLowerCase().normalize("NFD").replace(ACCENTS, "").replace(/\s+/g, " ").trim();
}

function dietOf(label) {
  const l = norm(label);
  if (l.includes("vegetariano estrito")) return "estrito";
  if (l.includes("ovolactovegetariano")) return "ovolacto";
  // só conta como variante "Padrão" o rótulo que diz isso: no Executivo o
  // rótulo é "Prato Principal 1" e não existe escolha de dieta
  if (/\bpadrao\b/.test(l)) return "padrao";
  return null;
}

/* Grupos de itens. O que é burocrático (salada, molho, sobremesa, refresco,
   sopa, torrada) vai em linha corrida para a refeição inteira caber na
   primeira dobra do celular; o prato principal fica como manchete. */
const GROUPS_MEAL = [
  { id: "principal", title: "Prato principal", main: true, test: l => l.startsWith("prato principal") },
  { id: "acomp", title: "Acompanhamentos", test: l => /^(guarnicao|acompanhamento)/.test(l) },
  { id: "saladas", title: "Saladas", inline: true, test: l => /^(salada|molho)/.test(l) },
  { id: "sobremesa", title: "Sobremesa e refresco", inline: true, test: l => /^(sobremesa|bebida)/.test(l) },
  { id: "sopa", title: "Sopa e torrada", inline: true, test: l => /^(sopa|torrada)/.test(l) },
  { id: "outros", title: "Outros", test: () => true }
];

const GROUPS_CAFE = [
  { id: "principal", title: "Complemento principal", main: true, test: l => l.startsWith("complemento") },
  { id: "cafe", title: "Pão, bebida e fruta", inline: true, test: l => /^(panificacao|bebidas|gordura|opcao extra|fruta)/.test(l) },
  { id: "outros", title: "Outros", test: () => true }
];

/* ---------------------------------------------------------------------------
   Carga dos dados
--------------------------------------------------------------------------- */
const memory = new Map(); // campus -> { json, stale } (troca de campus sem flash)

function campusFile(id) {
  return `data/cardapio-${id}.json`;
}

function isCampusData(json) {
  return json && typeof json === "object" && json.days && typeof json.days === "object";
}

async function fetchCampus(id) {
  const res = await fetch(campusFile(id), { cache: "no-cache" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const json = await res.json();
  if (!isCampusData(json)) throw new Error("JSON inesperado (sem 'days')");
  return json;
}

async function loadCampus(id) {
  try {
    const json = await fetchCampus(id);
    // guardar o cache é opcional: se falhar (cota cheia), os dados recém
    // baixados continuam valendo nesta sessão
    storeSet(`cardapio-cache-${id}`, JSON.stringify(json));
    return { json, stale: false };
  } catch (e) {
    console.warn("Falha ao buscar cardápio:", e);
    const cached = storeGet(`cardapio-cache-${id}`);
    if (cached) {
      try {
        const json = JSON.parse(cached);
        if (isCampusData(json)) return { json, stale: true };
      } catch (cacheErr) {
        console.warn("Cache local inválido:", cacheErr);
      }
    }
    return { json: null, stale: false };
  }
}

/* ---------------------------------------------------------------------------
   Leitura do JSON do campus
--------------------------------------------------------------------------- */
function daysWithContent(json) {
  const days = (json && json.days) || {};
  return Object.keys(days)
    .filter(iso => {
      const day = days[iso] || {};
      const items = Object.keys(day).some(k => Array.isArray(day[k]) && day[k].length);
      return items || Boolean(day.note);
    })
    .sort();
}

function mealOrder(json) {
  const order = (json && json.meals_order && json.meals_order.length)
    ? json.meals_order.filter(m => MEAL_ORDER.includes(m) || m === "principal")
    : MEAL_ORDER;
  return order.length ? order : MEAL_ORDER;
}

function itemsOf(json, iso, meal) {
  const day = (json && json.days && json.days[iso]) || {};
  const items = day[meal];
  return Array.isArray(items) ? items : [];
}

function hasDietChoice(json) {
  for (const iso of Object.keys((json && json.days) || {})) {
    const day = json.days[iso] || {};
    for (const meal of Object.keys(day)) {
      const items = day[meal];
      if (Array.isArray(items) && items.some(it => dietOf(it.label))) return true;
    }
  }
  return false;
}

/* ---------------------------------------------------------------------------
   Renderização
--------------------------------------------------------------------------- */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function renderStatus() {
  const banner = document.getElementById("status-banner");
  const isos = state.days;
  let message = "";
  if (state.stale) {
    message = "Sem conexão — exibindo o último cardápio salvo neste aparelho.";
  } else if (isos.length) {
    const today = todayISO();
    const past = isos.filter(iso => iso <= today);
    const last = past[past.length - 1];
    if (!last) {
      message = "A semana atual ainda não foi publicada — mostrando a próxima.";
    } else if (weekStartISO(today) > weekStartISO(last)) {
      message = "Cardápio da semana anterior — a atual ainda não foi publicada.";
    }
  }
  banner.textContent = message;
  banner.hidden = !message;
}

function renderDayTabs() {
  const tabs = document.getElementById("day-tabs");
  const today = todayISO();
  const week = state.weeks[state.weekIndex] || { days: [] };
  tabs.innerHTML = "";
  for (const iso of week.days) {
    const dt = parseISO(iso);
    const selected = iso === state.selectedDay;
    const btn = el("button", "day-tab");
    btn.type = "button";
    btn.setAttribute("role", "tab");
    btn.setAttribute("aria-selected", String(selected));
    btn.setAttribute("aria-controls", "menu-card");
    btn.id = `tab-day-${iso}`;
    btn.tabIndex = selected ? 0 : -1;
    btn.dataset.day = iso;
    btn.dataset.today = String(iso === today);
    if (iso === today) btn.title = "Hoje";
    const dow = el("span", "dow", iso === today ? "hoje" : DOW_SHORT[dt.getDay()]);
    const dom = el("span", "dom", String(dt.getDate()));
    const dot = el("span", "dot");
    dot.setAttribute("aria-hidden", "true");
    btn.append(dow, dom, dot);
    btn.setAttribute("aria-label",
      `${DOW_LONG[dt.getDay()]}, ${dt.getDate()} de ${MONTH_SHORT[dt.getMonth()]}${iso === today ? " (hoje)" : ""}`);
    btn.addEventListener("click", () => selectDay(iso));
    tabs.appendChild(btn);
  }
}

function renderWeekChrome() {
  const prev = document.getElementById("week-prev");
  const next = document.getElementById("week-next");
  const label = document.getElementById("week-label");
  const many = state.weeks.length > 1;
  prev.hidden = !many;
  next.hidden = !many;
  if (!many) {
    label.hidden = true;
    return;
  }
  prev.disabled = state.weekIndex === 0;
  next.disabled = state.weekIndex === state.weeks.length - 1;
  const week = state.weeks[state.weekIndex];
  const text = `Semana de ${fmtWeekLabel(week.start, week.days)}`;
  label.textContent = state.weekIndex === state.weeks.length - 1 && week.days.every(d => d > todayISO())
    ? `${text} (próxima)`
    : text;
  label.hidden = false;
}

function renderMealSwitch() {
  const order = mealOrder(state.data);
  const day = (state.data.days || {})[state.selectedDay] || {};
  let available = order.filter(m => Array.isArray(day[m]) && day[m].length);
  if (!available.length) available = order; // dia sem dados: mostra todas
  if (!available.includes(state.selectedMeal)) {
    state.selectedMeal = available.includes("almoco") ? "almoco" : available[0];
  }
  document.querySelectorAll("#meal-tabs button").forEach(btn => {
    const meal = btn.dataset.meal;
    const shown = available.includes(meal);
    btn.hidden = !shown;
    btn.tabIndex = shown && meal === state.selectedMeal ? 0 : -1;
    const active = shown && meal === state.selectedMeal;
    btn.setAttribute("aria-selected", String(active));
    btn.textContent = MEAL_LABELS[meal] || meal;
  });
  const panel = document.getElementById("menu-card");
  const dayTab = document.getElementById(`tab-day-${state.selectedDay}`);
  const mealTab = document.getElementById(`tab-${state.selectedMeal}`);
  const label = [dayTab && dayTab.id, mealTab && mealTab.id].filter(Boolean).join(" ");
  if (label) panel.setAttribute("aria-labelledby", label);
  else panel.removeAttribute("aria-labelledby");
}

function renderDietSwitch() {
  const box = document.getElementById("diet-switch");
  box.hidden = !state.hasDiet;
  box.querySelectorAll(".diet-chip").forEach(chip => {
    chip.setAttribute("aria-pressed", String(chip.dataset.diet === state.diet));
  });
}

function buildGroups(items, meal) {
  const defs = meal === "cafe" ? GROUPS_CAFE : GROUPS_MEAL;
  const buckets = defs.map(def => Object.assign({ items: [] }, def));
  for (const it of items) {
    const l = norm(it.label);
    const bucket = buckets.find(b => b.test(l)) || buckets[buckets.length - 1];
    bucket.items.push(it);
  }
  return buckets.filter(b => b.items.length);
}

function kindOf(label) {
  return (label || "").replace(/\s*\d+\s*$/, "").trim();
}

function renderMenu() {
  const card = document.getElementById("menu-card");
  const day = (state.data.days || {})[state.selectedDay] || {};
  const items = itemsOf(state.data, state.selectedDay, state.selectedMeal)
    .filter(it => {
      const diet = dietOf(it.label);
      return !diet || diet === state.diet;
    });

  card.innerHTML = "";

  if (!items.length) {
    if (day.note) {
      const p = el("p", "notice");
      p.append(el("strong", "", day.note), document.createTextNode(
        " — o restaurante não abre neste dia."));
      card.appendChild(p);
    } else {
      const p = el("p", "notice");
      p.append(el("strong", "", MEAL_LABELS[state.selectedMeal] || "Refeição"),
        document.createTextNode(" não é servido neste dia neste campus."));
      card.appendChild(p);
    }
    return;
  }

  for (const bucket of buildGroups(items, state.selectedMeal)) {
    const section = el("section", "group");
    section.appendChild(el("h2", "group-title", bucket.title));
    if (bucket.inline) {
      const byKind = new Map();
      for (const it of bucket.items) {
        const kind = kindOf(it.label) || bucket.title;
        if (!byKind.has(kind)) byKind.set(kind, []);
        byKind.get(kind).push(it.value);
      }
      for (const [kind, values] of byKind) {
        const line = el("p", "inline-line");
        line.appendChild(el("span", "inline-kind", kind));
        line.appendChild(document.createTextNode(" " + values.join(" · ")));
        section.appendChild(line);
      }
    } else {
      bucket.items.forEach(it => {
        const p = el("p", bucket.main ? "dish dish--main" : "dish", it.value);
        if (!bucket.main) p.title = it.label;
        section.appendChild(p);
      });
    }
    card.appendChild(section);
  }

  // Dia sem a variante escolhida (acontece no café de alguns dias): em vez de
  // uma tela sem prato principal, mostra o que o RU publicou naquele dia —
  // e no topo, onde o prato principal estaria.
  const hasMain = items.some(it => GROUPS_MEAL.concat(GROUPS_CAFE)
    .some(g => g.main && g.test(norm(it.label))));
  if (!hasMain && state.hasDiet) {
    const alternatives = itemsOf(state.data, state.selectedDay, state.selectedMeal)
      .filter(it => {
        const diet = dietOf(it.label);
        return diet && diet !== state.diet;
      });
    if (alternatives.length) {
      const fallback = el("section", "group group--plain");
      const note = el("p", "notice notice--tight");
      note.append(el("strong", "", `Sem variante ${DIET_LABEL[state.diet]} neste dia.`),
        document.createTextNode(" O RU publicou:"));
      fallback.appendChild(note);
      const byDiet = new Map();
      for (const it of alternatives) {
        const diet = dietOf(it.label);
        if (!byDiet.has(diet)) byDiet.set(diet, []);
        byDiet.get(diet).push(it.value);
      }
      for (const [diet, values] of byDiet) {
        const line = el("p", "inline-line");
        line.appendChild(el("span", "inline-kind", DIET_LABEL[diet]));
        line.appendChild(document.createTextNode(" " + values.join(" · ")));
        fallback.appendChild(line);
      }
      card.insertBefore(fallback, card.firstChild);
    }
  }
}

function renderFooter() {
  const updatedAt = document.getElementById("updated-at");
  const sourceLink = document.getElementById("source-link");
  const { generated_at, sources } = state.data;

  const dt = generated_at ? new Date(generated_at) : null;
  updatedAt.textContent = (dt && !isNaN(dt.getTime()))
    ? "Atualizado em " + dt.toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" }) +
      (state.stale ? " · dados salvos" : "")
    : String(generated_at || "");

  const src = (sources || []).find(s => s && s.url);
  if (src) {
    sourceLink.href = src.url;
    sourceLink.hidden = false;
  } else {
    sourceLink.hidden = true;
    sourceLink.removeAttribute("href");
  }
}

function clearChrome() {
  const sourceLink = document.getElementById("source-link");
  if (sourceLink) {
    sourceLink.hidden = true;
    sourceLink.removeAttribute("href");
  }
  const updatedAt = document.getElementById("updated-at");
  if (updatedAt) updatedAt.textContent = "";
  const banner = document.getElementById("status-banner");
  if (banner) banner.hidden = true;
  const label = document.getElementById("week-label");
  if (label) label.hidden = true;
  const prev = document.getElementById("week-prev");
  const next = document.getElementById("week-next");
  if (prev) prev.hidden = true;
  if (next) next.hidden = true;
  document.querySelectorAll("#meal-tabs button").forEach(btn => { btn.hidden = true; });
  document.getElementById("diet-switch").hidden = true;
}

function render(opts) {
  const options = opts || {};
  if (!state.data || !state.days.length) {
    clearChrome();
    document.getElementById("day-tabs").innerHTML = "";
    const card = document.getElementById("menu-card");
    card.innerHTML = "";
    const p = el("p", "notice");
    p.append(el("strong", "", "Não foi possível carregar o cardápio."),
      document.createTextNode(" Verifique a conexão e recarregue a página."));
    card.appendChild(p);
    return;
  }
  renderStatus();
  renderDayTabs();
  renderWeekChrome();
  renderMealSwitch();
  renderDietSwitch();
  renderMenu();
  renderFooter();
  if (options.focusDay) {
    const active = document.querySelector(`#tab-day-${state.selectedDay}`);
    if (active) active.focus();
  }
}

/* ---------------------------------------------------------------------------
   Seleção de dia / semana / refeição
--------------------------------------------------------------------------- */
function selectDay(iso, opts) {
  const options = opts || {};
  state.selectedDay = iso;
  const week = state.weeks.findIndex(w => w.days.includes(iso));
  if (week >= 0) state.weekIndex = week;
  if (iso !== todayISO()) state.mealPinned = true;
  render({ focusDay: Boolean(options.focusDay) });
}

function stepWeek(delta) {
  const next = state.weekIndex + delta;
  if (next < 0 || next >= state.weeks.length) return;
  state.weekIndex = next;
  const days = state.weeks[next].days;
  // mantém o mesmo dia da semana quando existe; senão, o primeiro dia da semana
  const wanted = parseISO(state.selectedDay).getDay();
  const same = days.find(iso => parseISO(iso).getDay() === wanted);
  selectDay(same || days[0]);
}

function selectMeal(meal, opts) {
  const options = opts || {};
  if (!state.data) return;
  const order = mealOrder(state.data);
  const day = (state.data.days || {})[state.selectedDay] || {};
  const available = order.filter(m => Array.isArray(day[m]) && day[m].length);
  if (available.length && !available.includes(meal)) return;
  state.selectedMeal = meal;
  state.mealPinned = true;
  renderMealSwitch();
  renderMenu();
  if (options.focus) {
    const btn = document.getElementById(`tab-${meal}`);
    if (btn) btn.focus();
  }
}

function selectDiet(diet) {
  if (state.diet === diet) return;
  state.diet = diet;
  storeSet(DIET_KEY, diet);
  renderDietSwitch();
  renderMenu();
}

/* ---------------------------------------------------------------------------
   Navegação por teclado nas abas (padrão WAI-ARIA: setas + Home/End)
--------------------------------------------------------------------------- */
function wireTablist(container, activate) {
  container.addEventListener("keydown", event => {
    const tabs = Array.from(container.querySelectorAll('[role="tab"]')).filter(t => !t.hidden);
    const index = tabs.indexOf(document.activeElement);
    if (index < 0) return;
    let target = null;
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        target = tabs[(index + 1) % tabs.length];
        break;
      case "ArrowLeft":
      case "ArrowUp":
        target = tabs[(index - 1 + tabs.length) % tabs.length];
        break;
      case "Home":
        target = tabs[0];
        break;
      case "End":
        target = tabs[tabs.length - 1];
        break;
      default:
        return;
    }
    if (!target) return;
    event.preventDefault();
    activate(target);
  });
}

/* ---------------------------------------------------------------------------
   Troca de campus
--------------------------------------------------------------------------- */
function applyData(json, stale) {
  state.data = json;
  state.stale = stale;
  state.days = daysWithContent(json);
  state.hasDiet = hasDietChoice(json);
  state.weeks = [];
  const byWeek = new Map();
  for (const iso of state.days) {
    const start = weekStartISO(iso);
    if (!byWeek.has(start)) byWeek.set(start, []);
    byWeek.get(start).push(iso);
  }
  state.weeks = Array.from(byWeek.entries())
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .map(([start, days]) => ({ start, days }));

  const today = todayISO();
  const current = state.days.includes(today)
    ? today
    : (state.days.find(iso => iso >= today) || state.days[state.days.length - 1]);
  state.selectedDay = current || null;
  state.weekIndex = Math.max(0, state.weeks.findIndex(w => w.days.includes(state.selectedDay)));

  const order = mealOrder(json);
  if (!order.includes(state.selectedMeal)) {
    state.selectedMeal = order.includes("almoco") ? "almoco" : order[0];
  }
  // no dia de hoje a refeição segue o relógio de Brasília; em outro dia, fica
  // a que o usuário escolheu (ou o almoço, padrão dos campi tabelados)
  if (state.selectedDay === today && !state.mealPinned) state.selectedMeal = mealForNow();
}

function setHeading(campusId) {
  const meta = CAMPUS.find(c => c.id === campusId);
  document.title = `Cardápio RU · ${meta ? meta.name : "UnB"}`;
  const select = document.getElementById("campus-select");
  if (select) select.value = campusId;
}

async function selectCampus(id, opts) {
  const options = opts || {};
  state.campus = id;
  state.mealPinned = false;
  storeSet("cardapio-campus", id);
  if (options.updateHash !== false) {
    history.replaceState(null, "", `#${id}`);
  }
  setHeading(id);

  const cached = memory.get(id);
  if (cached) {
    // visita repetida: pinta na hora e revalida em segundo plano
    applyData(cached.json, cached.stale);
    render();
    revalidate(id);
    return;
  }

  applyData(null, false);

  // estado de carregamento sem passar pelo "não foi possível carregar"
  clearChrome();
  document.getElementById("day-tabs").innerHTML = "";
  const card = document.getElementById("menu-card");
  card.innerHTML = "";
  card.appendChild(el("p", "notice", "Carregando…"));

  const { json, stale } = await loadCampus(id);
  if (state.campus !== id) return; // o usuário trocou de campus enquanto carregava
  memory.set(id, { json, stale });
  applyData(json, stale);
  render();
}

async function revalidate(id) {
  if (state.campus !== id) return;
  try {
    const json = await fetchCampus(id);
    const previous = memory.get(id);
    const prevJson = previous && previous.json;
    const changed = !prevJson || prevJson.generated_at !== json.generated_at;
    memory.set(id, { json, stale: false });
    storeSet(`cardapio-cache-${id}`, JSON.stringify(json));
    if (changed) {
      // preserva a escolha do usuário (dia e refeição) depois de atualizar
      const keepDay = state.selectedDay;
      const keepMeal = state.selectedMeal;
      applyData(json, false);
      if (state.days.includes(keepDay)) {
        state.selectedDay = keepDay;
        const idx = state.weeks.findIndex(w => w.days.includes(keepDay));
        if (idx >= 0) state.weekIndex = idx;
      }
      const order = mealOrder(json);
      if (order.includes(keepMeal)) state.selectedMeal = keepMeal;
      render();
    }
  } catch (e) {
    console.warn("Revalidação falhou:", e);
  }
}

/* ---------------------------------------------------------------------------
   Bootstrap
--------------------------------------------------------------------------- */
function setupCampusSelect() {
  const select = document.getElementById("campus-select");
  // o listener precisa existir ANTES do primeiro carregamento: uma troca
  // durante o fetch inicial não pode se perder
  select.addEventListener("change", () => selectCampus(select.value));
}

function setupMealSwitch() {
  const container = document.getElementById("meal-tabs");
  container.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("click", () => selectMeal(btn.dataset.meal));
  });
  wireTablist(container, tab => selectMeal(tab.dataset.meal, { focus: true }));
}

function setupDayTabs() {
  const container = document.getElementById("day-tabs");
  wireTablist(container, tab => {
    if (tab.dataset.day) selectDay(tab.dataset.day, { focusDay: true });
  });
}

function setupDietSwitch() {
  document.querySelectorAll(".diet-chip").forEach(chip => {
    chip.addEventListener("click", () => selectDiet(chip.dataset.diet));
  });
}

function setupWeekSteps() {
  document.getElementById("week-prev").addEventListener("click", () => stepWeek(-1));
  document.getElementById("week-next").addEventListener("click", () => stepWeek(1));
}

function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  // só faz sentido onde o site é servido com contexto seguro (https/localhost)
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(err => {
      console.warn("Service worker não registrado:", err);
    });
  });
}

function setupConnectivity() {
  window.addEventListener("offline", () => {
    state.stale = Boolean(state.data);
    renderStatus();
  });
  window.addEventListener("online", () => {
    if (state.campus) revalidate(state.campus);
  });
}

(function init() {
  const savedDiet = storeGet(DIET_KEY);
  if (savedDiet && ["padrao", "ovolacto", "estrito"].includes(savedDiet)) {
    state.diet = savedDiet;
  }

  setupMealSwitch();
  setupDayTabs();
  setupDietSwitch();
  setupWeekSteps();
  setupCampusSelect();
  setupConnectivity();
  registerServiceWorker();

  const fromHash = location.hash.replace("#", "");
  const saved = storeGet("cardapio-campus");
  const campus = (CAMPUS.find(c => c.id === fromHash) || {}).id
    || (CAMPUS.find(c => c.id === saved) || {}).id
    || DEFAULT_CAMPUS;

  selectCampus(campus, { updateHash: false });

  // troca de campus ao navegar por hash (ex.: colar um link #fcte depois do load)
  window.addEventListener("hashchange", () => {
    const id = (CAMPUS.find(c => c.id === location.hash.replace("#", "")) || {}).id;
    if (id && id !== state.campus) selectCampus(id, { updateHash: false });
  });
})();
