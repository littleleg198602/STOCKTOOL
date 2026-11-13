"use strict";

/**
 * StockTool SHORT Scanner v0.1
 * Read-only browser over private MT5 OHLCV D1 stored at FORPSI.
 * Never stores the key in localStorage, cookies, URLs, or source code.
 */
(() => {
  const $ = id => document.getElementById(id);
  const BATCH = 35;
  const PAGE_SIZE = 25;
  const PRIORITY = {BREAKDOWN:0,FAILED_RALLY:1,DOWNTREND:2,AVOID:3,WATCH:4,STALE:5,INSUFFICIENT:6,NONE:7};
  const LABELS = {BREAKDOWN:"BREAKDOWN",FAILED_RALLY:"FAILED RALLY",DOWNTREND:"DOWNTREND",AVOID:"NEBRAT",WATCH:"WATCH",NONE:"BEZ SHORT SETUPU",INSUFFICIENT:"MÁLO DAT",STALE:"STARÁ DATA"};
  const nf = new Intl.NumberFormat("cs-CZ",{maximumFractionDigits:2});
  const priceFormat = new Intl.NumberFormat("cs-CZ",{maximumFractionDigits:5});
  let signedIn = false;
  let results = [];
  let selectedSymbol = "";
  let selected = null;
  let filter = "short";
  let page = 0;
  let scanning = false;
  let scanComplete = false;
  let chartData = [];
  let requestSequence = 0;
  let toastTimer;

  function format(value,suffix="") {
    return value == null || !Number.isFinite(Number(value)) ? "—" : nf.format(Number(value)) + suffix;
  }
  function price(value) {
    return value == null || !Number.isFinite(Number(value)) ? "—" : priceFormat.format(Number(value));
  }
  function utc(t) {
    if (!t || !Number.isFinite(Number(t))) return "—";
    try { return new Date(Number(t) * 1000).toISOString().slice(0,10); }
    catch { return "—"; }
  }
  function utcDateTime(t) {
    if (!t || !Number.isFinite(Number(t))) return "—";
    try { return new Date(Number(t) * 1000).toISOString().slice(0,16).replace("T"," ") + " UTC"; }
    catch { return "—"; }
  }
  function setupClass(value) {
    return ["BREAKDOWN","FAILED_RALLY","DOWNTREND","WATCH","STALE","AVOID"].includes(value) ? value.toLowerCase() : "neutral";
  }
  function notify(text,error=false) {
    const el=$("toast");
    el.textContent=text;
    el.classList.toggle("error",error);
    el.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer=setTimeout(()=>el.classList.remove("visible"),4400);
  }
  function status(text,error=false) {
    $("connection-state").textContent=text;
    $("connection-state").classList.toggle("is-error",error);
  }

  async function request(url) {
    const response=await fetch(url,{
      method:"GET",cache:"no-store",credentials:"same-origin",
      headers:{"Accept":"application/json"}
    });
    let json;
    try {json=await response.json();}
    catch {throw new Error("Server nevrátil platný JSON. Zkontroluj nasazení PHP na FORPSI.");}
    if (!response.ok || json.ok!==true) {
      const reasons={
        invalid_api_key:"Přihlášení vypršelo nebo bylo odhlášeno.",
        not_configured:"Server ještě nemá soukromý config.php.",
        storage_unavailable:"Serverové úložiště není dostupné."
      };
      throw new Error(reasons[json.error] || "Serverová chyba: HTTP "+response.status+".");
    }
    return json;
  }

  function showSignedIn(yes) {
    signedIn = yes;
    $("login-controls").hidden = yes;
    $("scan-button").innerHTML = yes ? "Spustit SHORT Scanner <span>↗</span>"
                                   : "Přihlásit a spustit <span>↗</span>";
    $("logout-button").disabled = !yes;
    if (!yes) $("rescan-button").disabled = true;
  }

  async function loginOnce() {
    const key = $("api-key").value.trim();
    if (key.length < 32) throw new Error("Pro první přihlášení vlož existující StockTool API klíč.");
    try {
      const response = await fetch("../data-manager/api/login.php",{
        method:"POST",cache:"no-store",credentials:"same-origin",
        headers:{"X-StockTool-Key":key,"Accept":"application/json"}
      });
      const data = await response.json();
      if(!response.ok||!data.ok||!data.authenticated){
        throw new Error(response.status===401 ? "Nesprávný klíč." :
          "Server odmítl přihlášení (HTTP "+response.status+").");
      }
      showSignedIn(true);
      status("Přihlášeno · Data Manager a BUY Scanner si toto zařízení pamatují.");
    } finally {
      $("api-key").value="";
    }
  }

  async function restoreLogin() {
    try {
      const response=await fetch("../data-manager/api/session.php",{
        method:"GET",cache:"no-store",credentials:"same-origin"
      });
      const data=await response.json();
      if(response.ok&&data.ok&&data.authenticated){
        showSignedIn(true);
        status("Přihlášeno automaticky · můžeš rovnou spustit BUY Scanner.");
      } else {
        showSignedIn(false);
        status("Přihlas se jednou. Příště už klíč zadávat nebudeš.");
      }
    } catch(error) {
      showSignedIn(false);
      status("Přihlášení nelze ověřit: "+error.message,true);
    }
  }

  async function logout() {
    if(scanning)return notify("Nejdřív dokonči probíhající analýzu.",true);
    try {
      const response=await fetch("../data-manager/api/logout.php",{
        method:"POST",cache:"no-store",credentials:"same-origin"
      });
      if(!response.ok)throw new Error("Server nedokončil odhlášení.");
      showSignedIn(false);
      results=[];selected=null;selectedSymbol="";chartData=[];
      page=0;scanComplete=false;
      $("rescan-button").disabled=true;
      $("copy-tickers").disabled=true;
      $("export-txt").disabled=true;
      $("detail-symbol").textContent="Vyber akcii";
      $("detail-subtitle").textContent="Pro detail se nejdřív přihlas a spusť skener.";
      $("detail-setup").textContent="Nepřihlášeno";
      $("detail-setup").className="setup-pill neutral";
      ["detail-sma50","detail-sma200","detail-rsi","detail-atr","detail-high","detail-momentum"].forEach(id=>$(id).textContent="—");
      $("detail-reasons").replaceChildren();
      $("detail-risks").replaceChildren();
      $("chart-empty").hidden=false;
      $("chart-empty").textContent="Přihlas se a spusť analýzu.";
      drawChart();updateStats();renderTable();setProgress(0,1);
      status("Odhlášeno z BUY Scanneru i Data Manageru.");
      notify("Odhlášeno. Prohlížeč už relaci nepoužívá.");
    }catch(error){notify(error.message,true);}
  }

  function setProgress(done,total) {
    const pct=total>0?Math.min(100,Math.round(done/total*100)):100;
    $("progress-label").textContent = scanning
      ? "Prozkoumáno " + nf.format(done) + " / " + nf.format(total) + " D1 datasetů"
      : (scanComplete ? "Analýza dokončena. Data zůstávají na stránce do obnovení." : "Načtení ještě nezačalo.");
    $("progress-bar").style.width=pct+"%";
    $("progress-number").textContent=pct+" %";
  }

  function updateStats() {
    const short = results.filter(r=>r.candidate).length;
    const risk = results.filter(r=>r.risk).length;
    const avoid = results.filter(r=>r.avoid).length;
    $("stat-short").textContent = nf.format(short);
    $("stat-scanned").textContent = nf.format(results.length);
    $("stat-risk").textContent = nf.format(risk);
    $("stat-avoid").textContent = nf.format(avoid);
    $("stat-scanned-note").textContent = scanComplete ? "D1 datasety z MT5" : "Průběžné načítání";
  }

  async function runScan() {
    if (scanning) return;
    if (location.protocol!=="https:")return notify("Pro práci s API klíčem otevři zabezpečené HTTPS.",true);
    if (!signedIn) {
      try {await loginOnce();}
      catch(error){status(error.message,true);notify(error.message,true);return;}
    }
    scanning=true;
    scanComplete=false;
    results=[];
    selected=null;
    selectedSymbol="";
    chartData=[];
    drawChart();
    page=0;
    $("scan-button").disabled=true;
    $("rescan-button").disabled=true;
    $("copy-tickers").disabled=true;
    $("export-txt").disabled=true;
    status("Propojuji SHORT Scanner se StockTool API…");
    updateStats();renderTable();
    let done=0,total=1,failedFiles=0;
    setProgress(0,1);
    try {
      do {
        const result=await request("./api/scan.php?offset="+done+"&limit="+BATCH);
        total=Math.max(0,Number(result.total)||0);
        done+=Number(result.scanned)||0;
        failedFiles+=Number(result.errors)||0;
        if (!Array.isArray(result.results))throw new Error("Server nevrátil seznam výsledků.");
        results.push(...result.results);
        setProgress(done,total);
        updateStats();
        // Partial results stay visible during multi-batch scans.
        renderTable();
        if (done===0 && total>0)throw new Error("Server nepostupuje v dávkovém načítání.");
      } while(done<total);
      scanComplete=true;
      status("Připojeno · "+nf.format(results.length)+" D1 datasetů · "+(failedFiles?"Chybných souborů: "+failedFiles:"bez chyb při čtení")+" · "+new Date().toLocaleTimeString("cs-CZ"));
      setProgress(total,total);
      updateStats();renderTable();
      $("copy-tickers").disabled=false;
      $("export-txt").disabled=false;
      const best=filteredResults()[0];
      if(best)selectSymbol(best.symbol);
      notify("SHORT screening dokončen: "+nf.format(results.filter(x=>x.candidate).length)+" technických kandidátů.");
    } catch(error) {
      console.error("SHORT Scanner:",error);
      status("Chyba: "+error.message,true);
      if (/Přihlášení vypršelo|401/.test(error.message)) showSignedIn(false);
      notify("Sken se nepodařilo dokončit: "+error.message,true);
      setProgress(done,total);
      renderTable();
    } finally {
      scanning=false;
      $("scan-button").disabled=false;
      $("rescan-button").disabled=!signedIn;
    }
  }

  function filteredResults() {
    const term=$("ticker-search").value.trim().toUpperCase();
    const sort=$("sort-mode").value;
    let filtered=results.filter(r=>{
      if (term && !String(r.symbol).toUpperCase().includes(term)) return false;
      if(filter==="short") return !!r.candidate;
      if(filter==="risk") return !!r.risk;
      if(filter==="avoid") return !!r.avoid;
      if(filter==="all") return true;
      return r.setup===filter;
    });
    filtered.sort((a,b)=>{
      if(sort==="ticker")return a.symbol.localeCompare(b.symbol);
      if(sort==="rsi")return (a.rsi14??1e10)-(b.rsi14??1e10) || a.symbol.localeCompare(b.symbol);
      if(sort==="atr")return (b.atr_pct??-1e10)-(a.atr_pct??-1e10) || a.symbol.localeCompare(b.symbol);
      if(sort==="momentum")return (a.ret20_pct??1e10)-(b.ret20_pct??1e10) || a.symbol.localeCompare(b.symbol);
      if(filter==="risk"){
        return (b.risk_flags?.length||0)-(a.risk_flags?.length||0)
          || (b.atr_pct??0)-(a.atr_pct??0)
          || a.symbol.localeCompare(b.symbol);
      }
      if(filter==="avoid"){
        const avoidPriority={AVOID:0,STALE:1,INSUFFICIENT:2,NONE:3,WATCH:4};
        return (avoidPriority[a.setup]??5)-(avoidPriority[b.setup]??5)
          || (b.risk_flags?.length||0)-(a.risk_flags?.length||0)
          || a.symbol.localeCompare(b.symbol);
      }
      return (PRIORITY[a.setup]??99)-(PRIORITY[b.setup]??99)
        || (a.ret20_pct??1e10)-(b.ret20_pct??1e10)
        || a.symbol.localeCompare(b.symbol);
    });
    if($("top-ten").checked && ["short","risk","avoid"].includes(filter)){
      filtered=filtered.slice(0,filter==="short"?10:5);
    }
    return filtered;
  }

  function setCell(tr,text,className="") {
    const td=document.createElement("td");
    td.textContent=text;
    if(className)td.className=className;
    tr.append(td);
    return td;
  }
  function returnClass(value) {
    if(value==null)return "";
    return Number(value)>=0?"positive":"negative";
  }

  function renderTable() {
    const filtered=filteredResults();
    const total=filtered.length;
    const pages=Math.max(1,Math.ceil(total/PAGE_SIZE));
    page=Math.min(page,pages-1);
    $("filtered-count").textContent="("+nf.format(total)+")";
    const tbody=$("results-body");
    tbody.replaceChildren();
    if(!total) {
      const tr=document.createElement("tr");
      const td=document.createElement("td");
      td.className="empty-cell";td.colSpan=9;
      td.textContent=scanning ? "Načítám výsledky z MT5…" :
        !results.length ? "Pro analýzu se přihlas a spusť SHORT Scanner." :
        "Žádná akcie neodpovídá zvoleným filtrům.";
      tr.append(td);tbody.append(tr);
    } else {
      for(const r of filtered.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE)) {
        const tr=document.createElement("tr");
        if(r.symbol===selectedSymbol)tr.className="chosen";
        const tickerCell=document.createElement("td");
        const button=document.createElement("button");
        button.type="button";button.className="ticker-button";
        button.textContent=r.symbol;
        button.setAttribute("aria-label","Zobrazit detail "+r.symbol);
        button.addEventListener("click",()=>selectSymbol(r.symbol));
        tickerCell.append(button);tr.append(tickerCell);
        const td=document.createElement("td");
        const pill=document.createElement("span");
        pill.className="setup-chip "+setupClass(r.setup);
        pill.textContent=LABELS[r.setup]||r.setup;
        td.append(pill);tr.append(td);
        setCell(tr,price(r.close));
        setCell(tr,format(r.rsi14));
        setCell(tr,format(r.ret20_pct,"%"),returnClass(r.ret20_pct));
        setCell(tr,format(r.vs_sma200_pct,"%"),returnClass(r.vs_sma200_pct));
        setCell(tr,format(r.atr_pct,"%"));
        setCell(tr,r.risk_flags?.length ? String(r.risk_flags.length)+" var." : "—",
          r.risk_flags?.length ? "negative" : "");
        setCell(tr,utc(r.last_time));
        tbody.append(tr);
      }
    }
    $("page-caption").textContent=total ? (page+1)+" / "+pages : "—";
    $("prev-page").disabled=page===0;
    $("next-page").disabled=page>=pages-1;
    const top=$("top-ten").checked && ["short","risk","avoid"].includes(filter)
      ? " · Top "+(filter==="short"?"10":"5") : "";
    $("table-note").textContent="Zobrazeno "+nf.format(total)+" titulů"+top+
      " · Výpůjční náklady, shortovatelnost a možné gapy nejsou z OHLCV zjistitelné.";
  }

  function selectSymbol(symbol) {
    const r=results.find(item=>item.symbol===symbol);
    if(!r)return;
    selected=r;
    selectedSymbol=r.symbol;
    renderTable();
    $("detail-symbol").textContent=r.symbol+" · D1";
    $("detail-subtitle").textContent=nf.format(r.count)+" svíček · poslední "+utcDateTime(r.last_time);
    const pill=$("detail-setup");
    pill.className="setup-pill "+setupClass(r.setup);
    pill.textContent=LABELS[r.setup]||r.setup;
    $("detail-sma50").textContent=price(r.sma50);
    $("detail-sma200").textContent=price(r.sma200);
    $("detail-rsi").textContent=format(r.rsi14);
    $("detail-atr").textContent=format(r.atr_pct,"%");
    $("detail-low").textContent=format(r.from_52w_low_pct,"%");
    $("detail-momentum").textContent=format(r.ret20_pct,"%");
    $("detail-reasons").replaceChildren();
    (Array.isArray(r.reasons)?r.reasons:[]).forEach(reason=>{
      const li=document.createElement("li");
      li.textContent=reason;
      $("detail-reasons").append(li);
    });
    const risks=$("detail-risks");
    risks.replaceChildren();
    const riskFlags=Array.isArray(r.risk_flags)?r.risk_flags:[];
    for (const text of (riskFlags.length ? riskFlags :
        ["Z vybraných OHLC filtrů nevyplynulo extrémní riziko. Půjčení akcie, náklady a gapy se neověřují."])) {
      const li=document.createElement("li");
      li.textContent=text;
      risks.append(li);
    }
    $("detail-footer").textContent="Data: MT5 D1 · OHLC chyby "+nf.format(r.invalid_bars||0)+
      " · Duplicitní časy "+nf.format(r.duplicate_times||0)+
      " · Dostupnost shortování neověřena.";
    loadChart(r.symbol);
  }

  async function loadChart(symbol) {
    const generation=++requestSequence;
    $("chart-empty").hidden=false;
    $("chart-empty").textContent="Načítám historické ceny…";
    chartData=[];drawChart();
    try {
      const body=await request("../data-manager/api/candles.php?symbol="+encodeURIComponent(symbol)+"&timeframe=D1&limit=180");
      if(generation!==requestSequence || selectedSymbol!==symbol)return;
      chartData=(body.bars||[]).map(row=>({time:Number(row.t),close:Number(row.c)}))
        .filter(row=>Number.isFinite(row.time)&&Number.isFinite(row.close))
        .sort((a,b)=>a.time-b.time);
      $("chart-empty").hidden=chartData.length>1;
      if(chartData.length<=1)$("chart-empty").textContent="Pro graf není dost svíček.";
      drawChart();
    } catch(error) {
      if(generation!==requestSequence)return;
      $("chart-empty").hidden=false;
      $("chart-empty").textContent="Graf nelze načíst: "+error.message;
    }
  }

  function drawChart() {
    const canvas=$("detail-chart");
    const context=canvas.getContext("2d");
    if(!context)return;
    const width=Math.max(180,canvas.clientWidth||340);
    const height=canvas.clientHeight||180;
    const dpr=Math.min(window.devicePixelRatio||1,2.5);
    canvas.width=Math.ceil(width*dpr);
    canvas.height=Math.ceil(height*dpr);
    context.setTransform(dpr,0,0,dpr,0,0);
    context.clearRect(0,0,width,height);
    if(chartData.length<2)return;
    const series=chartData.slice(-120);
    const closes=series.map(row=>row.close);
    let min=Math.min(...closes),max=Math.max(...closes);
    const extra=Math.max((max-min)*.08,Math.abs(max)*.0002,.00001);
    min-=extra;max+=extra;
    const left=13,right=12,top=15,bottom=27;
    const x=index=>left+index/(series.length-1)*(width-left-right);
    const y=value=>top+(max-value)/(max-min)*(height-top-bottom);
    context.lineWidth=1;
    context.strokeStyle="rgba(127,167,184,.21)";
    for(let n=0;n<4;n++){
      const yy=top+(height-top-bottom)*n/3;
      context.beginPath();context.moveTo(left,yy);context.lineTo(width-right,yy);context.stroke();
    }
    const rising=closes[closes.length-1]>=closes[0];
    const color=rising?"#53d9b8":"#ff9a9f";
    context.beginPath();
    series.forEach((item,index)=>{
      if(index===0)context.moveTo(x(index),y(item.close));
      else context.lineTo(x(index),y(item.close));
    });
    context.strokeStyle=color;context.lineWidth=2;context.stroke();
    context.fillStyle=color;
    context.beginPath();
    context.arc(x(series.length-1),y(closes[closes.length-1]),3,0,Math.PI*2);
    context.fill();
    context.fillStyle="#87a9b6";
    context.font="10px ui-monospace,Consolas,monospace";
    context.textBaseline="bottom";
    context.fillText(utc(series[0].time),left,height-5);
    const label=utc(series[series.length-1].time);
    context.fillText(label,Math.max(left,width-right-context.measureText(label).width),height-5);
  }

  function exportRows() {
    return filteredResults();
  }
  function tickerLine() {
    return exportRows().map(row=>row.symbol).join(",");
  }
  async function copyTickers() {
    const line=tickerLine();
    if(!line)return notify("Aktuální filtr neobsahuje žádné tickery.",true);
    try {
      await navigator.clipboard.writeText(line);
      notify("Zkopírováno "+exportRows().length+" tickerů v jednom řádku pro MT5.");
    } catch {
      notify("Zkopírování selhalo. Zkus stáhnout TXT výstup.",true);
    }
  }
  function exportText() {
    const items=exportRows();
    if(!items.length)return notify("Aktuální filtr neobsahuje žádné výsledky.",true);
    const lines=[
      "STOCKTOOL SHORT SCANNER v0.1",
      "Zdroj: MetaTrader 5 / D1 | Neinvesticni technicky screening. Dostupnost shortovani neoverena.",
      "Vygenerovano: "+new Date().toISOString(),
      "Vyber: "+filter+" | radit: "+$("sort-mode").value+" | pocet: "+items.length,
      "",
      "TICKERY PRO MT5:",
      items.map(row=>row.symbol).join(","),
      "",
      "DETAILY:"
    ];
    items.forEach((r,i)=>{
      lines.push((i+1)+". "+r.symbol+" | "+(LABELS[r.setup]||r.setup)+
        " | close "+price(r.close)+" | RSI14 "+format(r.rsi14)+
        " | 20D "+format(r.ret20_pct,"%")+" | SMA200 "+format(r.vs_sma200_pct,"%")+
        " | posledni D1 "+utc(r.last_time));
      (r.reasons||[]).forEach(line=>lines.push("   - "+line));
      (r.risk_flags||[]).forEach(line=>lines.push("   RIZIKO: "+line));
    });
    const blob=new Blob(["\uFEFF"+lines.join("\r\n")+"\r\n"],{type:"text/plain;charset=utf-8"});
    const url=URL.createObjectURL(blob);
    const link=document.createElement("a");
    link.href=url;link.download="StockTool_SHORT_"+new Date().toISOString().slice(0,10)+".txt";
    document.body.append(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),3000);
    notify("TXT výstup připraven: "+items.length+" titulů.");
  }

  function bind() {
    $("year").textContent=String(new Date().getFullYear());
    $("scan-button").addEventListener("click",runScan);
    $("rescan-button").addEventListener("click",runScan);
    $("logout-button").addEventListener("click",logout);
    $("api-key").addEventListener("keydown",event=>{if(event.key==="Enter")runScan();});
    $("show-key").addEventListener("click",()=>{
      const el=$("api-key");
      el.type=el.type==="password"?"text":"password";
    });
    for(const chip of document.querySelectorAll("[data-filter]")){
      chip.addEventListener("click",()=>{
        filter=chip.dataset.filter;
        for(const item of document.querySelectorAll("[data-filter]")){
          const active=item===chip;
          item.classList.toggle("active",active);
          item.setAttribute("aria-pressed",String(active));
        }
        page=0;renderTable();
      });
    }
    $("sort-mode").addEventListener("change",()=>{page=0;renderTable();});
    $("ticker-search").addEventListener("input",()=>{page=0;renderTable();});
    $("top-ten").addEventListener("change",()=>{page=0;renderTable();});
    $("prev-page").addEventListener("click",()=>{page=Math.max(0,page-1);renderTable();});
    $("next-page").addEventListener("click",()=>{page++;renderTable();});
    $("copy-tickers").addEventListener("click",copyTickers);
    $("export-txt").addEventListener("click",exportText);
    if("ResizeObserver" in window){
      new ResizeObserver(drawChart).observe(document.querySelector(".detail-chart"));
    } else window.addEventListener("resize",drawChart);
    updateStats();
    setProgress(0,1);
    restoreLogin();
  }
  document.addEventListener("DOMContentLoaded",bind);
})();
