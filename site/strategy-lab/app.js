"use strict";
/* StockTool Strategy Lab v0.1 – browser-only research; no trading functions.
 * localStorage contains ONLY strategy configurations, never API credentials.
 */
(() => {
  const E=window.StockToolStrategyEngine;
  const $=id=>document.getElementById(id);
  const fm=new Intl.NumberFormat("cs-CZ",{maximumFractionDigits:2});
  const fmt=(v,u="")=>v===null||v===undefined||!Number.isFinite(Number(v))?"—":fm.format(Number(v))+u;
  const date=t=>{try{return t?new Date(Number(t)*1000).toISOString().slice(0,10):"—";}catch{return"—";}};
  const STORAGE="stocktool_strategy_lab_market_bank_v1";
  const defaultConfig={
    name:"RSI Market Pullback",timeframe:"D1",side:"LONG",join:"AND",exitJoin:"AND",
    entry:[{type:"rsi_below",period:14,value:65},{type:"close_above_sma",period:50,value:0}],
    exit:[{type:"rsi_above",period:14,value:62}],
    horizon:10,stopLoss:5,takeProfit:10,commission:1,spread:5,slippage:2,oos:30
  };
  let entryRules=[],exitRules=[],bank=[],generated=[],lastResult=null,marketBars=null,marketContext=null;
  let dataSymbol="",dataTimeframe="",signedIn=false,catalog=[],catalogEntries=[],currentTab="builder",isGenerating=false,genCancel=false,toastTimer=null,genProgress=0;

  function alertUser(text,error=false){
    const el=$("toast");el.textContent=text;
    el.classList.toggle("error",error);el.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer=setTimeout(()=>el.classList.remove("visible"),4300);
  }
  function setConnection(message,error=false){
    const el=$("connection-status");el.textContent=message;el.classList.toggle("error",error);
  }
  function setDataState(message){$("data-state").textContent=message;}
  function setStatus(message){$("builder-status").textContent=message;}
  function make(tag,props={},text=""){
    const el=document.createElement(tag);
    for(const [k,v] of Object.entries(props)){
      if(k==="class")el.className=v;
      else if(k==="type")el.type=v;
      else if(k==="title")el.title=v;
      else if(k==="value")el.value=v;
      else el.setAttribute(k,v);
    }
    if(text!=="")el.textContent=text;
    return el;
  }
  function button(label,click,cls="outline-btn tiny"){
    const b=make("button",{"class":cls,"type":"button"},label);
    b.addEventListener("click",click);return b;
  }
  function switchTab(name){
    if(!["builder","generator","databank","robustness"].includes(name))return;
    currentTab=name;
    for(const el of document.querySelectorAll(".tab-page"))el.classList.toggle("active",el.id==="tab-"+name);
    for(const el of document.querySelectorAll(".nav-item[data-tab]")){
      const active=el.dataset.tab===name;
      el.classList.toggle("active",active);
      el.setAttribute("aria-current",active?"page":"false");
    }
    if(name==="databank")renderBank();
    if(name==="robustness"&&lastResult){
      $("robustness-note").textContent="Připravená strategie: "+lastResult.config.name+
        " ("+lastResult.trades.length+" obchodů).";
    }
  }

  function ruleNeedsPeriod(type){return !["green_candle","red_candle"].includes(type);}
  function ruleNeedsValue(type){return ["rsi_below","rsi_above","sma_cross_up","sma_cross_down",
    "roc_above","roc_below","tick_spike"].includes(type);}
  function ruleValueLabel(type){return type.startsWith("sma_cross")?"SMA2":type==="tick_spike"?"Násobek":"Hodnota";}
  function buildRule(rule,where,index) {
    const row=make("div",{"class":"rule-row"});
    const choose=make("label",{"class":"rule-name"},"Indikátor / podmínka");
    const select=make("select",{"aria-label":"Typ pravidla"});
    for(const [id,info]of Object.entries(E.RULES)){
      const opt=make("option",{"value":id},info.name);
      select.append(opt);
    }
    select.value=rule.type;
    select.addEventListener("change",()=>{
      const base=E.RULES[select.value];
      where[index]={type:select.value,period:base.period,value:base.value};
      drawRules();
    });
    choose.append(select);
    const pWrap=make("label",{"class":"rule-name"},"Perioda");
    const p=make("input",{type:"number",min:"1",max:"250",step:"1",value:String(rule.period),"aria-label":"Perioda pravidla"});
    p.disabled=!ruleNeedsPeriod(rule.type);
    p.addEventListener("change",()=>{
      const v=Number(p.value);
      if(Number.isInteger(v)&&v>=1&&v<=250)where[index].period=v;
      else{p.value=String(where[index].period);alertUser("Perioda musí být 1–250.",true);}
    });
    pWrap.append(p);
    const vWrap=make("label",{"class":"rule-name"},ruleValueLabel(rule.type));
    const val=make("input",{type:"number",step:"0.1",value:String(rule.value),"aria-label":"Hodnota pravidla"});
    val.disabled=!ruleNeedsValue(rule.type);
    val.addEventListener("change",()=>{
      const v=Number(val.value);
      if(Number.isFinite(v)&&Math.abs(v)<=1000)where[index].value=v;
      else{val.value=String(where[index].value);alertUser("Hodnota musí být v rozsahu -1000 až 1000.",true);}
    });
    vWrap.append(val);
    const remove=button("×",()=>{where.splice(index,1);drawRules();},"remove-rule");
    remove.setAttribute("aria-label","Odebrat pravidlo");
    row.append(choose,pWrap,vWrap,remove);
    return row;
  }
  function drawRules(){
    for(const [id,arr]of [["entry-rules",entryRules],["exit-rules",exitRules]]){
      const box=$(id);box.replaceChildren();
      if(!arr.length){
        box.append(make("div",{"class":"rule-hint"},id==="entry-rules"?
          "Přidej minimálně jednu podmínku vstupu.":"Žádná podmínka – rozhodne SL/TP nebo maximální doba držení."));
      }else arr.forEach((rule,i)=>box.append(buildRule(rule,arr,i)));
    }
    $("entry-add").disabled=entryRules.length>=5;
    $("exit-add").disabled=exitRules.length>=5;
  }
  function putConfig(config){
    const c=E.config(config);
    $("strategy-name").value=c.name;$("side").value=c.side;
    $("timeframe").value=c.timeframe;
    $("entry-join").value=c.join;$("exit-join").value=c.exitJoin;
    $("horizon").value=String(c.horizon);
    $("stop-loss").value=String(c.stopLoss);$("take-profit").value=String(c.takeProfit);
    $("commission").value=String(c.commission);$("spread").value=String(c.spread);
    $("slippage").value=String(c.slippage);$("oos").value=String(c.oos);
    entryRules=c.entry.map(r=>({...r}));exitRules=c.exit.map(r=>({...r}));
    drawRules();
  }
  function getConfig(){
    return E.config({
      name:$("strategy-name").value,side:$("side").value,
      join:$("entry-join").value,exitJoin:$("exit-join").value,
      horizon:Number($("horizon").value),stopLoss:Number($("stop-loss").value),
      takeProfit:Number($("take-profit").value),commission:Number($("commission").value),
      spread:Number($("spread").value),slippage:Number($("slippage").value),
      oos:Number($("oos").value),
      entry:entryRules,exit:exitRules,symbol:$("symbol").value.trim().toUpperCase(),timeframe:$("timeframe").value
    });
  }

  async function getJSON(url,options={}){
    const resp=await fetch(url,{method:"GET",credentials:"same-origin",cache:"no-store",
      headers:{"Accept":"application/json"},...options});
    let data;
    try{data=await resp.json();}catch{throw Error("Server nevrátil platnou JSON odpověď.");}
    if(!resp.ok||!data.ok){
      if(resp.status===401){
        signedIn=false;$("login-controls").hidden=false;
        throw Error("Přihlášení vypršelo. Vlož stávající API klíč.");
      }
      throw Error("Data Manager API: "+(data.error||resp.status));
    }
    return data;
  }
  async function loginOnce(){
    const key=$("api-key").value.trim();
    if(key.length<32)throw Error("Při prvním přihlášení je potřeba současný StockTool API klíč.");
    try{
      const resp=await fetch("../data-manager/api/login.php",{
        method:"POST",credentials:"same-origin",cache:"no-store",
        headers:{"Accept":"application/json","X-StockTool-Key":key}
      });
      const data=await resp.json();
      if(!resp.ok||!data.ok||!data.authenticated)
        throw Error(resp.status===401?"Nesprávný klíč.":"Přihlášení selhalo (HTTP "+resp.status+").");
      signedIn=true;$("login-controls").hidden=true;
      setConnection("Přihlášeno · zabezpečená relace sdílená se StockTool aplikacemi.");
      await loadCatalog();
    }finally{$("api-key").value="";}
  }
  async function restoreLogin(){
    try{
      const resp=await fetch("../data-manager/api/session.php",{
        method:"GET",credentials:"same-origin",cache:"no-store"
      });
      const d=await resp.json();
      if(resp.ok&&d.ok&&d.authenticated){
        signedIn=true;$("login-controls").hidden=true;
        setConnection("Přihlášeno automaticky · společná StockTool relace.");
        await loadCatalog();
        const s=$("symbol").value.trim().toUpperCase();
        if(s&&catalog.includes(s))await loadData(true);
      }else{
        signedIn=false;$("login-controls").hidden=false;
        setConnection("Přihlas se jednou stávajícím klíčem. Příště už nebude potřeba.");
      }
    }catch(e){
      if(!signedIn){$("login-controls").hidden=false;setConnection("Ověření relace: "+e.message,true);}
      else setConnection(e.message,true);
    }
  }
  function availableForSymbol(symbol){
    return catalogEntries.filter(d=>String(d.symbol).toUpperCase()===symbol)
      .map(d=>String(d.timeframe).toUpperCase());
  }
  function syncTimeframeOptions(){
    const symbol=$("symbol").value.trim().toUpperCase();
    const available=availableForSymbol(symbol);
    const field=$("timeframe");
    for(const option of field.options)option.disabled=available.length>0&&!available.includes(option.value);
    if(available.length&&!available.includes(field.value)){
      field.value=["D1","H4","H1","W1"].find(tf=>available.includes(tf))||available[0];
    }
    return available;
  }
  async function loadCatalog(){
    if(!signedIn)return;
    const r=await getJSON("../market-data/api/datasets.php");
    catalogEntries=(r.datasets||[]).filter(d=>["H1","H4","D1","W1"].includes(String(d.timeframe).toUpperCase()));
    catalog=[...new Set(catalogEntries.map(d=>String(d.symbol).toUpperCase()))].sort();
    const datalist=$("symbols");datalist.replaceChildren();
    for(const symbol of catalog)datalist.append(make("option",{value:symbol}));
    const candidate=$("symbol").value.trim().toUpperCase();
    if(!candidate||!catalog.includes(candidate)){
      const priority=["US500","NAS100","GER40","XAUUSD","EURUSD","US30","JP225"];
      $("symbol").value=priority.find(sym=>catalog.includes(sym))||catalog[0]||"";
    }
    syncTimeframeOptions();
    setConnection("Přihlášeno · Market Data Manager obsahuje "+catalog.length+" instrumentů.");
    if(!catalog.length)setDataState("Market Data Manager zatím nemá žádná data. Nejdřív spusť import z druhého MT5.");
  }
  async function loadData(quiet=false){
    if(!signedIn){
      try{await loginOnce();}
      catch(e){setConnection(e.message,true);return alertUser(e.message,true);}
    }
    const requested=$("symbol").value.trim().toUpperCase();
    const tf=$("timeframe").value;
    if(!/^[A-Z0-9._:#@+-]{1,40}$/.test(requested))return alertUser("Zadej platný ticker z Market Data Manageru.",true);
    if(!["H1","H4","D1","W1"].includes(tf))return alertUser("Vyber platný interval.",true);
    if(catalogEntries.length && !catalogEntries.some(d=>
      String(d.symbol).toUpperCase()===requested && String(d.timeframe).toUpperCase()===tf)){
      return alertUser(requested+" nemá v Market Data Manageru dostupný interval "+tf+".",true);
    }
    const button=$("load-data");button.disabled=true;
    setDataState("Načítám "+requested+" / "+tf+"…");
    try{
      const payload=await getJSON("../market-data/api/candles.php?symbol="+
        encodeURIComponent(requested)+"&timeframe="+encodeURIComponent(tf)+"&limit=5000");
      const verified=E.verifyBars(payload.bars||[]);
      marketBars=verified;marketContext=E.context(verified);dataSymbol=requested;dataTimeframe=tf;
      lastResult=null;
      for(const id of ["m-trades","m-win","m-pf","m-net","m-dd","m-avg",
        "is-trades","is-win","is-pf","is-avg","oos-trades","oos-win","oos-pf","oos-avg"])$(id).textContent="—";
      $("download-trades").disabled=true;
      $("trade-rows").replaceChildren();
      drawChart();
      $("symbol").value=requested;
      $("bars-count").textContent=fmt(verified.length);
      $("bars-period").textContent=date(verified[0].t)+" — "+date(verified[verified.length-1].t);
      setDataState(requested+" / "+tf+" · "+verified.length+" svíček");
      setStatus("Historie "+requested+" / "+tf+" připravena k výpočtu.");
      try{localStorage.setItem("stocktool_strategy_lab_market_symbol_v1",requested);}catch{}
      if(!quiet)alertUser(requested+" / "+tf+": načteno "+verified.length+" svíček.");
    }catch(e){
      marketBars=null;marketContext=null;dataSymbol="";dataTimeframe="";
      $("bars-count").textContent="—";
      setDataState("Chyba načtení: "+e.message);
      alertUser(e.message,true);
    }finally{button.disabled=false;}
  }
  async function ensureData(){
    const desired=$("symbol").value.trim().toUpperCase();
    const selectedTimeframe=$("timeframe").value;
    if(!marketBars||dataSymbol!==desired||dataTimeframe!==selectedTimeframe)await loadData(true);
    if(!marketBars||dataSymbol!==desired||dataTimeframe!==selectedTimeframe)
      throw Error("Nejdřív musí být dostupné validní svíčky vybraného trhu a intervalu.");
  }

  function metric(id,v,u=""){const el=$(id);el.textContent=fmt(v,u);el.classList.toggle("positive",v!=null&&v>0&&["m-net","m-avg","is-avg","oos-avg"].includes(id));el.classList.toggle("negative",v!=null&&v<0);}
  function showResults(run){
    lastResult=run;
    for(const [id,val,unit]of [
      ["m-trades",run.all.trades],["m-win",run.all.winrate,"%"],
      ["m-pf",run.all.pf,"×"],["m-net",run.all.net,"%"],
      ["m-dd",run.all.dd,"%"],["m-avg",run.all.avg,"%"],
      ["is-trades",run.is.trades],["is-win",run.is.winrate,"%"],
      ["is-pf",run.is.pf,"×"],["is-avg",run.is.avg,"%"],
      ["oos-trades",run.oos.trades],["oos-win",run.oos.winrate,"%"],
      ["oos-pf",run.oos.pf,"×"],["oos-avg",run.oos.avg,"%"]
    ])metric(id,val,unit||"");
    $("split-is-text").textContent=(100-run.config.oos)+" % IN-SAMPLE";
    $("split-oos-text").textContent=run.config.oos+" % OUT-OF-SAMPLE";
    $("split-is-bar").style.width=(100-run.config.oos)+"%";
    $("validation-note").textContent="Hranice: "+date(run.split_time)+
      " · "+run.boundary+" obchody překročily hranici a nejsou v IS ani OOS."+
      (run.oos.trades<5?" OOS obsahuje méně než 5 obchodů: z výsledku nevyvozuj spolehlivou výhodu.":"");
    const tbody=$("trade-rows");tbody.replaceChildren();
    const shown=[...run.trades].reverse().slice(0,40);
    if(!shown.length){
      const tr=make("tr"),td=make("td",{colspan:"4","class":"empty"},"Žádné uzavřené obchody při zvolených pravidlech.");
      tr.append(td);tbody.append(tr);
    }else for(const t of shown){
      const tr=make("tr");
      for(const [str,cls]of [[date(t.entry_time),""],[date(t.exit_time),""],[t.reason,""],[fmt(t.net_pct,"%"),t.net_pct>=0?"positive":"negative"]]){
        tr.append(make("td",{"class":cls},str));
      }
      tbody.append(tr);
    }
    $("download-trades").disabled=!run.trades.length;
    $("rob-dd50").textContent="—";$("rob-dd95").textContent="—";
    $("rob-stress").textContent="—";$("rob-oos-count").textContent="—";
    $("robustness-note").textContent="Spusť robustness test aktuální strategie.";
    drawChart();
  }
  function drawChart(){
    const canvas=$("equity-chart"),ctx=canvas.getContext("2d");if(!ctx)return;
    const w=Math.max(210,canvas.clientWidth||610),h=Math.max(160,canvas.clientHeight||260);
    const dpr=Math.min(window.devicePixelRatio||1,2.5);
    canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);
    ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
    const curve=lastResult?.all?.curve||[];
    if(curve.length<2){$("chart-placeholder").hidden=false;return;}
    $("chart-placeholder").hidden=true;
    const values=curve.map(p=>p.eq);
    let min=Math.min(100,...values),max=Math.max(100,...values);
    const extra=Math.max((max-min)*.12,.4);min-=extra;max+=extra;
    const L=43,R=15,T=15,B=25;
    const x=i=>L+i/(curve.length-1)*(w-L-R);
    const y=v=>T+(max-v)/(max-min)*(h-T-B);
    ctx.lineWidth=1;ctx.strokeStyle="#274257";ctx.font="10px ui-monospace,monospace";
    for(let k=0;k<5;k++){
      const yy=T+(h-T-B)*k/4;
      ctx.beginPath();ctx.moveTo(L,yy);ctx.lineTo(w-R,yy);ctx.stroke();
      ctx.fillStyle="#799aaa";ctx.fillText(fmt(max-(max-min)*k/4),5,yy+3);
    }
    ctx.strokeStyle="#507061";ctx.setLineDash([4,4]);
    ctx.beginPath();ctx.moveTo(L,y(100));ctx.lineTo(w-R,y(100));ctx.stroke();ctx.setLineDash([]);
    const positive=curve[curve.length-1].eq>=100;
    ctx.strokeStyle=positive?"#62e4bf":"#ffa3aa";ctx.lineWidth=2.5;
    ctx.beginPath();curve.forEach((p,i)=>i?ctx.lineTo(x(i),y(p.eq)):ctx.moveTo(x(i),y(p.eq)));ctx.stroke();
    ctx.fillStyle=ctx.strokeStyle;
    ctx.beginPath();ctx.arc(x(curve.length-1),y(curve[curve.length-1].eq),3,0,Math.PI*2);ctx.fill();
    const splitIndex=curve.findIndex(p=>p.t>=lastResult.split_time);
    if(splitIndex>0){
      ctx.strokeStyle="#ffd092";ctx.lineWidth=1;ctx.setLineDash([5,5]);
      ctx.beginPath();ctx.moveTo(x(splitIndex),T);ctx.lineTo(x(splitIndex),h-B);ctx.stroke();ctx.setLineDash([]);
      ctx.fillStyle="#ffd092";ctx.fillText("OOS",Math.min(w-35,x(splitIndex)+4),T+12);
    }
    ctx.fillStyle="#92b6c4";ctx.fillText(date(curve[0].t),L,h-5);
    const last=date(curve[curve.length-1].t);
    ctx.fillText(last,Math.max(L,w-R-ctx.measureText(last).width),h-5);
  }
  async function runBacktest(){
    $("run-backtest").disabled=true;
    try{
      await ensureData();
      const c=getConfig();c.symbol=dataSymbol;
      const res=E.backtest(marketBars,c,marketContext);
      showResults(res);
      setStatus("Backtest hotov · "+res.trades.length+" uzavřených obchodů · OOS "+res.oos.trades+".");
      alertUser("Historický výpočet dokončen pro "+dataSymbol+".");
    }catch(e){setStatus(e.message);alertUser(e.message,true);}
    finally{$("run-backtest").disabled=false;}
  }
  function loadBank(){
    try{
      const raw=localStorage.getItem(STORAGE);
      const parsed=JSON.parse(raw||"[]");
      if(Array.isArray(parsed))bank=parsed.slice(0,100).filter(x=>x&&x.config);
    }catch{bank=[];}
    $("bank-count").textContent=String(bank.length);
  }
  function persistBank(){
    try{localStorage.setItem(STORAGE,JSON.stringify(bank));}
    catch{alertUser("Prohlížeč blokuje trvalé ukládání strategií.",true);}
    $("bank-count").textContent=String(bank.length);
  }
  function saveToBank(c,report=null){
    try{c=E.config(c);}catch(e){return alertUser(e.message,true);}
    const record={
      id:Date.now()+"_"+Math.random().toString(36).slice(2,8),
      added:new Date().toISOString(),symbol:c.symbol||"",
      config:c,
      snapshot:report?{is:report.is,oos:report.oos,trades:report.trades.length}:null
    };
    // Avoid storing full trade history in localStorage.
    if(record.snapshot){
      const {is:ins,oos:out}=record.snapshot;
      record.snapshot={is:{trades:ins.trades,pf:ins.pf,avg:ins.avg,winrate:ins.winrate},
        oos:{trades:out.trades,pf:out.pf,avg:out.avg,winrate:out.winrate},trades:record.snapshot.trades};
    }
    bank.unshift(record);bank=bank.slice(0,100);persistBank();renderBank();
    alertUser("Strategie uložená do Databank v tomto prohlížeči.");
  }
  function download(text,name,mime){
    const blob=new Blob(["\uFEFF",text],{type:mime});
    const url=URL.createObjectURL(blob);
    const a=make("a");a.href=url;a.download=name;
    document.body.append(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),2500);
  }
  function exportConfig(){
    try{
      const config=getConfig();
      download(JSON.stringify({app:"StockTool Strategy Lab",version:1,config},null,2),
        "StockTool_Strategy_"+config.name.replace(/[^A-Za-z0-9_-]/g,"_")+".json","application/json;charset=utf-8");
      alertUser("Konfigurace strategie exportovaná.");
    }catch(e){alertUser(e.message,true);}
  }
  function exportTrades(){
    if(!lastResult?.trades.length)return alertUser("Zatím žádné uzavřené obchody.",true);
    const columns=["signal_time","entry_time","exit_time","side","entry","exit","gross_pct","net_pct","reason"];
    const lines=[columns.join(";")];
    for(const t of lastResult.trades){
      lines.push(columns.map(k=>'"'+String(t[k]??"").replace(/"/g,'""')+'"').join(";"));
    }
    download(lines.join("\r\n")+"\r\n","StockTool_StrategyLab_Trades_"+dataSymbol+".csv","text/csv;charset=utf-8");
  }
  function renderBank(){
    const body=$("bank-results");body.replaceChildren();
    if(!bank.length){const tr=make("tr");tr.append(make("td",{"class":"empty",colspan:"7"},"Zatím nejsou uložené strategie."));body.append(tr);return;}
    bank.forEach(item=>{
      const tr=make("tr"),c=item.config,ss=item.snapshot;
      for(const text of [c.name+" ("+(item.symbol||"bez dat")+")",c.side,c.entry.length+" / "+c.join,
        fmt(ss?.is?.trades),fmt(ss?.is?.pf,"×"),fmt(ss?.oos?.pf,"×")])
        tr.append(make("td",{},text));
      const actions=make("td");
      actions.append(button("Otevřít",()=>{
        putConfig(c);if(item.symbol)$("symbol").value=item.symbol;
        lastResult=null;switchTab("builder");
        alertUser("Nastavení načteno. Pro aktuální čísla spusť backtest.");
      }),button("Smazat",()=>{
        bank=bank.filter(x=>x.id!==item.id);persistBank();renderBank();
      },"danger"));
      tr.append(actions);body.append(tr);
    });
  }
  async function importJSON(file){
    if(!file)return;
    try{
      if(file.size>250000)throw Error("Soubor je příliš velký (limit 250 KB).");
      const json=JSON.parse(await file.text());
      const configs=Array.isArray(json?.strategies)?json.strategies.map(x=>x.config||x):
        [json?.config||json];
      if(!configs.length||configs.length>100)throw Error("JSON musí obsahovat 1–100 strategií.");
      let added=0;
      for(const cfg of configs){const valid=E.config(cfg);
        bank.unshift({id:Date.now()+"_"+added+"_"+Math.random().toString(36).slice(2,6),
          added:new Date().toISOString(),symbol:valid.symbol,config:valid,snapshot:null});added++;
      }
      bank=bank.slice(0,100);persistBank();renderBank();
      alertUser("Importováno "+added+" strategií.");
    }catch(e){alertUser("Neplatný soubor: "+e.message,true);}
    finally{$("import-json").value="";}
  }

  function generatedScore(item){
    const m=item.report.is;
    return Math.max(0,m.avg||0)*Math.sqrt(m.trades)*Math.min(5,m.pf||0);
  }
  function renderGenerated(){
    const body=$("gen-results");body.replaceChildren();
    $("gen-found").textContent=generated.length+" kandidátů";
    if(!generated.length){
      const tr=make("tr");tr.append(make("td",{"class":"empty",colspan:"8"},
        isGenerating?"Počítám varianty…":"Žádná varianta nesplnila minimální kritéria. Uprav počet obchodů nebo doplň delší historii."));body.append(tr);return;
    }
    generated.forEach((item,index)=>{
      const tr=make("tr"),cfg=item.config,r=item.report;
      const cells=[String(index+1),cfg.name,cfg.side,
        String(r.is.trades),fmt(r.is.pf,"×"),fmt(r.is.avg,"%"),fmt(r.oos.pf,"×")];
      for(const val of cells)tr.append(make("td",{},val));
      const action=make("td");
      action.append(button("Testovat",()=>{
        putConfig(cfg);switchTab("builder");
        showResults(r);setStatus("Načten výsledek generátoru pro "+dataSymbol+".");
      }),button("Uložit",()=>saveToBank(cfg,r)));
      tr.append(action);body.append(tr);
    });
  }
  async function runGenerator(){
    if(isGenerating)return;
    try{
      await ensureData();
      const base=getConfig(),total=Number($("gen-count").value),seed=Number($("gen-seed").value);
      const minTrades=Number($("gen-min-trades").value),minPf=Number($("gen-min-pf").value);
      if(![30,100,200].includes(total)||!Number.isInteger(seed)||seed<0||seed>99999999||
        !Number.isInteger(minTrades)||minTrades<2||minTrades>100||
        !Number.isFinite(minPf)||minPf<0||minPf>20)
        throw Error("Zkontroluj nastavení generátoru.");
      const plans=E.makeVariations(base,total,seed);
      generated=[];genCancel=false;isGenerating=true;genProgress=0;
      $("run-generator").disabled=true;$("cancel-generator").disabled=false;
      renderGenerated();
      for(let i=0;i<plans.length;i++){
        if(genCancel)break;
        const cfg=plans[i],res=E.backtest(marketBars,cfg,marketContext);
        if(res.is.trades>=minTrades&&res.is.pf!==null&&
          res.is.pf>=minPf&&(res.is.avg??0)>0){
          generated.push({config:cfg,report:res});
        }
        genProgress=Math.round((i+1)/plans.length*100);
        $("gen-progress-bar").style.width=genProgress+"%";
        if(i%8===0||i===plans.length-1){
          $("gen-progress-label").textContent="Ověřeno "+(i+1)+" / "+plans.length+
            " variant · splnilo IS filtr "+generated.length;
          await new Promise(resolve=>setTimeout(resolve,0));
        }
      }
      generated.sort((a,b)=>generatedScore(b)-generatedScore(a));
      generated=generated.slice(0,20);
      renderGenerated();
      alertUser(genCancel?"Generátor zastaven: částečný výsledek.":"Generování hotovo: "+generated.length+" kandidátů v IS výběru.");
    }catch(e){alertUser("Generator: "+e.message,true);}
    finally{
      isGenerating=false;$("run-generator").disabled=false;$("cancel-generator").disabled=true;
    }
  }
  async function robustness(){
    try{
      if(!lastResult||!marketBars)throw Error("Nejdřív spusť backtest v Rule Builderu.");
      const mc=E.monteCarlo(lastResult.trades,200,42);
      const old=lastResult.config;
      const stress={...old,commission:Math.min(100,old.commission*2),
        spread:Math.min(100,old.spread*2),slippage:Math.min(100,old.slippage*2)};
      const stressed=E.backtest(marketBars,stress,marketContext);
      $("rob-dd50").textContent=fmt(mc.ddMedian,"%");
      $("rob-dd95").textContent=fmt(mc.dd95,"%");
      $("rob-stress").textContent=fmt(stressed.all.net,"%");
      $("rob-oos-count").textContent=String(lastResult.oos.trades);
      $("robustness-note").textContent=mc.warning+" Zvýšené náklady znamenají 2× komisi, spread a slippage."+
        (lastResult.oos.trades<5?" OOS má méně než pět uzavřených obchodů – nedostatečná validace.":"");
      alertUser("Robustness test dokončen.");
    }catch(e){alertUser(e.message,true);}
  }
  async function loadMacroPreview(){
    const target=$("macro-next");
    if(!target)return;
    try{
      const response=await fetch("../market-intelligence/api/overview.php",{method:"GET",cache:"no-store"});
      if(!response.ok)throw Error("Server zdroje nedostupný");
      const data=await response.json();
      const now=Math.floor(Date.now()/1000);
      const events=(Array.isArray(data.calendar)?data.calendar:[])
        .filter(item=>Number(item.time)>now && item.impact==="high")
        .sort((a,b)=>a.time-b.time);
      if(!events.length){
        target.textContent="V dostupných zdrojích BEA/BLS právě není nejbližší událost s vysokým makro významem.";
        return;
      }
      const next=events[0];
      const when=new Intl.DateTimeFormat("cs-CZ",{
        timeZone:"Europe/Prague",day:"2-digit",month:"2-digit",
        hour:"2-digit",minute:"2-digit",hour12:false
      }).format(new Date(next.time*1000));
      target.textContent=when+" · "+(next.name_cs||next.name_original)+" · "+(next.currency||"USD")+
        " (oficiální kalendář "+next.source+")";
    }catch{
      target.textContent="Přehled makro událostí je momentálně nedostupný. Otevři samostatný News & Calendar.";
    }
  }

  function wire(){
    if(!E){setConnection("Nelze načíst výpočetní engine.js.",true);return;}
    $("entry-add").addEventListener("click",()=>{
      if(entryRules.length>=5)return;
      entryRules.push({...E.RULES.close_above_sma,type:"close_above_sma"});drawRules();
    });
    $("exit-add").addEventListener("click",()=>{
      if(exitRules.length>=5)return;
      exitRules.push({...E.RULES.rsi_above,type:"rsi_above"});drawRules();
    });
    for(const b of document.querySelectorAll(".nav-item[data-tab]"))
      b.addEventListener("click",()=>switchTab(b.dataset.tab));
    $("reset-config").addEventListener("click",()=>{putConfig(defaultConfig);setStatus("Výchozí nastavení obnoveno.");});
    $("save-config").addEventListener("click",()=>{
      try{
        const cfg=getConfig();
        const snapshot=lastResult&&JSON.stringify(lastResult.config)===JSON.stringify(cfg)?lastResult:null;
        saveToBank(cfg,snapshot);
      }catch(e){alertUser(e.message,true);}
    });
    $("download-strategy").addEventListener("click",exportConfig);
    $("run-backtest").addEventListener("click",runBacktest);
    $("download-trades").addEventListener("click",exportTrades);
    $("run-generator").addEventListener("click",runGenerator);
    $("cancel-generator").addEventListener("click",()=>{genCancel=true;});
    $("bank-export").addEventListener("click",()=>{
      download(JSON.stringify({app:"StockTool Strategy Lab",version:1,
        strategies:bank.map(x=>({config:x.config,symbol:x.symbol,snapshot:x.snapshot}))},null,2),
        "StockTool_Strategy_Databank.json","application/json;charset=utf-8");
    });
    $("import-json-trigger").addEventListener("click",()=>$("import-json").click());
    $("import-json").addEventListener("change",()=>importJSON($("import-json").files?.[0]));
    $("run-robustness").addEventListener("click",robustness);
    $("load-data").addEventListener("click",()=>loadData());
    $("api-key").addEventListener("keydown",e=>{if(e.key==="Enter")loadData();});
    $("symbol").addEventListener("keydown",e=>{if(e.key==="Enter")loadData();});
    $("symbol").addEventListener("change",syncTimeframeOptions);
    $("timeframe").addEventListener("change",()=>{setDataState("Změněn interval – načti nové svíčky.");});
    $("oos").addEventListener("change",()=>{const n=Number($("oos").value);
      if(n>=15&&n<=50){
        $("split-is-text").textContent=(100-n)+" % IN-SAMPLE";
        $("split-oos-text").textContent=n+" % OUT-OF-SAMPLE";
        $("split-is-bar").style.width=(100-n)+"%";
      }
    });
    window.addEventListener("resize",drawChart);
    loadBank();putConfig(defaultConfig);
    try{const last=localStorage.getItem("stocktool_strategy_lab_market_symbol_v1");if(last)$("symbol").value=last;}catch{}
    restoreLogin();
    loadMacroPreview();
  }
  document.addEventListener("DOMContentLoaded",wire);
})();
