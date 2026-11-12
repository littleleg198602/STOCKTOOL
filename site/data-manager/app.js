"use strict";
// StockTool MT5 Data Manager – authenticated browser viewer for the MT5->PHP bridge.
// Credentials stay in memory only; no cookies, localStorage, sessionStorage or URL tokens.
(() => {
  const $ = id => document.getElementById(id);
  const API = "./api/";
  const PERIODS = { M1:1, M5:5, M15:15, M30:30, H1:60, H4:240, D1:1440, W1:10080 };
  const DAY = 86400000;
  const FMT = new Intl.NumberFormat("cs-CZ");
  const PAGE_SIZE = 20;
  let signedIn = false;
  let catalog = [];
  let selected = "";
  let rawBars = [];
  let aggregated = [];
  let chartBars = [];
  let page = 0;
  let previousSourceTimeframe = "";
  let busy = false;
  let toastTimer;

  function flash(text, error = false) {
    const el = $("toast");
    el.textContent = text;
    el.classList.toggle("error", error);
    el.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("visible"), 4800);
  }
  const num = n => FMT.format(n);
  const money = n => {
    if (!Number.isFinite(n)) return "—";
    return new Intl.NumberFormat("cs-CZ", {
      maximumFractionDigits: Math.abs(n) >= 1000 ? 2 : Math.abs(n) >= 1 ? 5 : 7
    }).format(n);
  };
  const stamp = t => t ? new Date(t).toISOString().slice(0, 16).replace("T", " ") + " UTC" : "—";

  async function getJson(uri) {
    const result = await fetch(API + uri, {
      headers: {"Accept":"application/json"}, cache:"no-store", credentials:"same-origin"
    });
    let data;
    try { data = await result.json(); } catch {
      throw new Error("API nevrátilo JSON. Ověř podporu PHP na FORPSI.");
    }
    if (!result.ok || !data.ok) {
      const details = {
        not_configured: "Na FORPSI chybí neveřejný config.php.",
        invalid_private_configuration: "Na FORPSI je neplatný soukromý config.php.",
        invalid_api_key: "Nesprávný přístupový klíč.",
        storage_unavailable: "Serverové úložiště není dostupné.",
        dataset_not_found: "Dataset již neexistuje."
      };
      throw new Error(details[data.error] || "Chyba serveru (" + result.status + ").");
    }
    return data;
  }

  function connectedState(active) {
    signedIn = active;
    $("login-controls").hidden = active;
    $("connect-button").disabled = active;
    $("disconnect-button").disabled = !active;
    $("refresh-button").disabled = !active;
    $("connection-label").textContent = active ? "Přihlášeno · zapamatované zařízení" : "Zatím nepřihlášeno";
  }

  function updateCoverage() {
    const symbols = new Set(catalog.map(item => item.symbol));
    const count = catalog.reduce((sum, item) => sum + Number(item.count || 0), 0);
    const lastUpdate = catalog.reduce((maximum, item) =>
      Math.max(maximum, Number(item.updated_at || 0)), 0);
    $("summary-symbols").textContent = num(symbols.size);
    $("summary-datasets").textContent = num(catalog.length);
    $("summary-bars").textContent = num(count);
    $("summary-updated").textContent = lastUpdate ? stamp(lastUpdate * 1000) : "—";
  }

  function renderCatalog() {
    const list = $("datasets-list");
    list.replaceChildren();
    const groups = new Map();
    for (const item of catalog) {
      const entries = groups.get(item.symbol) || [];
      entries.push(item);
      groups.set(item.symbol, entries);
    }
    $("set-count").textContent = String(groups.size);
    updateCoverage();
    if (!groups.size) {
      const empty = document.createElement("div");
      empty.className = "empty-small";
      empty.textContent = signedIn ? "MT5 zatím neposlal žádné svíčky." : "Přihlas se do StockToolu.";
      list.append(empty);
      return;
    }

    const term = $("dataset-filter").value.trim().toLocaleUpperCase("cs-CZ");
    const available = [...groups].filter(([symbol, entries]) =>
      (symbol + " " + entries.map(row => row.timeframe).join(" ")).toLocaleUpperCase("cs-CZ").includes(term));
    if (!available.length) {
      const empty = document.createElement("div");
      empty.className = "empty-small";
      empty.textContent = "Žádný ticker neodpovídá hledání.";
      list.append(empty);
    }

    available.slice(0, 120).forEach(([symbol, entries]) => {
      const selectedSymbol = selected.split("|")[0];
      const button = document.createElement("button");
      button.className = "dataset-item" + (selectedSymbol === symbol ? " is-active" : "");
      button.type = "button";
      button.setAttribute("aria-pressed", String(selectedSymbol === symbol));
      const box = document.createElement("span");
      const name = document.createElement("strong");
      name.textContent = symbol;
      const info = document.createElement("small");
      const sum = entries.reduce((total, row) => total + Number(row.count || 0), 0);
      info.textContent = num(sum) + " svíček · " + entries.length + " intervalů";
      const frames = document.createElement("span");
      frames.className = "dataset-frames";
      frames.textContent = entries.map(e => e.timeframe)
        .sort((a, b) => PERIODS[a] - PERIODS[b]).join(" · ");
      box.append(name, info);
      button.append(box, frames);
      button.addEventListener("click", () => {
        const currentTF = selected.split("|")[1];
        const chosen = entries.find(e => e.timeframe === currentTF)
          || entries.find(e => e.timeframe === "D1") || entries[0];
        selected = symbol + "|" + chosen.timeframe;
        page = 0;
        renderCatalog();
        loadSelected().catch(error => flash(error.message, true));
      });
      list.append(button);
    });

    if (available.length > 120) {
      const note = document.createElement("div");
      note.className = "empty-small";
      note.textContent = "Zobrazeno prvních 120 z " + num(available.length) +
        " akcií. Pro další ticker použij hledání.";
      list.append(note);
    }
  }

  async function connect() {
    if (location.protocol !== "https:") {
      return flash("Připojení vyžaduje zabezpečené HTTPS.", true);
    }
    const key = $("access-key").value.trim();
    if (key.length < 32) return flash("Při prvním přihlášení vlož existující API klíč.", true);
    $("connect-button").disabled = true;
    try {
      const response = await fetch(API + "login.php", {
        method: "POST", credentials: "same-origin", cache:"no-store",
        headers: { "X-StockTool-Key":key, "Accept":"application/json" }
      });
      const body = await response.json();
      if (!response.ok || !body.ok || !body.authenticated) {
        throw new Error(response.status === 401 ? "Nesprávný API klíč." : "Přihlášení selhalo (HTTP "+response.status+").");
      }
      $("access-key").value = "";
      connectedState(true);
      await refreshAll(true);
      flash("Přihlášeno. Data Manager a BUY Scanner si přístup zapamatují.");
    } catch (error) {
      flash("Přihlášení: " + error.message, true);
      if (!signedIn) connectedState(false);
    } finally {
      $("access-key").value = "";
      $("connect-button").disabled = signedIn;
    }
  }

  async function disconnect() {
    try {
      const response = await fetch(API + "logout.php", {
        method:"POST",credentials:"same-origin",cache:"no-store"
      });
      if (!response.ok) throw new Error("Odhlášení na serveru selhalo.");
      catalog = [];
      selected = "";
      rawBars = []; aggregated = []; chartBars = [];
      previousSourceTimeframe = "";
      page = 0;
      connectedState(false);
      renderCatalog();
      setEmpty("Čeká na přihlášení", "Přihlásit se stačí jednou na tomto zařízení.");
      $("api-status").textContent = "Odhlášeno ze StockToolu.";
      flash("Odhlášeno z Data Manageru i BUY Scanneru.");
    } catch(error) {
      flash(error.message,true);
    }
  }

  async function refreshAll(first = false) {
    if (!signedIn || busy) return;
    busy = true;
    try {
      const result = await getJson("datasets.php");
      catalog = result.datasets || [];
      if (catalog.length) {
        if (!catalog.some(d => d.symbol + "|" + d.timeframe === selected)) {
          const preferred = catalog.find(row => row.timeframe === "D1") || catalog[0];
          selected = preferred.symbol + "|" + preferred.timeframe;
          page = 0;
        }
      } else {
        selected = "";
      }
      renderCatalog();
      if (selected) await loadSelected();
      else setEmpty("Čeká na svíčky z MT5", "Zapni MT5 a spusť hromadný synchronizační program.");
      $("api-status").textContent = "API dostupné · poslední kontrola " + new Date().toLocaleTimeString("cs-CZ");
      connectedState(true);
    } catch (error) {
      $("api-status").textContent = "API chyba: " + error.message;
      if (/Nesprávný přístupový klíč|401/.test(error.message)) {
        connectedState(false);
        $("api-status").textContent = "Přihlášení vypršelo. Přihlas se znovu.";
      }
      if (first) throw error;
      flash(error.message, true);
    } finally {
      busy = false;
    }
  }

  async function loadSelected() {
    const id = selected;
    const [symbol, timeframe] = id.split("|");
    if (!symbol || !timeframe) return;
    const response = await getJson("candles.php?symbol=" + encodeURIComponent(symbol) +
      "&timeframe=" + encodeURIComponent(timeframe) + "&limit=5000");
    if (id !== selected) return;
    rawBars = (response.bars || []).map(bar => ({
      t: Number(bar.t) * 1000, o: Number(bar.o), h: Number(bar.h),
      l: Number(bar.l), c: Number(bar.c), v: Number(bar.v)
    })).filter(bar => Number.isFinite(bar.t) && Number.isFinite(bar.o)
      && Number.isFinite(bar.h) && Number.isFinite(bar.l) && Number.isFinite(bar.c))
      .sort((a, b) => a.t - b.t);

    // Genuine MT5 timeframe selector. Other intervals are not just
    // resampled from the currently displayed source.
    const available = catalog.filter(row => row.symbol === symbol)
      .sort((a, b) => PERIODS[a.timeframe] - PERIODS[b.timeframe]);
    const sourceSelector = $("source-timeframe");
    sourceSelector.replaceChildren();
    available.forEach(entry => {
      const option = document.createElement("option");
      option.value = entry.timeframe;
      option.textContent = entry.timeframe;
      sourceSelector.append(option);
    });
    sourceSelector.value = timeframe;
    sourceSelector.disabled = available.length < 2;
    $("available-frames").textContent = "Originální MT5 data: " +
      available.map(entry => entry.timeframe).join(", ");

    const activeTF = previousSourceTimeframe === timeframe ? $("view-timeframe").value : timeframe;
    previousSourceTimeframe = timeframe;
    const allowed = Object.keys(PERIODS).filter(tf => PERIODS[tf] >= PERIODS[timeframe]);
    const selector = $("view-timeframe");
    selector.replaceChildren();
    for (const tf of allowed) {
      const option = document.createElement("option");
      option.value = tf;
      option.textContent = tf;
      selector.append(option);
    }
    selector.value = allowed.includes(activeTF) ? activeTF : timeframe;
    selector.disabled = false;
    $("range").disabled = false;
    $("dataset-heading").textContent = symbol + " · " + timeframe;
    $("dataset-meta").textContent = "Server přijal data " + stamp(response.updated_at * 1000);
    $("dataset-source").textContent = "MT5 API";
    page = 0;
    rebuild();
  }

  function setEmpty(title, description) {
    $("dataset-heading").textContent = title;
    $("dataset-meta").textContent = description;
    $("dataset-source").textContent = signedIn ? "ČEKÁ NA MT5" : "OFFLINE";
    ["stat-count","stat-close","stat-high","stat-low",
      "quality-ohlc","quality-duplicates","quality-last"].forEach(id => $(id).textContent = "—");
    $("source-timeframe").disabled = true;
    $("source-timeframe").replaceChildren();
    $("available-frames").textContent = "Dostupnost se zobrazí po připojení.";
    $("stat-date").textContent = "Bez dat";
    $("stat-timeframe").textContent = "Bez dat";
    $("view-timeframe").disabled = true;
    $("range").disabled = true;
    $("chart-empty").hidden = false;
    $("table-meta").textContent = "Bez dat";
    rawBars = []; aggregated = []; chartBars = [];
    renderTable(); drawChart();
  }

  function bucket(t, tf) {
    if (tf === "W1") {
      const week = DAY * 7, monday = DAY * 4;
      return Math.floor((t - monday) / week) * week + monday;
    }
    const duration = PERIODS[tf] * 60000;
    return Math.floor(t / duration) * duration;
  }
  function aggregate(bars, tf) {
    const out = [];
    let lastBucket = -1;
    for (const b of bars) {
      const time = bucket(b.t, tf);
      if (time !== lastBucket) {
        out.push({t:time,o:b.o,h:b.h,l:b.l,c:b.c,v:b.v});
        lastBucket = time;
      } else {
        const last = out[out.length - 1];
        last.h = Math.max(last.h,b.h); last.l = Math.min(last.l,b.l);
        last.c = b.c; last.v += b.v;
      }
    }
    return out;
  }

  function rebuild() {
    if (!rawBars.length) return setEmpty("Bez dat", "Na serveru zatím nejsou žádné svíčky.");
    const timeframe = $("view-timeframe").value;
    const [symbol, sourceTf] = selected.split("|");
    aggregated = timeframe === sourceTf ? rawBars : aggregate(rawBars,timeframe);
    chartBars = aggregated.slice(-Number($("range").value));
    $("stat-count").textContent = num(rawBars.length);
    $("stat-timeframe").textContent = "Původní interval: " + sourceTf;
    const last = rawBars[rawBars.length - 1];
    $("stat-close").textContent = money(last.c);
    $("stat-date").textContent = stamp(last.t);
    let high=-Infinity,low=Infinity;
    for (const b of rawBars) { high=Math.max(high,b.h); low=Math.min(low,b.l); }
    $("stat-high").textContent = money(high);
    $("stat-low").textContent = money(low);
    let invalid = 0, duplicates = 0;
    for (let i = 0; i < rawBars.length; i++) {
      const b = rawBars[i];
      if (b.h < Math.max(b.o, b.c, b.l) ||
          b.l > Math.min(b.o, b.c, b.h) ||
          !Number.isFinite(b.v) || b.v < 0) invalid++;
      if (i && b.t === rawBars[i - 1].t) duplicates++;
    }
    $("quality-ohlc").textContent = invalid === 0 ? "OK · " + num(rawBars.length) : num(invalid) + " neplatných";
    $("quality-duplicates").textContent = num(duplicates);
    $("quality-last").textContent = stamp(last.t);
    $("chart-empty").hidden = false;
    $("chart-caption").textContent = num(aggregated.length) + " svíček · " + timeframe + " · čas MT5 (UTC formát)";
    $("table-meta").textContent = "Nejnovější první · " + timeframe;
    $("chart-empty").hidden = true;
    renderTable(); drawChart();
  }

  function renderTable() {
    const body = $("data-rows");
    body.replaceChildren();
    if (!aggregated.length) {
      const tr=document.createElement("tr"), td=document.createElement("td");
      td.colSpan=6;td.className="table-empty";td.textContent="Zatím žádné svíčky.";
      tr.append(td);body.append(tr);
      $("page-text").textContent="—";
      $("prev-page").disabled=$("next-page").disabled=true;
      return;
    }
    const len=aggregated.length;
    const start=len-1-page*PAGE_SIZE;
    const end=Math.max(-1,start-PAGE_SIZE);
    for(let i=start;i>end;i--){
      const b=aggregated[i], tr=document.createElement("tr");
      const values=[stamp(b.t),money(b.o),money(b.h),money(b.l),money(b.c),num(b.v)];
      values.forEach((v,k)=>{
        const td=document.createElement("td");td.textContent=v;
        if(k===4)td.className=b.c>=b.o?"positive":"negative";
        tr.append(td);
      });
      body.append(tr);
    }
    $("page-text").textContent=(page+1)+" / "+Math.ceil(len/PAGE_SIZE)+" · "+num(len)+" svíček";
    $("prev-page").disabled=page<=0;
    $("next-page").disabled=(page+1)*PAGE_SIZE>=len;
  }

  function drawChart() {
    const canvas=$("chart"),ctx=canvas.getContext("2d");
    if(!ctx)return;
    const width=Math.max(300,canvas.clientWidth||680),height=canvas.clientHeight||328;
    const dpr=Math.min(2.5,window.devicePixelRatio||1);
    canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
    ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
    if(!chartBars.length)return;
    const left=10,right=78,top=17,bottom=height-63;
    const pw=width-left-right,ph=bottom-top;
    let high=-Infinity,low=Infinity,maxVol=1;
    for(const b of chartBars){high=Math.max(high,b.h);low=Math.min(low,b.l);maxVol=Math.max(maxVol,b.v);}
    const extra=Math.max((high-low)*.08,Math.abs(high)*.0001,.000001);
    high+=extra;low-=extra;
    const y=price=>top+(high-price)/(high-low)*ph;
    ctx.font="10px ui-monospace,Consolas,monospace";ctx.textBaseline="middle";
    for(let i=0;i<5;i++){
      const yy=top+ph*i/4;
      ctx.strokeStyle="rgba(86,120,142,.22)";ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(left,yy);ctx.lineTo(left+pw,yy);ctx.stroke();
      ctx.fillStyle="#8aa9b7";ctx.fillText(money(high-(high-low)*i/4),width-right+10,yy);
    }
    const step=pw/chartBars.length,cw=Math.max(1,Math.min(10,step*.65));
    chartBars.forEach((b,i)=>{
      const cx=left+i*step+step/2;
      const color=b.c>=b.o?"#48e5bb":"#f18e8e";
      ctx.strokeStyle=ctx.fillStyle=color;ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(cx,y(b.h));ctx.lineTo(cx,y(b.l));ctx.stroke();
      const a=y(Math.max(b.o,b.c)),z=y(Math.min(b.o,b.c));
      ctx.fillRect(cx-cw/2,a,cw,Math.max(1,z-a));
      if(b.v>0){ctx.globalAlpha=.4;ctx.fillRect(cx-cw/2,height-43-(b.v/maxVol)*31,cw,(b.v/maxVol)*31);ctx.globalAlpha=1;}
    });
    ctx.fillStyle="#7996a8";
    const ticks=Math.min(6,chartBars.length);
    for(let i=0;i<ticks;i++){
      const index=ticks===1?0:Math.floor(i*(chartBars.length-1)/(ticks-1));
      const x=left+index*step;
      ctx.fillText(new Date(chartBars[index].t).toISOString().slice(5,10),Math.max(1,Math.min(width-105,x)),height-9);
    }
  }

  async function initialize() {
    $("year").textContent=String(new Date().getFullYear());
    $("dataset-filter").addEventListener("input",renderCatalog);
    $("source-timeframe").addEventListener("change", () => {
      const symbol = selected.split("|")[0];
      const timeframe = $("source-timeframe").value;
      if (!symbol || !timeframe) return;
      selected = symbol + "|" + timeframe;
      page = 0;
      renderCatalog();
      loadSelected().catch(error => flash(error.message, true));
    });
    $("connect-button").addEventListener("click",connect);
    $("access-key").addEventListener("keydown",event=>{if(event.key==="Enter")connect();});
    $("show-key").addEventListener("change",e=>{
      $("access-key").type=e.target.checked?"text":"password";
    });
    $("disconnect-button").addEventListener("click",disconnect);
    $("refresh-button").addEventListener("click",()=>refreshAll());
    $("view-timeframe").addEventListener("change",()=>{page=0;rebuild();});
    $("range").addEventListener("change",()=>{chartBars=aggregated.slice(-Number($("range").value));drawChart();});
    $("prev-page").addEventListener("click",()=>{page=Math.max(0,page-1);renderTable();});
    $("next-page").addEventListener("click",()=>{if((page+1)*PAGE_SIZE<aggregated.length)page++;renderTable();});
    $("chart").addEventListener("mousemove",event=>{
      if(!chartBars.length)return;
      const r=$("chart").getBoundingClientRect();
      const step=(r.width-88)/chartBars.length;
      const i=Math.floor(((event.clientX-r.left)-10)/step);
      if(i<0||i>=chartBars.length)return;
      const b=chartBars[i];
      $("hover-details").textContent=stamp(b.t)+" · O "+money(b.o)+" · H "+money(b.h)+" · L "+money(b.l)+" · C "+money(b.c)+" · V "+num(b.v);
    });
    $("chart").addEventListener("mouseleave",()=>{
      $("hover-details").textContent="Po najetí myší na svíčku zde uvidíš OHLCV.";
    });
    if("ResizeObserver" in window)new ResizeObserver(drawChart).observe($("chart-wrapper"));
    else window.addEventListener("resize",drawChart);
    window.setInterval(()=>{if(signedIn&&!document.hidden)refreshAll();},30000);
    setEmpty("Čeká na přihlášení", "Přihlásit se stačí jen jednou.");
    $("api-status").textContent = "Ověřuji zapamatované přihlášení…";
    try {
      const session = await getJson("session.php");
      if (session.authenticated) {
        connectedState(true);
        await refreshAll(true);
        $("api-status").textContent = "Přihlášeno automaticky · StockTool si tento prohlížeč pamatuje.";
      } else {
        connectedState(false);
        $("api-status").textContent = "První přihlášení: vlož API klíč jednou.";
      }
    } catch(error) {
      if (!signedIn) connectedState(false);
      $("api-status").textContent = "Kontrola přihlášení: "+error.message;
    }
  }
  document.addEventListener("DOMContentLoaded",initialize);
})();
