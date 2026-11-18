"use strict";
/**
 * StockTool Market Intelligence. Client does not scrape Forex Factory.
 * Primary news: public issuer RSS; calendar: public US BEA/BLS schedules.
 * Sessions: approximate FX hub opening hours in IANA local time zones.
 */
(() => {
  const $=id=>document.getElementById(id);
  const PRAGUE="Europe/Prague";
  const DAY=86400000;
  const fmtDate=new Intl.DateTimeFormat("cs-CZ",{timeZone:PRAGUE,day:"2-digit",month:"2-digit",year:"numeric"});
  const fmtTime=new Intl.DateTimeFormat("cs-CZ",{timeZone:PRAGUE,hour:"2-digit",minute:"2-digit",hour12:false});
  const fmtLong=new Intl.DateTimeFormat("cs-CZ",{timeZone:PRAGUE,weekday:"long",day:"numeric",month:"long",year:"numeric"});
  const fmtClock=new Intl.DateTimeFormat("cs-CZ",{timeZone:PRAGUE,hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false});
  const tzFormatters=new Map();
  const sessions=[
    {id:"syd",name:"Sydney",country:"Austrálie",zone:"Australia/Sydney",start:9,end:18,topic:"AUD, asijské indexy",color:"syd"},
    {id:"tok",name:"Tokio",country:"Japonsko",zone:"Asia/Tokyo",start:9,end:18,topic:"JPY, Nikkei / JP225",color:"tok"},
    {id:"ldn",name:"Londýn",country:"Velká Británie",zone:"Europe/London",start:8,end:17,topic:"EUR, GBP, GER40, zlato",color:"ldn"},
    {id:"ny",name:"New York",country:"USA",zone:"America/New_York",start:8,end:17,topic:"USD, US500, NAS100, zlato",color:"ny"}
  ];
  const data={news:[],hot:[],calendar:[],updated_at:null,stale:false,translation_enabled:false,sources:[]};
  let lastError="",activeTab="calendar";

  function el(tag,cls="",txt=""){
    const node=document.createElement(tag);
    if(cls)node.className=cls;
    if(txt!=="")node.textContent=txt;
    return node;
  }
  function formatStamp(ts,withDate=true){
    if(ts===null||ts===undefined||!Number.isFinite(Number(ts))||Number(ts)<=0)return "Čas neuveden";
    const date=new Date(Number(ts)*1000);
    return withDate?fmtDate.format(date)+" · "+fmtTime.format(date):fmtTime.format(date);
  }
  function relative(ts){
    if(!ts)return "Bez data";
    const d=Math.round((Date.now()/1000-Number(ts))/3600);
    if(d<0)return "Naplánováno";
    if(d<1)return "Právě zveřejněno";
    if(d<24)return "Před "+d+" h";
    return "Před "+Math.floor(d/24)+" d";
  }
  function badge(impact){
    const name={high:"Vysoké téma",medium:"Střední téma",low:"Ostatní"};
    return el("span","severity "+(impact||"low"),name[impact]||name.low);
  }
  function foreignLink(url,label,cls=""){
    const a=el("a",cls,label);
    // Only trust valid HTTPS source links, never javascript: or embedded HTML.
    try{
      const u=new URL(url);
      if(u.protocol!=="https:")throw Error("Unsafe scheme");
      a.href=u.href;
    }catch{a.removeAttribute("href");return a;}
    a.target="_blank";a.rel="noopener noreferrer";
    return a;
  }
  function translateLink(url){
    const link="https://translate.google.com/translate?sl=auto&tl=cs&u="+encodeURIComponent(url);
    return foreignLink(link,"Přeložit článek ↗");
  }
  function newsMatchesTopic(item,topic) {
    if(topic==="all")return true;
    const t=(item.title_original+" "+item.topic_cs).toLowerCase();
    const patterns={
      rates:/fed|reserve|ecb|interest|rate|úrok|centrální|monetary|bank/,
      inflation:/inflation|cpi|pce|price|inflace|cenov/,
      jobs:/employment|unemployment|payroll|jobs|labor|práce|zaměstnan/,
      growth:/gdp|gross domestic|growth|economic|hospodář|economy|trade|consumer/,
      energy:/oil|petroleum|energy|gas|gold|silver|metals|ropa|energie|zlato/
    };
    return patterns[topic]?.test(t)??true;
  }
  function storyHeading(item){
    // A Czech topical synopsis is not falsely presented as a translation.
    const headline=typeof item.title_cs==="string"&&item.title_cs.trim()
      ?item.title_cs.trim():(item.source+": "+item.topic_cs);
    return headline;
  }
  function createStory(item,hot=false){
    const date=formatStamp(item.published_at);
    const impact=item.weight>=3?"high":item.weight===2?"medium":"low";
    const card=el("article",hot?"hot-card":"story");
    const source=String(item.source||"Zdroj");
    const isTranslation=!!item.translated;
    const heading=storyHeading(item);
    const label=isTranslation?"Český překlad":"České shrnutí tématu";
    if(hot){
      const head=el("div","hot-head");
      head.append(badge(impact),el("span","story-meta",relative(item.published_at)));
      card.append(head);
      card.append(el("div","story-meta",source+" · "+date+" · "+label));
      const title=el("h3");title.append(foreignLink(item.url,heading));card.append(title);
      card.append(el("p","story-original","Původní zpráva: "+item.title_original));
      card.append(el("p","story-cz-explainer",item.context_cs));
      const actions=el("div","hot-actions");
      actions.append(foreignLink(item.url,"Otevřít zdroj ↗"),translateLink(item.url));
      card.append(actions);return card;
    }
    const icon=el("div","story-icon",source);
    const body=el("div","story-main");
    const meta=el("div","story-meta");
    meta.append(el("span","source-tag",source),el("span","",date),badge(impact));
    body.append(meta);
    body.append(el("div","topic-label",item.topic_cs+" · "+label));
    const title=el("h3");title.append(foreignLink(item.url,heading));body.append(title);
    body.append(el("p","story-original","Originál (EN): "+item.title_original));
    body.append(el("p","story-cz-explainer",item.context_cs));
    const actions=el("div","story-actions");
    actions.append(foreignLink(item.url,"Zdroj ↗"),translateLink(item.url));
    card.append(icon,body,actions);
    return card;
  }
  function drawNews(){
    const list=$("news-list");
    list.replaceChildren();
    const selected=$("news-source").value;
    const topic=$("news-topic").value;
    const search=$("news-search").value.trim().toLocaleLowerCase("cs-CZ");
    const items=data.news.filter(item=>(selected==="all"||item.source===selected)&&
      newsMatchesTopic(item,topic)&&
      (!search||(item.title_original+" "+storyHeading(item)+" "+item.topic_cs+" "+item.context_cs).toLocaleLowerCase("cs-CZ").includes(search)));
    if(!items.length){
      list.append(el("div","empty",data.news.length?"Tomuto filtru neodpovídají žádné zprávy.":"Zprávy nejsou momentálně dostupné. Zkus obnovit zdroj nebo otevři Forex Factory."));
    } else for(const item of items)list.append(createStory(item));
    $("news-counter").textContent=String(items.length);
    $("news-foot").textContent="Zobrazeno "+items.length+" z "+data.news.length+
      " zpráv · "+(data.translation_enabled?"Přeložené titulky pomocí DeepL; původní text pod nimi":"České shrnutí tématu nahoře; přesné původní znění menším písmem")+
      " · Čas Praha";
  }
  function drawHot(){
    const list=$("hot-list");list.replaceChildren();
    if(!data.hot.length){
      list.append(el("div","empty","Aktuálně nemáme dostatek nových oficiálních zpráv pro vlastní výběr Hot Stories."));
      return;
    }
    for(const item of data.hot)list.append(createStory(item,true));
  }
  // Calendar v2 is maintained by calendar-v2.js; the public data payload
  // arrives through a single event so News/Hot/Sessions keep working.
  function publishCalendarEvents(payload) {
    document.dispatchEvent(new CustomEvent("stocktool:calendar-data",{
      detail:{events:data.calendar,updated_at:data.updated_at,
        stale:data.stale,data_available:!!payload.data_available,
        sources:data.sources,global_calendar_active:!!payload.global_calendar_active,
        calendar_attribution:payload.calendar_attribution||null}
    }));
  }
  function tzParts(date,tz){
    let formatter=tzFormatters.get(tz);
    if(!formatter){
      formatter=new Intl.DateTimeFormat("en-GB",{
        timeZone:tz,weekday:"short",hour:"2-digit",minute:"2-digit",hour12:false,hourCycle:"h23"
      });
      tzFormatters.set(tz,formatter);
    }
    const parts=Object.fromEntries(formatter.formatToParts(date).map(x=>[x.type,x.value]));
    return {weekday:parts.weekday,hour:Number(parts.hour)%24,minute:Number(parts.minute)};
  }
  function sessionOpen(session,date){
    const p=tzParts(date,session.zone);
    return p.weekday!=="Sat"&&p.weekday!=="Sun"&&p.hour>=session.start&&p.hour<session.end;
  }
  function transition(session,now){
    const state=sessionOpen(session,now);
    let last=state;
    for(let i=1;i<=24*6*4;i++){
      const t=new Date(now.getTime()+i*15*60000);
      const current=sessionOpen(session,t);
      if(current!==last)return{date:t,isOpen:current};
      last=current;
    }
    return null;
  }
  function formatDuration(time){
    const delta=Math.max(0,Math.floor((time.getTime()-Date.now())/60000));
    if(delta>=1440)return "za "+Math.floor(delta/1440)+" d "+Math.floor((delta%1440)/60)+" h";
    if(delta>=60)return "za "+Math.floor(delta/60)+" h "+delta%60+" min";
    return "za "+delta+" min";
  }
  function drawSessions(){
    const now=new Date();
    $("prague-clock").textContent=fmtClock.format(now);
    $("prague-date").textContent=fmtLong.format(now);
    $("session-time-label").textContent="24h přehled: "+fmtDate.format(new Date(now.getTime()-12*3600000))+
      " · čas Praha · označené „teď“";
    const first=now.getTime()-12*3600000;
    let activeCount=0;
    const cards=$("sessions-cards"),timeline=$("sessions-timeline");
    cards.replaceChildren();timeline.replaceChildren();
    const chart=el("div","timeline-inner");
    const ticks=el("div","time-ticks");
    for(let i=0;i<=8;i++)
      ticks.append(el("span","",fmtTime.format(new Date(first+i*3*3600000))));
    chart.append(ticks);
    for(const session of sessions){
      const open=sessionOpen(session,now);
      if(open)activeCount++;
      const transitionAt=transition(session,now);
      const currentLocal=tzParts(now,session.zone);
      const row=el("div","timeline-row");
      row.append(el("div","timeline-name",session.name));
      const track=el("div","timeline-track");
      for(let i=0;i<96;i++){
        const date=new Date(first+i*15*60000);
        const active=sessionOpen(session,date);
        track.append(el("div","timeline-slot"+(active?" active "+session.color:"")));
      }
      const nowMarker=el("div","timeline-now");nowMarker.style.left="50%";track.append(nowMarker);
      row.append(track);chart.append(row);
      const card=el("div","session-card"+(open?" open":""));
      card.append(el("h3","",session.name));
      card.append(el("div","session-state",open?"● Právě aktivní":"○ Mimo hlavní seanci"));
      card.append(el("div","session-time","Pravidelně "+String(session.start).padStart(2,"0")+
        ":00–"+String(session.end).padStart(2,"0")+":00 místního času"));
      const what=transitionAt?(transitionAt.isOpen?"Otevře ":"Zavře ")+
        fmtDate.format(transitionAt.date)+" "+fmtTime.format(transitionAt.date)+" (Praha) "+
        formatDuration(transitionAt.date):"Další přechod není dostupný.";
      card.append(el("p","",what));
      card.append(el("p","",session.topic+" · nyní místně "+String(currentLocal.hour).padStart(2,"0")+":"+String(currentLocal.minute).padStart(2,"0")));
      cards.append(card);
    }
    timeline.append(chart);
    $("n-sessions").textContent=activeCount+" / 4";
    $("sessions-summary").textContent=activeCount?"Hlavní FX seance běží":"Hlavní FX seance mimo provoz";
  }
  function drawStats(){
    $("n-news").textContent=data.news.length;
    $("n-hot").textContent=data.hot.length;
    const now=Math.floor(Date.now()/1000);
    $("n-calendar").textContent=data.calendar.filter(e=>e.time>=now&&e.time<=now+60*86400).length;
    $("source-status").textContent=data.stale?"Starší uložená data":"Aktualizace dat";
    const time=data.updated_at?formatStamp(data.updated_at):"neznámá";
    const missing=data.sources.filter(s=>!s.ok).map(s=>s.name);
    $("source-detail").textContent=
      (lastError?"Chyba aktualizace: "+lastError+". ":"")+
      "Poslední úspěšná aktualizace "+time+". Cache 15 minut. "+
      (data.stale?"Zobrazená data mohou být zastaralá. ":"")+
      (missing.length?"Nedostupné zdroje: "+missing.join(", ")+". ":"")+
      (data.translation_enabled?"Úplné české překlady přes DeepL: aktivní.":"Základní čeština: ověřené tematické shrnutí; originální nadpisy jsou zachovány pro kontrolu.");
  }
  function switchTab(name){
    const tabs=["news","hot","calendar","sessions"];
    if(!tabs.includes(name))return;
    activeTab=name;
    document.body.classList.toggle("calendar-focused",name==="calendar");
    for(const key of tabs){
      const current=key===name;
      $("tab-"+key).classList.toggle("active",current);
      $("tab-"+key).setAttribute("aria-selected",current?"true":"false");
      $("tab-"+key).tabIndex=current?0:-1;
      const panel=$("panel-"+key);panel.classList.toggle("active",current);panel.hidden=!current;
    }
    if(name==="sessions")drawSessions();
  }
  async function loadData(silent=false){
    if(!silent){
      $("refresh-data").disabled=true;
      $("source-status").textContent="Načítám oficiální zdroje…";
    }
    try{
      const response=await fetch("./api/overview.php",{method:"GET",cache:"no-store"});
      if(!response.ok)throw Error("HTTP "+response.status);
      const payload=await response.json();
      if(!payload.ok)throw Error(payload.error||"Neplatná odpověď API");
      data.news=Array.isArray(payload.news)?payload.news:[];
      data.hot=Array.isArray(payload.hot)?payload.hot:[];
      data.calendar=Array.isArray(payload.calendar)?payload.calendar:[];
      data.updated_at=payload.updated_at;data.stale=!!payload.stale;
      data.translation_enabled=!!payload.translation_enabled;
      data.sources=Array.isArray(payload.sources)?payload.sources:[];
      lastError=payload.data_available?"":"Oficiální zdroje momentálně neodpovídají";
      drawNews();drawHot();publishCalendarEvents(payload);drawStats();
    }catch(e){
      lastError=e.message;
      if(!silent){
        $("news-list").replaceChildren(el("div","empty","Načtení zpráv se nezdařilo. Zkontroluj připojení nebo otevři Forex Factory."));
        $("hot-list").replaceChildren(el("div","empty","Zpravodajský zdroj není dostupný."));
      }
      drawStats();
      publishCalendarEvents({data_available:false});
    }finally{$("refresh-data").disabled=false;}
  }
  function init(){
    $("year").textContent=String(new Date().getFullYear());
    for(const button of document.querySelectorAll("[data-tab]"))
      button.addEventListener("click",()=>switchTab(button.dataset.tab));
    for(const id of ["news-topic","news-source"])
      $(id).addEventListener("change",drawNews);
    $("news-search").addEventListener("input",drawNews);
    $("refresh-data").addEventListener("click",()=>loadData());
    const requestedTab=new URLSearchParams(window.location.search).get("tab");
    switchTab(["news","hot","calendar","sessions"].includes(requestedTab)?requestedTab:"calendar");
    drawSessions();loadData();
    setInterval(drawSessions,60000);
    setInterval(()=>{if(!document.hidden)loadData(true);},15*60000);
  }
  document.addEventListener("DOMContentLoaded",init);
})();
