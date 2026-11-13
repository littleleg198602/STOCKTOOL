"use strict";
/**
 * StockTool Market Pressure Scanner v0.1.
 * Read-only analysis from stored MT5 D1 OHLCV, never an orderflow feed.
 * Shared HttpOnly PHP session with Data Manager, BUY, SHORT; no key storage.
 */
(() => {
  const $ = id => document.getElementById(id);
  const BATCH = 30;
  const PAGE_SIZE = 25;
  const nf = new Intl.NumberFormat("cs-CZ",{maximumFractionDigits:2});
  const priceFormat = new Intl.NumberFormat("cs-CZ",{maximumFractionDigits:5});
  const LABELS = {
    PANIC:"PANICKÁ PROXY",FORCED_PROXY:"FORCED PROXY",REVERSAL:"MOŽNÝ OBRAT",
    EXHAUSTION:"VYČERPÁNÍ",CONTINUATION:"PRODEJNÍ TLAK",WATCH:"WATCH",
    NONE:"BEZ SIGNÁLU",STALE:"STARÁ DATA",INSUFFICIENT:"MÁLO DAT",BAD_DATA:"CHYBA DAT"
  };
  const PRIORITY = {
    FORCED_PROXY:0,PANIC:1,CONTINUATION:2,EXHAUSTION:3,REVERSAL:4,
    WATCH:5,NONE:6,STALE:7,INSUFFICIENT:8,BAD_DATA:9
  };
  let signedIn=false,scanning=false,scanComplete=false,results=[],selectedSymbol="";
  let filter="pressure",page=0,chartData=[],chartGeneration=0,toastTimer;
  const fmt=(value,suffix="")=>value===null||value===undefined||
    !Number.isFinite(Number(value))?"—":nf.format(Number(value))+suffix;
  const price=value=>value==null||!Number.isFinite(Number(value))
    ?"—":priceFormat.format(Number(value));
  const date=t=>t&&Number.isFinite(Number(t))?new Date(Number(t)*1000).toISOString().slice(0,10):"—";
  const dateTime=t=>t&&Number.isFinite(Number(t))?
    new Date(Number(t)*1000).toISOString().slice(0,16).replace("T"," ")+" UTC":"—";

  function notify(message,isError=false) {
    const node=$("toast");
    node.textContent=message;
    node.classList.toggle("error",isError);
    node.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer=setTimeout(()=>node.classList.remove("visible"),4200);
  }
  function status(message,isError=false){
    $("connection-state").textContent=message;
    $("connection-state").classList.toggle("is-error",isError);
  }
  function showSignedIn(value) {
    signedIn=value;
    $("login-controls").hidden=value;
    $("scan-button").textContent=value?"Spustit analýzu ↗":"Přihlásit a analyzovat ↗";
    $("logout-button").disabled=!value;
    if(!value)$("rescan-button").disabled=true;
  }
  async function request(url) {
    const response=await fetch(url,{
      method:"GET",cache:"no-store",credentials:"same-origin",
      headers:{"Accept":"application/json"}
    });
    let body;
    try{body=await response.json();}
    catch{throw new Error("Server nevrátil JSON. Zkontroluj nasazení PHP na FORPSI.");}
    if(!response.ok||!body.ok) {
      if(response.status===401) {
        showSignedIn(false);
        throw new Error("Přihlášení vypršelo. Přihlas se jednou stávajícím klíčem.");
      }
      throw new Error("Chyba API ("+response.status+"): "+String(body.error||"neznámá"));
    }
    return body;
  }
  async function loginOnce(){
    const key=$("api-key").value.trim();
    if(key.length<32)throw new Error("Vlož stávající soukromý StockTool klíč.");
    try{
      const response=await fetch("../data-manager/api/login.php",{
        method:"POST",credentials:"same-origin",cache:"no-store",
        headers:{"X-StockTool-Key":key,"Accept":"application/json"}
      });
      const json=await response.json();
      if(!response.ok||!json.ok||!json.authenticated){
        throw new Error(response.status===401?"Nesprávný API klíč.":
          "Přihlášení se nezdařilo (HTTP "+response.status+").");
      }
      showSignedIn(true);
      status("Přihlášeno · stejná relace jako v Data Manageru, BUY a SHORT Scanneru.");
    }finally{$("api-key").value="";}
  }
  async function restoreLogin(){
    try{
      const response=await fetch("../data-manager/api/session.php",{
        method:"GET",credentials:"same-origin",cache:"no-store"
      });
      const body=await response.json();
      if(response.ok&&body.ok&&body.authenticated){
        showSignedIn(true);
        status("Přihlášeno automaticky · načítám D1 data pro analýzu.");
        await runScan();
      }else {
        showSignedIn(false);
        status("Poprvé se přihlas stávajícím klíčem. Příště už nebude potřeba.");
      }
    }catch(error){
      if(!signedIn)showSignedIn(false);
      status("Ověření relace: "+error.message,true);
    }
  }

  function progress(done,total){
    const percentage=total===0?100:Math.min(100,Math.round(done/total*100));
    $("progress-bar").style.width=percentage+"%";
    $("progress-number").textContent=percentage+" %";
    $("progress-label").textContent=scanning?
      "Prozkoumáno "+nf.format(done)+" / "+nf.format(total)+" D1 datasetů":
      scanComplete?"Sken dokončen, výsledky jsou připravené.":"Analýza zatím nezačala.";
  }
  function stats(){
    $("stat-scanned").textContent=nf.format(results.length);
    $("stat-panic").textContent=nf.format(results.filter(r=>r.panic).length);
    $("stat-forced").textContent=nf.format(results.filter(r=>r.forced_proxy).length);
    $("stat-reversal").textContent=nf.format(results.filter(r=>r.exhaustion||r.reversal).length);
    $("stat-scanned-note").textContent=scanComplete?"Z analyzovaných D1 souborů":"Průběžné načítání";
  }

  async function runScan(){
    if(scanning)return;
    if(location.protocol!=="https:")return notify("Přihlášení vyžaduje HTTPS.",true);
    if(!signedIn){
      try{await loginOnce();}
      catch(e){status(e.message,true);return notify(e.message,true);}
    }
    scanning=true;scanComplete=false;results=[];selectedSymbol="";page=0;
    chartGeneration++;chartData=[];drawChart();
    $("detail-symbol").textContent="Analyzuji data…";
    $("detail-setup").textContent="Čekám na první výsledky";
    $("chart-empty").hidden=false;
    $("chart-empty").textContent="Graf se načte po zvolení tickeru.";
    $("scan-button").disabled=true;
    $("rescan-button").disabled=true;
    $("copy-tickers").disabled=true;
    $("export-txt").disabled=true;
    $("export-all").disabled=true;
    status("Načítám uzavřené D1 svíčky ze soukromého úložiště FORPSI…");
    let scanned=0,total=1,readErrors=0;
    progress(0,1);stats();renderTable();
    try{
      do {
        const batch=await request("./api/scan.php?offset="+scanned+"&limit="+BATCH);
        total=Number(batch.total)||0;
        const advancement=Number(batch.scanned)||0;
        if(total>scanned&&advancement<=0)throw new Error("API nepostupuje ve zpracování dat.");
        if(!Array.isArray(batch.results))throw new Error("API nevrátilo seznam indikací.");
        results.push(...batch.results);
        readErrors+=Number(batch.errors)||0;
        scanned+=advancement;
        progress(scanned,total);
        stats();renderTable();
      }while(scanned<total);
      scanComplete=true;
      progress(total,total);
      stats();renderTable();
      $("copy-tickers").disabled=false;
      $("export-txt").disabled=false;
      $("export-all").disabled=false;
      status("Hotovo: "+nf.format(results.length)+" D1 akcií"+
        (readErrors?" · chybných souborů: "+readErrors:" · bez chyb čtení")+
        " · "+new Date().toLocaleTimeString("cs-CZ"));
      const first=filteredResults()[0];
      if(first)selectSymbol(first.symbol);
      notify("Market Pressure: "+nf.format(results.filter(r=>r.panic||r.forced_proxy).length)+
        " akcií s cenovou indikací paniky či nucených výprodejů.");
    }catch(e){
      status("Sken nedokončen: "+e.message,true);
      notify(e.message,true);
      progress(scanned,total);
      renderTable();
    }finally{
      scanning=false;
      $("scan-button").disabled=false;
      $("rescan-button").disabled=!signedIn;
    }
  }

  function matches(row){
    if(filter==="all")return true;
    if(filter==="pressure")return !!(row.continuation||row.panic||row.forced_proxy);
    if(filter==="panic")return !!row.panic;
    if(filter==="forced")return !!row.forced_proxy;
    if(filter==="exhaustion")return !!row.exhaustion;
    if(filter==="reversal")return !!row.reversal;
    if(filter==="watch_buy")return !!row.watch_buy;
    if(filter==="watch_down")return !!row.watch_down;
    return false;
  }
  function sorted(items,mode){
    items.sort((a,b)=>{
      const az=String(a.symbol),bz=String(b.symbol);
      if(mode==="ticker")return az.localeCompare(bz);
      if(mode==="volume")return (b.tick_volume_ratio??-1)-(a.tick_volume_ratio??-1)||az.localeCompare(bz);
      if(mode==="fall")return (a.ret5_pct??1e10)-(b.ret5_pct??1e10)||az.localeCompare(bz);
      if(mode==="points")return (b.pressure_points??0)-(a.pressure_points??0)||az.localeCompare(bz);
      if(filter==="watch_buy"||filter==="reversal"||filter==="exhaustion"){
        const p={REVERSAL:0,EXHAUSTION:1};
        return (p[a.setup]??2)-(p[b.setup]??2)
          || (b.pressure_points??0)-(a.pressure_points??0)||az.localeCompare(bz);
      }
      return (PRIORITY[a.setup]??9)-(PRIORITY[b.setup]??9)
        || (b.pressure_points??0)-(a.pressure_points??0)
        || (a.ret5_pct??1e10)-(b.ret5_pct??1e10)||az.localeCompare(bz);
    });
    return items;
  }
  function filteredResults(){
    const term=$("ticker-search").value.trim().toUpperCase();
    let items=sorted(results.filter(row=>
      matches(row)&&String(row.symbol).toUpperCase().includes(term)), $("sort-mode").value);
    if($("top-ten").checked)items=items.slice(0,10);
    return items;
  }
  function cell(tr,value,css=""){
    const td=document.createElement("td");
    td.textContent=value;
    if(css)td.className=css;
    tr.append(td);
  }
  function direction(value){
    if(value==null)return "";
    return value<0?"negative":"positive";
  }
  function renderTable(){
    const list=filteredResults(),length=list.length;
    const pages=Math.max(1,Math.ceil(length/PAGE_SIZE));
    page=Math.min(page,pages-1);
    $("filtered-count").textContent="("+nf.format(length)+")";
    const tbody=$("results-body");
    tbody.replaceChildren();
    if(!length){
      const row=document.createElement("tr"),td=document.createElement("td");
      td.className="empty-cell";td.colSpan=8;
      td.textContent=scanning?"Zpracovávám historické svíčky…" :
        !scanComplete?"Přihlas se a spusť analýzu." :
        "Tento filtr neobsahuje žádné výsledky. Zkus Všechny.";
      row.append(td);tbody.append(row);
    }else{
      for(const item of list.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE)){
        const row=document.createElement("tr");
        if(item.symbol===selectedSymbol)row.className="chosen";
        const name=document.createElement("td"),btn=document.createElement("button");
        btn.className="ticker-button";btn.type="button";btn.textContent=item.symbol;
        btn.setAttribute("aria-label","Detail akcie "+item.symbol);
        btn.addEventListener("click",()=>selectSymbol(item.symbol));
        name.append(btn);row.append(name);
        const setup=document.createElement("td"),badge=document.createElement("span");
        badge.className="setup-chip "+String(item.setup||"NONE").toLowerCase();
        badge.textContent=LABELS[item.setup]||item.setup;
        setup.append(badge);row.append(setup);
        cell(row,fmt(item.ret1_pct,"%"),direction(item.ret1_pct));
        cell(row,fmt(item.ret5_pct,"%"),direction(item.ret5_pct));
        cell(row,fmt(item.range_atr,"×"));
        cell(row,fmt(item.tick_volume_ratio,"×"));
        cell(row,item.pressure_points!=null?String(item.pressure_points)+" / 9":"—");
        cell(row,date(item.last_time));
        tbody.append(row);
      }
    }
    $("page-caption").textContent=length?String(page+1)+" / "+pages:"—";
    $("prev-page").disabled=page===0;
    $("next-page").disabled=page>=pages-1;
    $("table-note").textContent="Zobrazeno "+nf.format(length)+" akcií"+
      ($("top-ten").checked?" · Top 10":"")+
      " · 0–9 bodů = pozorované podmínky, ne pravděpodobnost výnosu.";
  }

  function selectSymbol(symbol){
    const item=results.find(row=>row.symbol===symbol);
    if(!item)return;
    selectedSymbol=symbol;renderTable();
    $("detail-symbol").textContent=symbol+" · D1";
    $("detail-subtitle").textContent=nf.format(item.count)+" svíček · poslední "+dateTime(item.last_time);
    const badge=$("detail-setup");
    badge.className="setup-pill "+String(item.setup||"none").toLowerCase();
    badge.textContent=LABELS[item.setup]||item.setup;
    $("detail-ret1").textContent=fmt(item.ret1_pct,"%");
    $("detail-ret5").textContent=fmt(item.ret5_pct,"%");
    $("detail-move-atr").textContent=fmt(item.move_atr,"×");
    $("detail-range-atr").textContent=fmt(item.range_atr,"×");
    $("detail-clv").textContent=fmt(item.close_location_pct,"%");
    $("detail-volume").textContent=fmt(item.tick_volume_ratio,"×");
    $("detail-down5").textContent=fmt(item.down_days5);
    $("detail-points").textContent=item.pressure_points+" / 9";
    $("detail-reasons").replaceChildren();
    for(const text of item.reasons||[]){
      const li=document.createElement("li");li.textContent=text;$("detail-reasons").append(li);
    }
    $("detail-warnings").replaceChildren();
    for(const text of item.warnings||[]){
      const li=document.createElement("li");li.textContent=text;$("detail-warnings").append(li);
    }
    $("detail-footer").textContent="MT5 D1 · chybných svíček "+(item.invalid_bars||0)+
      " · duplicit "+(item.duplicate_times||0)+
      " · přijatá data "+dateTime(item.updated_at)+
      " · bez skutečného order flow.";
    loadChart(symbol);
  }

  async function loadChart(symbol){
    const version=++chartGeneration;
    chartData=[];
    $("chart-empty").hidden=false;
    $("chart-empty").textContent="Načítám D1 graf…";
    drawChart();
    try{
      const response=await request("../data-manager/api/candles.php?symbol="+
        encodeURIComponent(symbol)+"&timeframe=D1&limit=130");
      if(version!==chartGeneration||selectedSymbol!==symbol)return;
      chartData=(response.bars||[]).map(bar=>({
        t:Number(bar.t),close:Number(bar.c)
      })).filter(row=>Number.isFinite(row.t)&&Number.isFinite(row.close))
        .sort((a,b)=>a.t-b.t);
      $("chart-empty").hidden=chartData.length>=2;
      if(chartData.length<2)$("chart-empty").textContent="Nedostatečná historie pro graf.";
      drawChart();
    }catch(e){
      if(version!==chartGeneration)return;
      $("chart-empty").hidden=false;
      $("chart-empty").textContent="Graf nedostupný: "+e.message;
    }
  }
  function drawChart(){
    const canvas=$("detail-chart"),ctx=canvas.getContext("2d");
    if(!ctx)return;
    const width=Math.max(180,canvas.clientWidth||340),height=canvas.clientHeight||190;
    const dpr=Math.min(window.devicePixelRatio||1,2.5);
    canvas.width=Math.ceil(width*dpr);canvas.height=Math.ceil(height*dpr);
    ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.clearRect(0,0,width,height);
    if(chartData.length<2)return;
    const rows=chartData.slice(-120),prices=rows.map(r=>r.close);
    let lower=Math.min(...prices),upper=Math.max(...prices);
    const pad=Math.max((upper-lower)*.09,Math.abs(upper)*.0002,0.0001);
    lower-=pad;upper+=pad;
    const L=12,R=12,T=14,B=28;
    const xp=i=>L+i/(rows.length-1)*(width-L-R);
    const yp=v=>T+(upper-v)/(upper-lower)*(height-T-B);
    ctx.lineWidth=1;ctx.strokeStyle="rgba(125,167,185,.23)";
    for(let i=0;i<4;i++){
      const y=T+(height-T-B)*i/3;
      ctx.beginPath();ctx.moveTo(L,y);ctx.lineTo(width-R,y);ctx.stroke();
    }
    const color=prices[prices.length-1] < prices[0]?"#f9b27d":"#61e0c7";
    ctx.beginPath();
    rows.forEach((r,i)=>i===0?ctx.moveTo(xp(i),yp(r.close)):ctx.lineTo(xp(i),yp(r.close)));
    ctx.strokeStyle=color;ctx.lineWidth=2;ctx.stroke();
    ctx.fillStyle=color;
    ctx.beginPath();ctx.arc(xp(rows.length-1),yp(prices[prices.length-1]),3,0,Math.PI*2);ctx.fill();
    ctx.font="10px ui-monospace,Consolas,monospace";
    ctx.fillStyle="#9eb9c4";ctx.textBaseline="bottom";
    ctx.fillText(date(rows[0].t),L,height-4);
    const rightDate=date(rows[rows.length-1].t);
    ctx.fillText(rightDate,Math.max(L,width-R-ctx.measureText(rightDate).width),height-4);
  }

  function tickerLine(rows){return rows.map(r=>r.symbol).join(",");}
  async function copyTickers(){
    const rows=filteredResults();
    if(!rows.length)return notify("Aktuální výběr je prázdný.",true);
    try{await navigator.clipboard.writeText(tickerLine(rows));
      notify("Zkopírováno "+rows.length+" tickerů v jednom řádku pro MT5.");}
    catch{notify("Schránka nepovolila kopírování. Použij TXT export.",true);}
  }
  function makeReport(sections,filename){
    const lines=[
      "STOCKTOOL MARKET PRESSURE SCANNER v0.1",
      "Vytvoreno: "+new Date().toISOString(),
      "Zdroj: MT5 D1 OHLC + broker tick volume",
      "Panic / Forced Selling = CENOVA PROXY, NIKOLIV POTVRZENA LIKVIDACE.",
      "Nejde o pokyn BUY nebo SHORT, ani o skutecny order flow.",
      "Analyzovano D1 souboru: "+results.length,
      ""
    ];
    for(const [heading,rows] of sections){
      lines.push("===== "+heading+" =====");
      lines.push("TICKERY PRO MT5: "+(rows.length?tickerLine(rows):"ZADNE"));
      for(const [i,row] of rows.entries()){
        lines.push((i+1)+". "+row.symbol+" | "+(LABELS[row.setup]||row.setup)+
          " | 1D "+fmt(row.ret1_pct,"%")+" | 5D "+fmt(row.ret5_pct,"%")+
          " | rozp./ATR "+fmt(row.range_atr,"x")+
          " | tick volume "+fmt(row.tick_volume_ratio,"x")+
          " | tlak "+row.pressure_points+"/9 | "+date(row.last_time));
        for(const text of row.reasons||[])lines.push("  - "+text);
        for(const text of row.warnings||[])lines.push("  POZOR: "+text);
      }
      lines.push("");
    }
    const blob=new Blob(["\uFEFF"+lines.join("\r\n")+"\r\n"],{type:"text/plain;charset=utf-8"});
    const url=URL.createObjectURL(blob),a=document.createElement("a");
    a.href=url;a.download=filename;a.style.display="none";
    document.body.append(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),3000);
    notify("TXT report připraven: "+filename);
  }
  function exportText(){
    if(!scanComplete)return notify("Nejdřív dokonči analýzu.",true);
    makeReport([["VYBRANY FILTR: "+filter,filteredResults()]],
      "StockTool_MarketPressure_"+new Date().toISOString().slice(0,10)+".txt");
  }
  function exportAll(){
    if(!scanComplete)return notify("Nejdřív dokonči analýzu.",true);
    const byPressure=sorted(results.filter(r=>r.panic||r.forced_proxy||r.continuation),
      "points").slice(0,10);
    const byForced=sorted(results.filter(r=>r.forced_proxy),"points").slice(0,10);
    const byReversal=results.filter(r=>r.reversal||r.exhaustion)
      .sort((a,b)=>(a.reversal===b.reversal?0:a.reversal?-1:1)
        ||(b.pressure_points||0)-(a.pressure_points||0)).slice(0,10);
    const byDown=sorted(results.filter(r=>r.watch_down),"fall").slice(0,10);
    makeReport([
      ["TOP 10 VYPRODEJOVY TLAK",byPressure],
      ["TOP 10 FORCED SELLING PROXY",byForced],
      ["TOP 10 MOZNE OBRATY A VYCERPANI",byReversal],
      ["TOP 10 POKRACOVANI POKLESU",byDown]
    ],"StockTool_MarketPressure_Top10_"+new Date().toISOString().slice(0,10)+".txt");
  }

  async function logout(){
    if(scanning)return notify("Nejdřív dokonči probíhající sken.",true);
    try{
      const response=await fetch("../data-manager/api/logout.php",{
        method:"POST",credentials:"same-origin",cache:"no-store"
      });
      if(!response.ok)throw new Error("Server nepotvrdil odhlášení.");
      showSignedIn(false);scanComplete=false;results=[];selectedSymbol="";chartData=[];page=0;
      chartGeneration++;
      ["detail-ret1","detail-ret5","detail-move-atr","detail-range-atr","detail-clv",
       "detail-volume","detail-down5","detail-points"].forEach(id=>$(id).textContent="—");
      $("detail-symbol").textContent="Vyber akcii";
      $("detail-subtitle").textContent="Přihlas se a spusť sken.";
      $("detail-setup").textContent="Nepřihlášeno";
      $("detail-setup").className="setup-pill neutral";
      $("detail-reasons").replaceChildren();$("detail-warnings").replaceChildren();
      $("chart-empty").hidden=false;
      $("chart-empty").textContent="Graf se načte po přihlášení.";
      drawChart();stats();renderTable();progress(0,1);
      $("copy-tickers").disabled=true;$("export-txt").disabled=true;$("export-all").disabled=true;
      status("Odhlášeno ze všech aplikací StockTool.");
      notify("Zabezpečená relace byla ukončena.");
    }catch(e){notify(e.message,true);}
  }

  function bind(){
    $("year").textContent=String(new Date().getFullYear());
    $("scan-button").addEventListener("click",runScan);
    $("rescan-button").addEventListener("click",runScan);
    $("logout-button").addEventListener("click",logout);
    $("api-key").addEventListener("keydown",e=>{if(e.key==="Enter")runScan();});
    $("show-key").addEventListener("click",()=>{
      $("api-key").type=$("api-key").type==="password"?"text":"password";
    });
    for(const chip of document.querySelectorAll("[data-filter]")){
      chip.addEventListener("click",()=>{
        filter=chip.dataset.filter;
        for(const button of document.querySelectorAll("[data-filter]")){
          const active=chip===button;
          button.classList.toggle("active",active);
          button.setAttribute("aria-pressed",String(active));
        }
        page=0;renderTable();
      });
    }
    $("ticker-search").addEventListener("input",()=>{page=0;renderTable();});
    $("sort-mode").addEventListener("change",()=>{page=0;renderTable();});
    $("top-ten").addEventListener("change",()=>{page=0;renderTable();});
    $("prev-page").addEventListener("click",()=>{page=Math.max(0,page-1);renderTable();});
    $("next-page").addEventListener("click",()=>{page++;renderTable();});
    $("copy-tickers").addEventListener("click",copyTickers);
    $("export-txt").addEventListener("click",exportText);
    $("export-all").addEventListener("click",exportAll);
    if("ResizeObserver" in window){
      new ResizeObserver(drawChart).observe(document.querySelector(".detail-chart"));
    }else window.addEventListener("resize",drawChart);
    stats();renderTable();progress(0,1);
    restoreLogin();
  }
  document.addEventListener("DOMContentLoaded",bind);
})();
