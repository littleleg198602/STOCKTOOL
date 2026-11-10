"use strict";

/**
 * StockTool Data Manager BETA
 * Browser-only OHLCV importer & viewer. No outbound requests, no remote database.
 * Times in CSV/TSV are interpreted as UTC and never silently converted.
 */
(() => {
  const $ = id => document.getElementById(id);
  const PERIODS = { M1: 1, M5: 5, M15: 15, M30: 30, H1: 60, H4: 240, D1: 1440, W1: 10080 };
  const DATABASE = "stocktool-data-manager-v1";
  const STORE = "datasets";
  const MAX_FILE_BYTES = 20 * 1024 * 1024;
  const MAX_BARS = 100000;
  const TABLE_SIZE = 20;
  const DAY = 86400000;
  const numberFmt = new Intl.NumberFormat("cs-CZ");
  const memory = new Map();
  let db = null;
  let memoryOnly = false;
  let datasets = [];
  let selectedId = "";
  let fileToImport = null;
  let displayed = [];
  let chartBars = [];
  let page = 0;
  let toastTimer;

  const fmtPrice = value => {
    if (!Number.isFinite(value)) return "—";
    const decimalPlaces = Math.abs(value) >= 1000 ? 2 : Math.abs(value) >= 1 ? 5 : 7;
    return new Intl.NumberFormat("cs-CZ", { maximumFractionDigits: decimalPlaces }).format(value);
  };
  const fmtTime = time => new Date(time).toISOString().slice(0, 16).replace("T", " ") + " UTC";

  function message(text, isError = false) {
    const toast = $("toast");
    toast.textContent = text;
    toast.classList.toggle("error", isError);
    toast.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("visible"), 4800);
  }

  function openDatabase() {
    return new Promise((resolve, reject) => {
      if (!("indexedDB" in window)) return reject(new Error("IndexedDB není dostupné."));
      const req = indexedDB.open(DATABASE, 1);
      req.onupgradeneeded = () => {
        if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE, { keyPath: "id" });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error || new Error("Databáze není přístupná."));
      req.onblocked = () => reject(new Error("Databáze je zablokovaná jiným oknem."));
    });
  }

  function transaction(method, dataOrId) {
    if (memoryOnly) {
      if (method === "getAll") return Promise.resolve([...memory.values()]);
      if (method === "put") { memory.set(dataOrId.id, dataOrId); return Promise.resolve(); }
      if (method === "delete") { memory.delete(dataOrId); return Promise.resolve(); }
    }
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, method === "getAll" ? "readonly" : "readwrite");
      const store = tx.objectStore(STORE);
      let result;
      const req = method === "getAll" ? store.getAll() : method === "put" ? store.put(dataOrId) : store.delete(dataOrId);
      req.onsuccess = () => { result = req.result; };
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(tx.error || new Error("Operace s databází selhala."));
      tx.onabort = () => reject(tx.error || new Error("Operace byla přerušena."));
    });
  }

  async function refreshDatasets(preferredId = selectedId) {
    datasets = (await transaction("getAll")).sort((a, b) => b.updatedAt - a.updatedAt);
    const selected = datasets.find(d => d.id === preferredId);
    selectedId = selected ? selected.id : (datasets[0] ? datasets[0].id : "");
    renderDatasetList();
    setActive();
  }

  function renderDatasetList() {
    const root = $("datasets-list");
    root.replaceChildren();
    $("set-count").textContent = String(datasets.length);
    if (!datasets.length) {
      const empty = document.createElement("div");
      empty.className = "empty-small";
      empty.textContent = "Zatím žádná data.";
      root.append(empty);
      return;
    }
    for (const data of datasets) {
      const button = document.createElement("button");
      button.className = "dataset-item" + (data.id === selectedId ? " is-active" : "");
      button.type = "button";
      button.setAttribute("aria-pressed", String(data.id === selectedId));
      const box = document.createElement("span");
      const name = document.createElement("strong");
      const small = document.createElement("small");
      const tf = document.createElement("span");
      name.textContent = data.symbol;
      small.textContent = numberFmt.format(data.bars.length) + " svíček · " + data.source;
      tf.textContent = data.timeframe;
      box.append(name, small);
      button.append(box, tf);
      button.addEventListener("click", () => {
        selectedId = data.id;
        page = 0;
        renderDatasetList();
        setActive();
      });
      root.append(button);
    }
  }

  function periodBucket(time, tf) {
    const minutes = PERIODS[tf];
    if (tf === "W1") {
      const mondayAnchor = 4 * DAY;
      const week = 7 * DAY;
      return Math.floor((time - mondayAnchor) / week) * week + mondayAnchor;
    }
    return Math.floor(time / (minutes * 60000)) * minutes * 60000;
  }

  function aggregate(bars, tf) {
    let prevBucket = -1;
    const out = [];
    for (const bar of bars) {
      const bucket = periodBucket(bar.t, tf);
      if (bucket !== prevBucket) {
        out.push({ t: bucket, o: bar.o, h: bar.h, l: bar.l, c: bar.c, v: bar.v });
        prevBucket = bucket;
      } else {
        const last = out[out.length - 1];
        last.h = Math.max(last.h, bar.h);
        last.l = Math.min(last.l, bar.l);
        last.c = bar.c;
        last.v += bar.v;
      }
    }
    return out;
  }

  function setActive() {
    const data = datasets.find(d => d.id === selectedId);
    page = 0;
    const tfSelect = $("view-timeframe");
    tfSelect.replaceChildren();
    const opts = Object.entries(PERIODS).filter(([, v]) => data && v >= PERIODS[data.timeframe]);
    for (const [tf] of opts) {
      const option = document.createElement("option");
      option.value = tf;
      option.textContent = tf;
      tfSelect.append(option);
    }
    tfSelect.disabled = !data;
    $("range").disabled = !data;
    $("export-button").disabled = !data;
    $("delete-button").disabled = !data;
    renderActive();
  }

  function renderActive() {
    const data = datasets.find(d => d.id === selectedId);
    if (!data) {
      $("dataset-heading").textContent = "Zatím žádná data";
      $("dataset-meta").textContent = "Nahraj CSV z MT5 nebo zkus ukázkový dataset.";
      $("dataset-source").textContent = "NEPŘIPOJENO";
      for (const id of ["stat-count", "stat-close", "stat-high", "stat-low"]) $(id).textContent = "—";
      $("stat-timeframe").textContent = "Bez dat";
      $("stat-date").textContent = "Bez dat";
      $("chart-empty").hidden = false;
      $("chart-caption").textContent = "Časy se zobrazují v UTC bez převodu časového pásma.";
      $("table-meta").textContent = "Čeká na import";
      $("hover-details").textContent = "Po najetí myší na svíčku zde uvidíš OHLCV.";
      displayed = [];
      chartBars = [];
      renderTable();
      drawChart();
      return;
    }
    const last = data.bars[data.bars.length - 1];
    $("dataset-heading").textContent = data.symbol + " · " + data.timeframe;
    $("dataset-meta").textContent = "Od " + fmtTime(data.bars[0].t) + " do " + fmtTime(last.t);
    $("dataset-source").textContent = data.source === "DEMO" ? "UMĚLÁ DATA" : "IMPORT CSV";
    $("stat-count").textContent = numberFmt.format(data.bars.length);
    $("stat-timeframe").textContent = "Původní interval " + data.timeframe;
    $("stat-close").textContent = fmtPrice(last.c);
    $("stat-date").textContent = fmtTime(last.t);
    // For the minimum, calculate in a loop to avoid limits on spread arguments.
    let min = Infinity, max = -Infinity;
    for (const bar of data.bars) { if (bar.l < min) min = bar.l; if (bar.h > max) max = bar.h; }
    $("stat-high").textContent = fmtPrice(max);
    $("stat-low").textContent = fmtPrice(min);
    const viewTF = $("view-timeframe").value || data.timeframe;
    displayed = viewTF === data.timeframe ? data.bars : aggregate(data.bars, viewTF);
    $("chart-caption").textContent = numberFmt.format(displayed.length) + " svíček v intervalu " + viewTF + " · Čas UTC";
    $("chart-empty").hidden = true;
    $("table-meta").textContent = "Zobrazený interval: " + viewTF + " · Nejnovější první";
    chartBars = displayed.slice(-Number($("range").value));
    renderTable();
    drawChart();
  }

  function drawChart() {
    const canvas = $("chart");
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const width = Math.max(300, canvas.clientWidth || 680);
    const height = canvas.clientHeight || 328;
    const dpr = Math.min(2.5, window.devicePixelRatio || 1);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    if (!chartBars.length) return;
    const left = 10, right = 78, top = 18;
    const bottom = height - 63, plotWidth = width - left - right;
    const plotHeight = bottom - top;
    let low = Infinity, high = -Infinity, maxVolume = 1;
    for (const bar of chartBars) {
      low = Math.min(low, bar.l);
      high = Math.max(high, bar.h);
      maxVolume = Math.max(maxVolume, bar.v);
    }
    const padding = Math.max((high - low) * .08, Math.abs(high) * .0001, .000001);
    low -= padding; high += padding;
    const y = price => top + ((high - price) / (high - low)) * plotHeight;
    ctx.font = "10px ui-monospace, Consolas, monospace";
    ctx.textBaseline = "middle";
    for (let i = 0; i < 5; i++) {
      const yy = top + (plotHeight * i / 4);
      ctx.strokeStyle = "rgba(86,120,142,.22)";
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(left + plotWidth, yy); ctx.stroke();
      ctx.fillStyle = "#8aa9b7";
      ctx.fillText(fmtPrice(high - (high - low) * i / 4), width - right + 10, yy);
    }
    const step = plotWidth / chartBars.length;
    const candleWidth = Math.max(1, Math.min(10, step * .65));
    chartBars.forEach((bar, index) => {
      const cx = left + index * step + step / 2;
      const rising = bar.c >= bar.o;
      const color = rising ? "#48e5bb" : "#f18e8e";
      const bodyTop = y(Math.max(bar.o, bar.c));
      const bodyBottom = y(Math.min(bar.o, bar.c));
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = Math.max(1, step >= 4 ? 1.4 : 1);
      ctx.beginPath(); ctx.moveTo(cx, y(bar.h)); ctx.lineTo(cx, y(bar.l)); ctx.stroke();
      ctx.fillRect(cx - candleWidth / 2, bodyTop, candleWidth, Math.max(1, bodyBottom - bodyTop));
      if (bar.v > 0) {
        ctx.globalAlpha = .4;
        const volumeH = bar.v / maxVolume * 33;
        ctx.fillRect(cx - candleWidth / 2, height - 43 - volumeH, candleWidth, volumeH);
        ctx.globalAlpha = 1;
      }
    });
    const ticks = Math.min(6, chartBars.length);
    ctx.fillStyle = "#7996a8";
    ctx.font = "10px ui-monospace, monospace";
    for (let i = 0; i < ticks; i++) {
      const index = ticks <= 1 ? 0 : Math.floor(i * (chartBars.length - 1) / (ticks - 1));
      const bar = chartBars[index];
      const label = new Date(bar.t).toISOString().slice(5, 10);
      const xx = left + index * step;
      ctx.fillText(label, Math.max(1, Math.min(width - 109, xx)), height - 9);
    }
  }

  function renderTable() {
    const root = $("data-rows");
    root.replaceChildren();
    if (!displayed.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.className = "table-empty";
      td.colSpan = 6;
      td.textContent = "Zatím žádné svíčky.";
      tr.append(td); root.append(tr);
      $("page-text").textContent = "—";
      $("prev-page").disabled = true;
      $("next-page").disabled = true;
      return;
    }
    const reversed = displayed.slice().reverse();
    const first = page * TABLE_SIZE;
    for (const bar of reversed.slice(first, first + TABLE_SIZE)) {
      const tr = document.createElement("tr");
      const values = [fmtTime(bar.t), fmtPrice(bar.o), fmtPrice(bar.h), fmtPrice(bar.l), fmtPrice(bar.c), numberFmt.format(bar.v)];
      values.forEach((val, i) => {
        const td = document.createElement("td");
        td.textContent = val;
        if (i === 4) td.className = bar.c >= bar.o ? "positive" : "negative";
        tr.append(td);
      });
      root.append(tr);
    }
    const totalPages = Math.ceil(displayed.length / TABLE_SIZE);
    $("page-text").textContent = (page + 1) + " / " + totalPages + " · " + numberFmt.format(displayed.length) + " svíček";
    $("prev-page").disabled = page === 0;
    $("next-page").disabled = page >= totalPages - 1;
  }

  function splitDelimitedLine(line, separator) {
    const fields = [];
    let field = "", quoted = false;
    for (let i = 0; i < line.length; i++) {
      const char = line[i];
      if (char === '"') {
        if (quoted && line[i + 1] === '"') { field += '"'; i++; }
        else quoted = !quoted;
      } else if (char === separator && !quoted) { fields.push(field.trim()); field = ""; }
      else field += char;
    }
    fields.push(field.trim());
    return fields;
  }

  function parseUTCDate(dateText, timeText = "") {
    const date = String(dateText || "").trim();
    const time = String(timeText || "").trim();
    if (/^\d{10,13}$/.test(date) && !time) {
      const n = Number(date);
      return date.length === 13 ? n : n * 1000;
    }
    const combined = (date + " " + time).trim().replace("T", " ");
    const match = combined.match(/^(\d{4})[.\/-](\d{1,2})[.\/-](\d{1,2})(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?(?:\s*Z)?$/);
    const european = !match && combined.match(/^(\d{1,2})[.\/](\d{1,2})[.\/](\d{4})(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?$/);
    const v = match ? [match[1], match[2], match[3], match[4], match[5], match[6]] : european ? [european[3], european[2], european[1], european[4], european[5], european[6]] : null;
    if (!v) return NaN;
    const [year, month, day, hour, minute, second] = v.map(x => Number(x || 0));
    const result = Date.UTC(year, month - 1, day, hour, minute, second);
    const parsed = new Date(result);
    if (parsed.getUTCFullYear() !== year || parsed.getUTCMonth() + 1 !== month || parsed.getUTCDate() !== day || parsed.getUTCHours() !== hour || parsed.getUTCMinutes() !== minute) return NaN;
    return result;
  }

  function parseNumber(value) {
    const cleaned = String(value ?? "").trim().replace(/\s/g, "").replace(",", ".");
    if (!cleaned) return NaN;
    const n = Number(cleaned);
    return Number.isFinite(n) ? n : NaN;
  }

  function parseCsv(text) {
    const raw = text.replace(/^\uFEFF/, "").split(/\r\n|\r|\n/).filter(s => s.trim());
    if (raw.length < 2) throw new Error("Soubor neobsahuje hlavičku a datové řádky.");
    const headerLine = raw[0];
    const separator = ["\t", ";", ","].sort((a, b) => headerLine.split(b).length - headerLine.split(a).length)[0];
    const normalize = x => x.trim().replace(/^[<"']+|[>"']+$/g, "").replace(/[\s_-]/g, "").toLowerCase();
    const headers = splitDelimitedLine(headerLine, separator).map(normalize);
    const locate = (...names) => headers.findIndex(x => names.includes(x));
    const col = {
      date: locate("date", "datum"),
      time: locate("time"),
      dateTime: locate("datetime", "timestamp", "dateandtime"),
      open: locate("open", "o"),
      high: locate("high", "h"),
      low: locate("low", "l"),
      close: locate("close", "c"),
      volume: locate("tickvol", "tickvolume", "tickvolumes", "volume", "vol", "realvolume")
    };
    if ([col.open, col.high, col.low, col.close].some(x => x < 0) || (col.date < 0 && col.dateTime < 0 && col.time < 0)) {
      throw new Error("Chybí hlavička DATE/TIME (nebo DATETIME) a OPEN, HIGH, LOW, CLOSE.");
    }
    if (raw.length - 1 > MAX_BARS) throw new Error("Soubor obsahuje více než 100 000 řádků. Rozděl ho na menší části.");
    const map = new Map();
    let skipped = 0;
    for (let i = 1; i < raw.length; i++) {
      const cells = splitDelimitedLine(raw[i], separator);
      const timestamp = col.dateTime >= 0 ? parseUTCDate(cells[col.dateTime]) :
        col.date >= 0 ? parseUTCDate(cells[col.date], col.time >= 0 ? cells[col.time] : "") : parseUTCDate(cells[col.time]);
      const o = parseNumber(cells[col.open]), h = parseNumber(cells[col.high]);
      const l = parseNumber(cells[col.low]), c = parseNumber(cells[col.close]);
      const volumeValue = col.volume >= 0 ? parseNumber(cells[col.volume]) : 0;
      const v = Number.isFinite(volumeValue) && volumeValue >= 0 ? volumeValue : 0;
      if (!Number.isFinite(timestamp) || ![o, h, l, c].every(Number.isFinite) || h < Math.max(o, c, l) || l > Math.min(o, c, h)) { skipped++; continue; }
      map.set(timestamp, { t: timestamp, o, h, l, c, v });
    }
    const bars = [...map.values()].sort((a, b) => a.t - b.t);
    if (!bars.length) throw new Error("Nenašli jsme žádné platné OHLC svíčky. Zkontroluj formát souboru.");
    return { bars, skipped };
  }

  function selectFile(file) {
    if (!file) return;
    if (file.size > MAX_FILE_BYTES) {
      fileToImport = null;
      $("file-name").textContent = "Soubor je větší než 20 MB.";
      $("import-button").disabled = true;
      message("Soubor je příliš velký (maximum je 20 MB).", true);
      return;
    }
    fileToImport = file;
    $("file-name").textContent = file.name;
    $("import-button").disabled = false;
  }

  function canonicalSymbol(value) {
    const symbol = value.trim().toUpperCase();
    if (!/^[A-Z0-9._:-]{1,30}$/.test(symbol)) throw new Error("Symbol může obsahovat jen písmena, čísla a znaky . _ : -.");
    return symbol;
  }

  async function importFile() {
    if (!fileToImport) return;
    let symbol;
    try { symbol = canonicalSymbol($("symbol").value); }
    catch (error) { message(error.message, true); return; }
    const tf = $("source-timeframe").value;
    const button = $("import-button");
    button.disabled = true;
    button.textContent = "Importuji…";
    try {
      const { bars, skipped } = parseCsv(await fileToImport.text());
      const id = symbol + "|" + tf;
      const old = datasets.find(d => d.id === id);
      const merged = new Map((old?.bars || []).map(bar => [bar.t, bar]));
      for (const bar of bars) merged.set(bar.t, bar);
      const combined = [...merged.values()].sort((a, b) => a.t - b.t);
      if (combined.length > MAX_BARS) throw new Error("Dataset přesahuje 100 000 svíček. Použij kratší období.");
      const record = {
        id, symbol, timeframe: tf, bars: combined, source: "CSV",
        updatedAt: Date.now(), createdAt: old?.createdAt || Date.now()
      };
      await transaction("put", record);
      await refreshDatasets(id);
      message("Importováno: " + numberFmt.format(bars.length) + " svíček" + (skipped ? " · přeskočeno " + skipped : "") + ".");
    } catch (error) {
      console.error("StockTool import error:", error);
      message("Import selhal: " + (error.message || "Neznámá chyba."), true);
    } finally {
      button.disabled = !fileToImport;
      button.replaceChildren(document.createTextNode("Importovat svíčky "), Object.assign(document.createElement("span"), { textContent: "↗" }));
    }
  }

  async function demoData() {
    const end = Math.floor(Date.now() / 3600000) * 3600000;
    const bars = [];
    let price = 115;
    for (let i = 239; i >= 0; i--) {
      const sequence = 239 - i;
      const change = Math.sin(sequence * .31) * 1.0 + Math.cos(sequence * .12) * .9 + Math.sin(sequence * 1.7) * .4;
      const open = price;
      const close = Math.max(.5, open + change);
      const high = Math.max(open, close) + .3 + Math.abs(Math.sin(sequence)) * .7;
      const low = Math.min(open, close) - .3 - Math.abs(Math.cos(sequence)) * .7;
      bars.push({ t: end - i * 3600000, o: open, h: high, l: low, c: close, v: 50 + (sequence * 73) % 140 });
      price = close;
    }
    const id = "DEMO|H1";
    try {
      await transaction("put", { id, symbol: "DEMO", timeframe: "H1", bars, source: "DEMO", updatedAt: Date.now(), createdAt: Date.now() });
      await refreshDatasets(id);
      message("Načtena umělá ukázková data (nejde o skutečné tržní ceny).");
    } catch (error) { message("Ukázková data se nepodařilo uložit: " + error.message, true); }
  }

  function exportCsv() {
    const data = datasets.find(d => d.id === selectedId);
    if (!data) return;
    const rows = ["<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<TICKVOL>"];
    for (const bar of data.bars) {
      const iso = new Date(bar.t).toISOString();
      rows.push([iso.slice(0, 10).replaceAll("-", "."), iso.slice(11, 19), bar.o, bar.h, bar.l, bar.c, bar.v].join(","));
    }
    const blob = new Blob([rows.join("\r\n") + "\r\n"], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "stocktool_" + data.symbol.replace(/[^A-Z0-9._-]/gi, "_") + "_" + data.timeframe + ".csv";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 3000);
    message("Exportováno " + numberFmt.format(data.bars.length) + " původních svíček do CSV.");
  }

  async function deleteSelected() {
    const data = datasets.find(d => d.id === selectedId);
    if (!data) return;
    if (!window.confirm("Smazat dataset " + data.symbol + " (" + data.timeframe + ") z tohoto prohlížeče?")) return;
    try {
      await transaction("delete", data.id);
      selectedId = "";
      await refreshDatasets("");
      message("Dataset byl odstraněn.");
    } catch (error) { message("Smazání se nezdařilo: " + error.message, true); }
  }

  async function initialize() {
    $("year").textContent = String(new Date().getFullYear());
    try { db = await openDatabase(); }
    catch (error) {
      memoryOnly = true;
      const label = document.querySelector(".local-notice small");
      label.textContent = "Dočasná paměť – po zavření zmizí";
      message("Prohlížeč nepovolil místní databázi. Data vydrží jen do obnovení stránky.", true);
    }
    try { await refreshDatasets(); } catch (error) { message("Načtení databáze selhalo: " + error.message, true); }

    $("dropzone").addEventListener("click", () => $("file-input").click());
    $("dropzone").addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("file-input").click(); }
    });
    $("file-input").addEventListener("change", e => selectFile(e.target.files[0]));
    for (const type of ["dragenter", "dragover"]) {
      $("dropzone").addEventListener(type, e => { e.preventDefault(); $("dropzone").classList.add("dragover"); });
    }
    for (const type of ["dragleave", "drop"]) {
      $("dropzone").addEventListener(type, e => { e.preventDefault(); $("dropzone").classList.remove("dragover"); });
    }
    $("dropzone").addEventListener("drop", e => selectFile(e.dataTransfer.files[0]));
    $("import-button").addEventListener("click", importFile);
    $("demo-button").addEventListener("click", demoData);
    $("view-timeframe").addEventListener("change", () => { page = 0; renderActive(); });
    $("range").addEventListener("change", drawForNewRange);
    $("export-button").addEventListener("click", exportCsv);
    $("delete-button").addEventListener("click", deleteSelected);
    $("prev-page").addEventListener("click", () => { page = Math.max(0, page - 1); renderTable(); });
    $("next-page").addEventListener("click", () => { page++; renderTable(); });

    $("chart").addEventListener("mousemove", e => {
      if (!chartBars.length) return;
      const bounds = $("chart").getBoundingClientRect();
      const x = e.clientX - bounds.left;
      const step = (bounds.width - 88) / chartBars.length;
      const index = Math.floor((x - 10) / step);
      if (index < 0 || index >= chartBars.length) return;
      const bar = chartBars[index];
      $("hover-details").textContent = fmtTime(bar.t) + " · O " + fmtPrice(bar.o) + " · H " + fmtPrice(bar.h) + " · L " + fmtPrice(bar.l) + " · C " + fmtPrice(bar.c) + " · V " + numberFmt.format(bar.v);
    });
    $("chart").addEventListener("mouseleave", () => {
      $("hover-details").textContent = "Po najetí myší na svíčku zde uvidíš OHLCV.";
    });
    if ("ResizeObserver" in window) new ResizeObserver(drawChart).observe($("chart-wrapper"));
    else window.addEventListener("resize", drawChart);
  }

  function drawForNewRange() {
    chartBars = displayed.slice(-Number($("range").value));
    drawChart();
  }
  document.addEventListener("DOMContentLoaded", initialize);
})();
