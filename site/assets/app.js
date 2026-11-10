"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const chips = [...document.querySelectorAll(".filter-chip")];
  const cards = [...document.querySelectorAll(".app-card")];
  const search = document.querySelector("#app-search");
  const noResults = document.querySelector("#no-results");
  let activeFilter = "all";

  const normalize = value => value.toLocaleLowerCase("cs-CZ").normalize("NFD").replace(/[\u0300-\u036f]/g, "");

  function updateCatalog() {
    const query = normalize(search.value.trim());
    let shown = 0;
    for (const card of cards) {
      const categoryMatch = activeFilter === "all" || card.dataset.category.split(" ").includes(activeFilter);
      const queryMatch = !query || normalize(card.dataset.search + " " + card.querySelector("h3").textContent + " " + card.querySelector("p").textContent).includes(query);
      card.hidden = !(categoryMatch && queryMatch);
      if (!card.hidden) shown++;
    }
    noResults.hidden = shown > 0;
  }

  for (const chip of chips) {
    chip.addEventListener("click", () => {
      activeFilter = chip.dataset.filter;
      for (const other of chips) {
        const selected = other === chip;
        other.classList.toggle("active", selected);
        other.setAttribute("aria-pressed", String(selected));
      }
      updateCatalog();
    });
  }

  search.addEventListener("input", updateCatalog);
  document.querySelector("#reset-filters").addEventListener("click", () => {
    search.value = "";
    chips[0].click();
    search.focus();
  });

  const menuButton = document.querySelector(".menu-toggle");
  const menu = document.querySelector("#main-nav");
  function closeMenu() {
    menu.classList.remove("is-open");
    menuButton.setAttribute("aria-expanded", "false");
    menuButton.setAttribute("aria-label", "Otevřít navigaci");
  }
  menuButton.addEventListener("click", () => {
    const open = menu.classList.toggle("is-open");
    menuButton.setAttribute("aria-expanded", String(open));
    menuButton.setAttribute("aria-label", open ? "Zavřít navigaci" : "Otevřít navigaci");
  });
  for (const link of menu.querySelectorAll("a")) link.addEventListener("click", closeMenu);
  window.addEventListener("keydown", (event) => { if (event.key === "Escape") closeMenu(); });

  const details = {
    johny: { title: "JOHNY", icon: "J", description: "Samostatná webová aplikace pro vyhodnocování fundamentů, finančních výkazů, valuací, cash flow a dividendových kandidátů. Cílem je dohledatelné vyhodnocení akcií a jejich rizik." },
    buy: { title: "BUY Scanner", icon: "↗", description: "Samostatný program pro hledání potenciálních nákupních příležitostí. Počítáme s kombinací cenových a fundamentálních filtrů, signálů paniky a kontextu toku kapitálu." },
    short: { title: "SHORT Scanner", icon: "↘", description: "Oddělený analytický nástroj pro hledání rizikových akcií a situací vhodných ke zkoumání poklesu ceny. Bude mít vlastní pravidla nezávislá na BUY Scanneru." },
    flow: { title: "Order Flow", icon: "∿", description: "Výzkumná aplikace pro sledování tržního chování, objemů, změn sentimentu a možných nucených výprodejů. Datové zdroje a možnosti automatizace teprve ověříme." },
    backtest: { title: "Backtesting", icon: "▧", description: "Testování pravidel na historických datech včetně parametrů strategie, seznamu obchodů, drawdownu a vyhodnocení výkonu. Výsledky budou přehledně vizualizované." },
    data: { title: "Data Manager", icon: "▤", description: "Datová vrstva pro naše aplikace: historické OHLCV svíčky, import z MT5, kontrola úplnosti dat, ukládání a sdílení mezi nástroji s ohledem na licence zdrojů." }
  };
  const dialog = document.querySelector("#app-dialog");
  for (const button of document.querySelectorAll("[data-app]")) {
    button.addEventListener("click", () => {
      const detail = details[button.dataset.app];
      if (!detail) return;
      document.querySelector("#dialog-title").textContent = detail.title;
      document.querySelector("#dialog-description").textContent = detail.description;
      document.querySelector("#dialog-symbol").textContent = detail.icon;
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    });
  }
  const dismiss = () => dialog.close ? dialog.close() : dialog.removeAttribute("open");
  document.querySelector("#close-dialog").addEventListener("click", dismiss);
  document.querySelector("#dialog-ok").addEventListener("click", dismiss);
  dialog.addEventListener("click", event => { if (event.target === dialog) dismiss(); });

  document.querySelector("#year").textContent = String(new Date().getFullYear());
});
