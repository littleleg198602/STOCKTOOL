"use strict";
/**
 * StockTool Backtesting Engine v0.1
 * Live canonical scanner rules executed on server, batched across MT5 D1 files.
 * Credentials only as a one-time login header; no localStorage/sessionStorage.
 */
(() => {
  const $=id=>document.getElementById(id);
  const STRATEGIES={
    BUY:"BUY Scanner · LONG",
    SHORT:"SHORT Scanner · SHORT",
    PRESSURE_REVERSAL:"Market Pressure · obrat LONG",
    PRESSURE_CONTINUATION:"Market Pressure · pokračování SHORT"
  };
  const ORDER=Object.keys(STRATEGIES);
  const PAGE_SIZE=20;
  const N=new Intl.NumberFormat("cs-CZ",{maximumFractionDigits:2});
  const fmt=(v,suffix="")=>v==null||!Number.isFinite(Number(v))?"—":N.format(Number(v))+suffix;
  const dt=t=>{
    if(!t||!Number.isFinite(Number(t)))return "—";
    try{return new Date(Number(t)*1000).toISOString().slice(0,10);}
    catch{return "—";}
  };
  const numberPrice=v=>v==null||!Number.isFinite(Number(v))?"—":
    new Intl.NumberFormat("cs-CZ",{maximumFractionDigits:5}).format(Number(v));
  const colorFor=v=>v==null?"":Number(v)>=0?"positive":"negative";
  let signedIn=false,running=false,completed=false,aborter=null,cancelRequested=false;
  let rows=[],groups=[],currentKey="",costs={},scanOptions={},issues={};
  let pages={symbols:0,trades:0},notifyTimer=null;

  function toast(msg,error=false){
    const el=$("toast");
    el.textContent=msg;el.classList.toggle("error",error);el.classList.add("visible");
    clearTimeout(notifyTimer);
    notifyTimer=setTimeout(()=>el.classList.remove("visible"),4500);
  }
  function status(msg,error=false){
    $("connection-state").textContent=msg;
    $("connection-state").classList.toggle("is-error",error);
  }
  function showSignedIn(value){
    signedIn=value;
    $("login-controls").hidden=value;
    $("logout-button").disabled=!value;
  }
  async function restoreLogin(){
    try{
      const r=await fetch("../data-manager/api/session.php",{
        method:"GET",cache:"no-store",credentials:"same-origin"
      });
      const data=await r.json();
      if(r.ok&&data.ok&&data.authenticated){
        showSignedIn(true);
        status("Přihlášeno automaticky. Backtest můžeš spustit.");
      }else {
        showSignedIn(false);
        status("Při prvním použití zadej stávající API klíč. Příště si tě StockTool zapamatuje.");
      }
    }catch(e){
      showSignedIn(false);status("Nelze ověřit přihlášení: "+e.message,true);
    }
  }
  async function loginOnce(){
    const key=$("api-key").value.trim();
    if(key.length<32)throw Error("Vlož současný StockTool API klíč (jen při prvním přihlášení).");
    try{
      const r=await fetch("../data-manager/api/login.php",{
        method:"POST",credentials:"same-origin",cache:"no-store",
        headers:{"X-StockTool-Key":key,"Accept":"application/json"}
      });
      const data=await r.json();
      if(!r.ok||!data.ok||!data.authenticated)
        throw Error(r.status===401?"Nesprávný klíč.":"Server odmítl přihlášení (HTTP "+r.status+").");
      showSignedIn(true);status("Přihlášeno · společná zabezpečená relace StockTool.");
    }finally{$("api-key").value="";}
  }
  async function apiGet(url,signal){
    const r=await fetch(url,{
      method:"GET",credentials:"same-origin",cache:"no-store",signal,
      headers:{"Accept":"application/json"}
    });
    let data;
    try{data=await r.json();}
    catch{throw Error("Server nevrátil JSON – zkontroluj nasazení PHP.");}
    if(!r.ok||!data.ok){
      if(r.status===401) {
        showSignedIn(false);
        throw Error("Přihlášení vypršelo; zadej svůj klíč znovu.");
      }
      throw Error("Backtesting API HTTP "+r.status+" ("+String(data.error||"neznámá chyba")+").");
    }
    return data;
  }
  function readInputs(){
    const strategy=$("strategy").value;
    if(strategy!=="ALL"&&!ORDER.includes(strategy))throw Error("Neplatná strategie.");
    const horizons=[...document.querySelectorAll("input[name=horizon]:checked")]
      .map(x=>Number(x.value)).sort((a,b)=>a-b);
    if(!horizons.length)throw Error("Vyber alespoň jeden horizont.");
    if(horizons.some(x=>![1,5,10,20,60].includes(x)))throw Error("Neplatný horizont.");
    const values={};
    for(const id of ["commission","spread","slippage"]){
      const v=Number($(id).value);
      if(!Number.isFinite(v)||v<0||v>99||$(id).value.trim()==="")
        throw Error("Hodnota "+id+" musí být mezi 0 a 99 bps.");
      values[id]=Math.round(v*100)/100;
    }
    return {strategy,horizons,costs:values};
  }
  function setProgress(done,total){
    const pct=total<=0?(completed?100:0):Math.min(100,Math.round(done/total*100));
    $("progress-bar").style.width=pct+"%";
    $("progress-number").textContent=pct+" %";
    $("progress-label").textContent=running?
      "Zpracováno "+fmt(done)+" / "+fmt(total)+" D1 datasetů":
      completed?"Všechny dávky dokončeny.":cancelRequested?
      "Výpočet zastaven; výsledky nejsou úplné.":"Čeká na spuštění.";
  }
  function setRunning(value){
    running=value;
    $("scan-button").disabled=value;
    $("stop-button").disabled=!value;
    $("logout-button").disabled=!signedIn||value;
    for(const id of ["strategy","commission","spread","slippage"])
      $(id).disabled=value;
    for(const checkbox of document.querySelectorAll("input[name=horizon]"))
      checkbox.disabled=value;
  }
  async function start(){
    if(running)return;
    try{scanOptions=readInputs();}
    catch(e){return toast(e.message,true);}
    if(location.protocol!=="https:")return toast("Backtest vyžaduje HTTPS.",true);
    if(!signedIn){
      try{await loginOnce();}
      catch(e){status(e.message,true);return toast(e.message,true);}
    }
    cancelRequested=false;completed=false;rows=[];groups=[];currentKey="";
    issues={read:0,bad:0,short:0,stale:0};
    costs=scanOptions.costs;
    pages={symbols:0,trades:0};
    aborter=new AbortController();
    setRunning(true);
    $("export-report").disabled=true;$("export-csv").disabled=true;$("copy-tickers").disabled=true;
    $("run-status").textContent="Běží historický výpočet na FORPSI…";
    $("chart-empty").hidden=false;
    $("chart-empty").textContent="Po prvním výpočtu se zobrazí graf.";
    ["stat-symbols","stat-trades","stat-winrate","stat-avg","stat-pf","stat-dd"].forEach(id=>$(id).textContent="—");
    $("coverage-note").textContent="Načítám soubory";
    $("summary-body").replaceChildren();$("symbols-body").replaceChildren();$("trades-body").replaceChildren();
    let offset=0,total=1;
    setProgress(0,1);
    try{
      const params=new URLSearchParams({
        strategy:scanOptions.strategy,
        horizons:scanOptions.horizons.join(","),
        commission:String(costs.commission),spread:String(costs.spread),
        slippage:String(costs.slippage)
      });
      const batchSize=scanOptions.strategy==="ALL"?4:8;
      do{
        if(cancelRequested)throw new DOMException("Výpočet zastaven","AbortError");
        params.set("offset",String(offset));
        params.set("limit",String(batchSize));
        const batch=await apiGet("./api/run.php?"+params.toString(),aborter.signal);
        const advance=Number(batch.scanned)||0;
        total=Math.max(0,Number(batch.total)||0);
        if(offset<total&&advance===0)throw Error("Server nepostupuje ve zpracování dávky.");
        if(!Array.isArray(batch.rows))throw Error("API nevrátilo platné výsledky.");
        rows.push(...batch.rows);
        issues.read+=Number(batch.read_errors)||0;
        for(const row of batch.rows){
          if(row.status==="bad_data")issues.bad++;
          if(row.stale)issues.stale++;
          for(const g of row.groups||[])if(g.status==="too_short")issues.short++;
        }
        offset+=advance;
        setProgress(offset,total);
        $("run-status").textContent="Zpracováno "+fmt(offset)+" / "+fmt(total)+" D1 datasetů";
      }while(offset<total);
      completed=true;
      rebuildGroups(true);
      $("run-status").textContent="Dokončeno: "+fmt(offset)+" datasetů"+
        (issues.read?" · nečitelné "+issues.read:"")+
        (issues.bad?" · vadná historie "+issues.bad:"")+
        (issues.short?" · nedostatek historie "+issues.short:"");
      $("export-report").disabled=false;
      $("export-csv").disabled=false;
      $("copy-tickers").disabled=false;
      toast("Backtest dokončen. Výsledky, modelované náklady a jednotlivé obchody jsou připravené.");
    }catch(e){
      rebuildGroups(false);
      if(e.name==="AbortError"||cancelRequested){
        cancelRequested=true;
        $("run-status").textContent="ZASTAVENO: výsledky pouze částečné – "+rows.length+" datasetů.";
        toast("Výpočet zastaven; výsledky jsou jen částečné.",true);
      }else{
        $("run-status").textContent="CHYBA: "+e.message+" · data jsou pouze částečná.";
        toast(e.message,true);
      }
    }finally{
      setRunning(false);
      setProgress(offset,total);
      aborter=null;
    }
  }
  function cancel(){
    if(!running)return;
    cancelRequested=true;
    if(aborter)aborter.abort();
  }

  function metric(trades){
    const n=trades.length;
    if(!n)return {count:0,winrate:null,avg:null,median:null,pf:null,maxdd:null,
      best:null,worst:null,curve:[],symbols:0};
    const returns=trades.map(x=>Number(x.net_pct));
    const sum=returns.reduce((a,b)=>a+b,0);
    const sorted=[...returns].sort((a,b)=>a-b);
    const win=returns.filter(x=>x>0);
    const loss=returns.filter(x=>x<0);
    const gains=win.reduce((a,b)=>a+b,0);
    const losses=Math.abs(loss.reduce((a,b)=>a+b,0));
    const mid=n>>1;
    const med=n%2?sorted[mid]:(sorted[mid-1]+sorted[mid])/2;
    // This is an artificial closed-trade index, NOT a portfolio equity curve.
    // Trades exiting on the same day are equally weighted, then compounded
    // by exit cohort (there is no invested-capital or margin model).
    const exitDay=new Map();
    for(const t of trades){
      const key=Number(t.exit_time);
      const list=exitDay.get(key)||[];
      list.push(Number(t.net_pct));exitDay.set(key,list);
    }
    const curve=[{t:0,value:100}],dates=[...exitDay.keys()].sort((a,b)=>a-b);
    let eq=100,peak=100,dd=0;
    for(const day of dates){
      const values=exitDay.get(day);
      const average=values.reduce((a,b)=>a+b,0)/values.length;
      eq=Math.max(0,eq*(1+average/100));
      peak=Math.max(peak,eq);
      if(peak>0)dd=Math.max(dd,(peak-eq)/peak*100);
      curve.push({t:day,value:eq});
    }
    return {
      count:n,winrate:win.length/n*100,avg:sum/n,median:med,
      // No losers => undefined: do not show false confidence of "infinite" PF.
      pf:losses>0?gains/losses:null,maxdd:dd,
      best:sorted[n-1],worst:sorted[0],curve,
      symbols:new Set(trades.map(t=>t.symbol)).size
    };
  }
  function rebuildGroups(markComplete){
    const map=new Map();
    for(const symbolResult of rows){
      for(const raw of symbolResult.groups||[]){
        const key=raw.strategy+"|"+raw.horizon;
        if(!map.has(key))map.set(key,{strategy:raw.strategy,horizon:Number(raw.horizon),
          trades:[],seen:0,unclosed:0,overlap:0,tooShort:0,required:0});
        const g=map.get(key);
        if(raw.status==="too_short") {
          g.tooShort++;
          g.required=Math.max(g.required,Number(raw.required)||0);
          continue;
        }
        if(raw.status!=="ok")continue;
        g.trades.push(...(raw.trades||[]));
        g.seen+=Number(raw.signals_seen||0);
        g.unclosed+=Number(raw.unclosed||0);
        g.overlap+=Number(raw.overlap_skipped||0);
      }
    }
    // Show all selected combinations, including those with zero completed trades.
    const available=scanOptions.strategy==="ALL"?ORDER:[scanOptions.strategy];
    groups=[];
    for(const strategy of available){
      for(const horizon of scanOptions.horizons||[]){
        const key=strategy+"|"+horizon;
        const g=map.get(key)||{strategy,horizon,trades:[],seen:0,unclosed:0,overlap:0,tooShort:0,required:0};
        g.stats=metric(g.trades);
        groups.push(g);
      }
    }
    if(!currentKey&&groups.length)currentKey=groupKey(groups[0]);
    renderSummary();
    populateSelectors();
    if(markComplete){
      $("stat-symbols").textContent=fmt(rows.length);
      $("coverage-note").textContent="Vadná historie: "+issues.bad+" · krátká: "+issues.short;
    }else{
      $("stat-symbols").textContent=fmt(rows.length);
      $("coverage-note").textContent="POUZE ČÁSTEČNÁ DATA";
    }
    showGroup();
  }
  function groupKey(g){return g.strategy+"|"+g.horizon;}
  function selectedGroup(){
    return groups.find(g=>groupKey(g)===currentKey)||groups[0]||null;
  }
  function setCell(tr,value,cls=""){
    const td=document.createElement("td");
    td.textContent=value;
    if(cls)td.className=cls;
    tr.append(td);
    return td;
  }
  function renderSummary(){
    const body=$("summary-body");body.replaceChildren();
    if(!groups.length){
      const tr=document.createElement("tr"),td=setCell(tr,"Zatím bez výsledků.");
      td.colSpan=8;td.className="empty-cell";body.append(tr);return;
    }
    for(const g of groups){
      const m=g.stats,tr=document.createElement("tr");
      if(groupKey(g)===currentKey)tr.className="selected-row";
      setCell(tr,STRATEGIES[g.strategy]||g.strategy);
      setCell(tr,g.horizon+" D1");
      setCell(tr,fmt(m.count));
      setCell(tr,fmt(m.symbols));
      setCell(tr,fmt(m.winrate,"%"));
      setCell(tr,fmt(m.avg,"%"),colorFor(m.avg));
      setCell(tr,m.pf==null?"—":fmt(m.pf,"×"));
      setCell(tr,fmt(m.maxdd,"%"),"negative");
      tr.addEventListener("click",()=>{currentKey=groupKey(g);pages={symbols:0,trades:0};populateSelectors();renderSummary();showGroup();});
      body.append(tr);
    }
    $("summary-note").textContent=(completed?"Kompletní načtení.":"Částečný/neúplný výpočet! ")+
      " Profit factor je poměr součtů kladných/záporných netto výsledků. Max DD je jen na syntetické křivce uzavřených obchodů, nikoli na obchodovatelném portfoliu.";
  }
  function populateSelectors(){
    const strat=$("result-strategy"),hor=$("result-horizon");
    const selected=selectedGroup();
    strat.replaceChildren();hor.replaceChildren();
    const strategies=[...new Set(groups.map(g=>g.strategy))];
    for(const s of strategies){
      const el=document.createElement("option");
      el.value=s;el.textContent=STRATEGIES[s]||s;strat.append(el);
    }
    if(selected)strat.value=selected.strategy;
    for(const group of groups.filter(g=>g.strategy===strat.value)){
      const el=document.createElement("option");
      el.value=String(group.horizon);el.textContent=group.horizon+" D1";hor.append(el);
    }
    if(selected)hor.value=String(selected.horizon);
    strat.disabled=!groups.length;
    hor.disabled=!groups.length;
  }
  function switchStrategy(){
    const strat=$("result-strategy").value;
    const before=currentKey.split("|")[1];
    const next=groups.find(g=>g.strategy===strat&&String(g.horizon)===before)
      ||groups.find(g=>g.strategy===strat);
    if(next)currentKey=groupKey(next);
    pages={symbols:0,trades:0};populateSelectors();renderSummary();showGroup();
  }
  function switchHorizon(){
    currentKey=$("result-strategy").value+"|"+$("result-horizon").value;
    pages={symbols:0,trades:0};renderSummary();showGroup();
  }
  function showGroup(){
    const g=selectedGroup(),m=g?.stats||metric([]);
    $("stat-trades").textContent=fmt(m.count);
    $("stat-winrate").textContent=fmt(m.winrate,"%");
    $("stat-avg").textContent=fmt(m.avg,"%");
    $("stat-pf").textContent=fmt(m.pf,"×");
    $("stat-dd").textContent=fmt(m.maxdd,"%");
    $("metric-median").textContent=fmt(m.median,"%");
    $("metric-best").textContent=fmt(m.best,"%");
    $("metric-worst").textContent=fmt(m.worst,"%");
    $("metric-unclosed").textContent=g?fmt(g.unclosed):"—";
    const count=m.count||0;
    $("risk-warning").textContent=!completed
      ?"Výsledky jsou ČÁSTEČNÉ a nejsou vhodné k porovnávání strategií."
      :count===0 && g && g.tooShort>0
      ?"Žádné uzavřené obchody. "+g.tooShort+" datasetů nemá minimálně "+g.required+
        " D1 svíček pro tento horizont. Nulový počet není výnos 0 %."
      :count===0
      ?"Pro tento scénář není žádný uzavřený obchod. Neznamená to úspěch ani selhání strategie."
      :count<30
      ?"Pozor: jen "+count+" uzavřených obchodů. Tento vzorek je příliš malý pro spolehlivé závěry."
      :"Vypočteno "+count+" uzavřených obchodů. Survivorship bias, modelované náklady a překryvy stále omezují spolehlivost.";
    drawCurve(m.curve);
    renderSymbols();renderTrades();
  }
  function drawCurve(curve){
    const canvas=$("equity-chart"),ctx=canvas.getContext("2d");
    if(!ctx)return;
    const w=Math.max(240,canvas.clientWidth||600);
    const h=Math.max(170,canvas.clientHeight||300);
    const dpr=Math.min(window.devicePixelRatio||1,2.5);
    canvas.width=Math.ceil(w*dpr);canvas.height=Math.ceil(h*dpr);
    ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.clearRect(0,0,w,h);
    if(!curve||curve.length<2){
      $("chart-empty").hidden=false;
      $("chart-period").textContent="Nedostatek uzavřených obchodů";
      return;
    }
    $("chart-empty").hidden=true;
    const points=curve.slice(1);
    const values=curve.map(p=>p.value);
    let bottom=Math.min(100,...values),top=Math.max(100,...values);
    const pad=Math.max((top-bottom)*.1,1);
    bottom-=pad;top+=pad;
    const L=43,R=20,T=20,B=34;
    const x=i=>L+i/(curve.length-1)*(w-L-R);
    const y=v=>T+(top-v)/(top-bottom)*(h-T-B);
    ctx.lineWidth=1;ctx.strokeStyle="#294257";
    for(let i=0;i<5;i++){
      const yy=T+(h-T-B)*i/4;
      ctx.beginPath();ctx.moveTo(L,yy);ctx.lineTo(w-R,yy);ctx.stroke();
      const val=top-(top-bottom)*i/4;
      ctx.fillStyle="#829fac";ctx.font="10px ui-monospace,monospace";
      ctx.textBaseline="middle";ctx.fillText(fmt(val),4,yy);
    }
    ctx.strokeStyle="#6c7480";ctx.setLineDash([4,4]);
    ctx.beginPath();ctx.moveTo(L,y(100));ctx.lineTo(w-R,y(100));ctx.stroke();ctx.setLineDash([]);
    const gain=curve[curve.length-1].value>=100;
    const stroke=gain?"#73e0bf":"#ffa4a4";
    ctx.beginPath();
    curve.forEach((point,i)=>{if(i===0)ctx.moveTo(x(i),y(point.value));else ctx.lineTo(x(i),y(point.value));});
    ctx.strokeStyle=stroke;ctx.lineWidth=2.5;ctx.stroke();
    ctx.fillStyle=stroke;
    ctx.beginPath();ctx.arc(x(curve.length-1),y(curve[curve.length-1].value),3,0,Math.PI*2);ctx.fill();
    ctx.font="10px ui-monospace,monospace";ctx.fillStyle="#9bb5c1";ctx.textBaseline="bottom";
    ctx.fillText(dt(points[0].t),L,h-5);
    const last=dt(points[points.length-1].t);
    ctx.fillText(last,Math.max(L,w-R-ctx.measureText(last).width),h-5);
    $("chart-period").textContent=dt(points[0].t)+" — "+last;
  }
  function symbolRows(){
    const group=selectedGroup();if(!group)return [];
    const map=new Map();
    for(const t of group.trades){
      const list=map.get(t.symbol)||[];
      list.push(t);map.set(t.symbol,list);
    }
    const term=$("ticker-search").value.trim().toUpperCase();
    const result=[...map].filter(([symbol])=>symbol.toUpperCase().includes(term))
      .map(([symbol,ts])=>({symbol,...metric(ts),last:Math.max(...ts.map(x=>x.exit_time))}));
    const sort=$("symbol-sort").value;
    result.sort((a,b)=>{
      if(sort==="ticker")return a.symbol.localeCompare(b.symbol);
      if(sort==="avg")return (b.avg??-1e10)-(a.avg??-1e10)||a.symbol.localeCompare(b.symbol);
      if(sort==="winrate")return (b.winrate??-1e10)-(a.winrate??-1e10)||a.symbol.localeCompare(b.symbol);
      return b.count-a.count||a.symbol.localeCompare(b.symbol);
    });
    return result;
  }
  function renderSymbols(){
    const list=symbolRows(),body=$("symbols-body");
    const pageCount=Math.max(1,Math.ceil(list.length/PAGE_SIZE));
    pages.symbols=Math.min(pages.symbols,pageCount-1);
    body.replaceChildren();
    if(!list.length){const tr=document.createElement("tr");
      const td=setCell(tr,"Žádné uzavřené obchody nebo odpovídající tickery.");
      td.colSpan=7;td.className="empty-cell";body.append(tr);
    }else for(const item of list.slice(pages.symbols*PAGE_SIZE,(pages.symbols+1)*PAGE_SIZE)){
      const tr=document.createElement("tr");
      setCell(tr,item.symbol);
      setCell(tr,fmt(item.count));
      setCell(tr,fmt(item.winrate,"%"));
      setCell(tr,fmt(item.avg,"%"),colorFor(item.avg));
      setCell(tr,fmt(item.best,"%"),colorFor(item.best));
      setCell(tr,fmt(item.worst,"%"),colorFor(item.worst));
      setCell(tr,dt(item.last));body.append(tr);
    }
    $("symbols-count").textContent=fmt(list.length)+" tickerů · filtrovaný scénář";
    $("symbols-page").textContent=list.length?(pages.symbols+1)+" / "+pageCount:"—";
    $("symbols-prev").disabled=pages.symbols===0;
    $("symbols-next").disabled=pages.symbols>=pageCount-1;
  }
  function sortedTrades(){
    const g=selectedGroup();
    if(!g)return [];
    return [...g.trades].sort((a,b)=>
      Number(b.exit_time)-Number(a.exit_time)||a.symbol.localeCompare(b.symbol));
  }
  function renderTrades(){
    const list=sortedTrades(),body=$("trades-body");
    const pageCount=Math.max(1,Math.ceil(list.length/PAGE_SIZE));
    pages.trades=Math.min(pages.trades,pageCount-1);
    body.replaceChildren();
    if(!list.length){const tr=document.createElement("tr");
      const td=setCell(tr,"Pro vybranou kombinaci nejsou žádné uzavřené obchody.");
      td.colSpan=8;td.className="empty-cell";body.append(tr);
    }else for(const t of list.slice(pages.trades*PAGE_SIZE,(pages.trades+1)*PAGE_SIZE)){
      const tr=document.createElement("tr");
      setCell(tr,t.symbol);
      setCell(tr,dt(t.signal_time));
      setCell(tr,dt(t.entry_time)+" · "+numberPrice(t.entry));
      setCell(tr,dt(t.exit_time)+" · "+numberPrice(t.exit));
      setCell(tr,t.horizon+" D1");
      setCell(tr,fmt(t.gross_pct,"%"),colorFor(t.gross_pct));
      setCell(tr,fmt(t.net_pct,"%"),colorFor(t.net_pct));
      setCell(tr,t.setup);
      body.append(tr);
    }
    $("trades-count").textContent=fmt(list.length)+" uzavřených obchodů";
    $("trades-page").textContent=list.length?(pages.trades+1)+" / "+pageCount:"—";
    $("trades-prev").disabled=pages.trades===0;
    $("trades-next").disabled=pages.trades>=pageCount-1;
  }
  function allTrades(){
    return groups.flatMap(g=>g.trades);
  }
  function makeDownload(content,filename,type){
    const blob=new Blob(["\uFEFF",content],{type});
    const url=URL.createObjectURL(blob);
    const a=document.createElement("a");a.href=url;a.download=filename;
    document.body.append(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),5000);
  }
  function exportReport(){
    if(!completed)return toast("TXT lze exportovat až po dokončení backtestu.",true);
    const lines=[
      "STOCKTOOL BACKTESTING ENGINE v0.1",
      "Vytvoreno: "+new Date().toISOString(),
      "Zdroj: Darwinex MT5 D1, canonical BUY/SHORT/Market Pressure pravidla.",
      "Signal na CLOSE, vstup na dalsim D1 OPEN, vystup OPEN po N D1.",
      "Backtest zahrnuje pouze soucasne ulozene tickery, bez delistovanych akcii.",
      "Gross a NET zahrnuji ceny OPEN; NET modeluje komise, spread, slippage.",
      "SHORT: borrow fee, margin, shortability ani financovani nejsou modelovany.",
      "DD: synteticka posloupnost vysledku, nikoliv realne portfolio.",
      "Naklady bps: komise / strana "+costs.commission+"; cely spread "+costs.spread+
        "; slippage / strana "+costs.slippage,
      "Analyzovano: "+rows.length+" datasetu; nevalidni: "+issues.bad+
        "; nekompletni historie/skupiny: "+issues.short+"; chyby cteni: "+issues.read,
      ""
    ];
    for(const g of groups){
      const m=g.stats;
      lines.push("==== "+(STRATEGIES[g.strategy]||g.strategy)+" / "+g.horizon+" D1 ====");
      lines.push("Obchody: "+m.count+" | tickeru: "+m.symbols+
        " | win rate: "+fmt(m.winrate,"%")+" | prumer NET: "+fmt(m.avg,"%")+
        " | median: "+fmt(m.median,"%")+" | PF: "+fmt(m.pf,"x")+
        " | max DD synteticke krivky: "+fmt(m.maxdd,"%"));
      lines.push("Signalu: "+g.seen+" | bez dosud dostupneho vystupu: "+g.unclosed+
        " | prekryvajici se vstupy preskoceny: "+g.overlap);
      const symbols=[...new Set(g.trades.map(t=>t.symbol))].sort();
      lines.push("TICKERY PRO MT5: "+(symbols.length?symbols.join(","):"ZADNE"));
      lines.push("");
    }
    makeDownload(lines.join("\r\n")+"\r\n",
      "StockTool_Backtesting_"+new Date().toISOString().slice(0,10)+".txt",
      "text/plain;charset=utf-8");
    toast("Souhrnný TXT report stažen.");
  }
  function exportCSV(){
    if(!completed)return toast("CSV lze exportovat až po dokončení backtestu.",true);
    const fields=["symbol","strategy","setup","horizon","side","signal_time",
      "entry_time","exit_time","entry","exit","gross_pct","net_pct"];
    const quote=value=>{
      const s=String(value??"");
      return '"'+s.replace(/"/g,'""')+'"';
    };
    const lines=[fields.join(";")];
    for(const t of allTrades()){
      lines.push(fields.map(f=>quote(t[f])).join(";"));
    }
    makeDownload(lines.join("\r\n")+"\r\n",
      "StockTool_Backtesting_Trades_"+new Date().toISOString().slice(0,10)+".csv",
      "text/csv;charset=utf-8");
    toast("CSV obsahuje "+fmt(allTrades().length)+" historických obchodů.");
  }
  async function copyTickers(){
    if(!completed)return toast("Nejdřív dokonči backtest.",true);
    const g=selectedGroup(),line=g?[...new Set(g.trades.map(t=>t.symbol))].sort().join(","):"";
    if(!line)return toast("Tento scénář nemá žádné obchodované tickery.",true);
    try{await navigator.clipboard.writeText(line);toast("Tickery zkopírovány v jednom řádku pro MT5.");}
    catch{toast("Zkopírování selhalo. Použij TXT report.",true);}
  }
  async function logout(){
    if(running)return toast("Nejdřív zastav výpočet.",true);
    try{
      const r=await fetch("../data-manager/api/logout.php",{
        method:"POST",credentials:"same-origin",cache:"no-store"
      });
      if(!r.ok)throw Error("Odhlášení se na serveru nezdařilo.");
      showSignedIn(false);
      rows=[];groups=[];completed=false;currentKey="";
      $("export-report").disabled=true;$("export-csv").disabled=true;$("copy-tickers").disabled=true;
      $("summary-body").replaceChildren();$("symbols-body").replaceChildren();$("trades-body").replaceChildren();
      showGroup();setProgress(0,1);
      status("Odhlášeno ze všech StockTool aplikací.");
      toast("Odhlášeno.");
    }catch(e){toast(e.message,true);}
  }
  function bind(){
    $("year").textContent=String(new Date().getFullYear());
    $("scan-button").addEventListener("click",start);
    $("stop-button").addEventListener("click",cancel);
    $("logout-button").addEventListener("click",logout);
    $("api-key").addEventListener("keydown",e=>{if(e.key==="Enter")start();});
    $("show-key").addEventListener("click",()=>{
      $("api-key").type=$("api-key").type==="password"?"text":"password";
    });
    $("result-strategy").addEventListener("change",switchStrategy);
    $("result-horizon").addEventListener("change",switchHorizon);
    $("ticker-search").addEventListener("input",()=>{pages.symbols=0;renderSymbols();});
    $("symbol-sort").addEventListener("change",()=>{pages.symbols=0;renderSymbols();});
    $("symbols-prev").addEventListener("click",()=>{pages.symbols=Math.max(0,pages.symbols-1);renderSymbols();});
    $("symbols-next").addEventListener("click",()=>{pages.symbols++;renderSymbols();});
    $("trades-prev").addEventListener("click",()=>{pages.trades=Math.max(0,pages.trades-1);renderTrades();});
    $("trades-next").addEventListener("click",()=>{pages.trades++;renderTrades();});
    $("export-report").addEventListener("click",exportReport);
    $("export-csv").addEventListener("click",exportCSV);
    $("copy-tickers").addEventListener("click",copyTickers);
    if("ResizeObserver" in window)
      new ResizeObserver(()=>drawCurve(selectedGroup()?.stats?.curve||[]))
        .observe(document.querySelector(".equity-chart"));
    else window.addEventListener("resize",()=>drawCurve(selectedGroup()?.stats?.curve||[]));
    restoreLogin();
  }
  document.addEventListener("DOMContentLoaded",bind);
})();
