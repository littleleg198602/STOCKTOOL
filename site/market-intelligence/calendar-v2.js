"use strict";
/* Calendar v2 UI; receives only StockTool's official source calendar events. */
(() => {
  const C=window.StockToolCalendarCore;
  const $=id=>document.getElementById(id);
  const node=(tag,cls="",label="")=>{
    const item=document.createElement(tag);
    if(cls)item.className=cls;
    if(label!=="")item.textContent=label;
    return item;
  };
  const button=(label,fn,cls="",aria="")=>{
    const b=node("button",cls,label);b.type="button";
    if(aria)b.setAttribute("aria-label",aria);
    b.addEventListener("click",fn);return b;
  };
  const link=(url,label)=>{
    const el=node("a","cal-link",label);
    try{
      const u=new URL(url);
      if(u.protocol!=="https:")throw Error("Insecure link");
      el.href=u.href;el.target="_blank";el.rel="noopener noreferrer";
    }catch{return node("span","cal-muted","Zdroj není dostupný");}
    return el;
  };
  const state={
    selected:C.today(),monthCursor:C.monthStart(C.today()),mode:"week",
    timeZone:"prague",brokerOffset:2,currency:"all",impact:"all",category:"all",
    source:"all",search:"",onlyUpcoming:false,view:"compact",
    events:[],loaded:false,stale:false,error:false,expanded:new Set(),focusEvent:""
  };
  const timezoneLabel=()=>state.timeZone==="utc"?"UTC":
    state.timeZone==="broker"?"MT5 (UTC "+(state.brokerOffset>=0?"+":"")+state.brokerOffset+")":"Praha (CET/CEST)";
  const today=()=>C.today(state.timeZone,state.brokerOffset);
  function navigate(date,mode="week",highlight=""){
    if(!C.parseISO(date))return;
    state.selected=date;state.mode=mode;state.monthCursor=C.monthStart(date);
    state.expanded.clear();
    state.focusEvent=highlight;
    if(highlight)state.expanded.add(highlight);
    renderAll();
    if(window.history&&window.history.replaceState){
      const url=new URL(window.location.href);
      url.searchParams.set("tab","calendar");
      url.searchParams.set("date",date);
      if(highlight)url.searchParams.set("event",highlight);
      else url.searchParams.delete("event");
      window.history.replaceState(null,"",url.pathname+url.search+url.hash);
    }
  }
  function preset(value){
    const key=today();
    if(value==="today")navigate(key,"day");
    if(value==="tomorrow")navigate(C.addDays(key,1),"day");
    if(value==="week")navigate(key,"week");
    if(value==="next-week")navigate(C.addDays(key,7),"week");
    if(value==="last-week")navigate(C.addDays(key,-7),"week");
    if(value==="month")navigate(key,"month");
    if(value==="next-month")navigate(C.addMonths(key,1),"month");
    if(value==="last-month")navigate(C.addMonths(key,-1),"month");
  }
  function move(delta){
    const key=state.mode==="month"?C.addMonths(state.selected,delta):
      C.addDays(state.selected,delta*(state.mode==="day"?1:7));
    navigate(key,state.mode);
  }
  function renderMiniMonth(){
    $("cal-month-title").textContent=C.monthLabel(state.monthCursor);
    const container=$("cal-month-grid");container.replaceChildren();
    const window=C.period(state),current=today();
    const eventsOnDays=new Set(state.events.map(e=>C.zoneDate(e.time,state.timeZone,state.brokerOffset)?.date));
    const currentMonth=state.monthCursor.slice(0,7);
    for(const date of C.monthDays(state.monthCursor)){
      const b=button(String(C.parseISO(date).getUTCDate()),()=>navigate(date,"day"),"cal-date-button",C.dayLong(date));
      if(!date.startsWith(currentMonth))b.classList.add("other-month");
      if(date===current)b.classList.add("today");
      if(date>=window.start&&date<window.end)b.classList.add("within-period");
      if(date===state.selected)b.classList.add("selected");
      if(eventsOnDays.has(date))b.classList.add("has-event");
      b.setAttribute("aria-pressed",date===state.selected?"true":"false");
      container.append(b);
    }
    for(const b of document.querySelectorAll("[data-cal-preset]")){
      const val=b.dataset.calPreset;
      const active=val==="week"&&state.mode==="week"&&C.startWeek(state.selected)===C.startWeek(current)||
        val==="today"&&state.mode==="day"&&state.selected===current||
        val==="month"&&state.mode==="month"&&state.monthCursor===C.monthStart(current);
      b.classList.toggle("active",active);
    }
  }
  function impactBadge(impact){
    const types={high:"Vysoká",medium:"Střední",low:"Nízká"};
    const type=Object.hasOwn(types,impact)?impact:"low";
    const wrapper=node("span","cal-impact-badge");
    wrapper.append(node("i","cal-impact "+type),node("span","",types[type]));
    return wrapper;
  }
  function detailRow(event){
    const row=node("tr","cal-expanded-row");
    row.dataset.eventId=String(event.id||"");
    const cell=node("td");cell.colSpan=10;
    const wrap=node("div","cal-detail-wrap"),body=node("div","cal-detail-body");
    body.append(node("strong","",event.name_cs||event.name_original||"Makro událost"));
    if(event.name_cs!==event.name_original)
      body.append(node("div","cal-original-name",event.name_original||""));
    body.append(node("p","",event.context_cs||"Podrobnosti nejsou součástí primárního kalendářového zdroje."));
    const kv=node("div","cal-detail-kv");
    kv.append(node("span","","Měna: "+(event.currency||"—")),
      node("span","","Zdroj: "+(event.source||"—")),
      node("span","","Čas: "+(C.zoneDate(event.time,state.timeZone,state.brokerOffset)?.time||"—")+" "+timezoneLabel()));
    body.append(kv);
    body.append(node("p","cal-detail-warning",
      "Actual: "+C.value(event.actual)+" · Forecast: "+C.value(event.forecast)+
      " · Previous: "+C.value(event.previous)+". Chybějící údaje nejsou nuly a čas události není predikcí pohybu trhu."));
    const side=node("div","cal-detail-side");
    side.append(link(event.url,"Původní oficiální zdroj ↗"));
    side.append(node("small","",Array.isArray(event.history)&&event.history.length?
      "Ověř historické hodnoty v oficiálním zdroji.":"Historický graf není k dispozici."));
    wrap.append(body,side);cell.append(wrap);row.append(cell);return row;
  }
  function toggleEvent(id){
    if(state.expanded.has(id))state.expanded.delete(id);
    else state.expanded.add(id);
    renderRows();
  }
  function eventRow(event,day,first){
    const row=node("tr","cal-event-row");row.dataset.eventId=String(event.id||"");
    if(state.focusEvent===event.id)row.classList.add("highlight");
    const time=C.zoneDate(event.time,state.timeZone,state.brokerOffset);
    const dateCell=node("td","cal-date-cell",first?C.dayShort(day):"");
    const timeCell=node("td","cal-time-cell",time?.time||"—");
    const currencyCell=node("td","cal-currency-cell",event.currency||"—");
    const impactCell=node("td","cal-impact-cell");impactCell.append(impactBadge(event.impact));
    const nameCell=node("td","cal-name-cell");
    const name=button(event.name_cs||event.name_original||"Neznámá událost",
      ()=>toggleEvent(event.id),"cal-event-name","Detail události "+(event.name_cs||event.name_original||""));
    name.setAttribute("aria-expanded",state.expanded.has(event.id)?"true":"false");
    nameCell.append(name);
    if(state.view==="insight")nameCell.append(node("span","cal-inline-context",event.context_cs||"Podrobnosti v oficiálním zdroji."));
    const details=node("td","cal-detail-cell");
    details.append(button(state.expanded.has(event.id)?"▴":"▾",()=>toggleEvent(event.id),
      "cal-detail-trigger","Zobrazit detail"));
    const actual=node("td","cal-data-cell",C.value(event.actual));
    const direction=C.surprise(event);if(direction)actual.classList.add(direction);
    const forecast=node("td","cal-data-cell",C.value(event.forecast));
    const previous=node("td","cal-data-cell",C.value(event.previous));
    const graph=node("td","cal-graph-cell");
    graph.append(node("span","cal-muted","—"));
    row.append(dateCell,timeCell,currencyCell,impactCell,nameCell,details,actual,forecast,previous,graph);
    return row;
  }
  function renderRows(){
    const body=$("cal-v2-body");body.replaceChildren();
    const window=C.period(state);
    $("cal-period-title").textContent=window.title;
    $("cal-zone-status").textContent="Čas: "+timezoneLabel();
    const entries=C.filter(state.events,state);
    let previousDay="";
    if(!entries.length){
      const tr=node("tr"),td=node("td","cal-empty");
      td.colSpan=10;
      td.textContent=!state.loaded?"Čekám na termíny zveřejnění z BEA/BLS…":
        state.error||!state.events.length?"Oficiální termíny nyní nejsou dostupné. Nevytváříme žádné náhradní události.":
        "Pro vybrané období a filtry nejsou dostupné události. Kalendář zatím pokrývá jen oficiální BEA/BLS zveřejnění USA.";
      tr.append(td);body.append(tr);
    }
    for(const item of entries){
      const day=C.zoneDate(item.time,state.timeZone,state.brokerOffset).date;
      if(day!==previousDay){
        const group=node("tr","cal-day-group"),title=node("td","",C.dayLong(day));
        title.colSpan=10;group.append(title);body.append(group);
      }
      body.append(eventRow(item,day,day!==previousDay));
      if(state.expanded.has(item.id))body.append(detailRow(item));
      previousDay=day;
    }
    $("cal-result-count").textContent=entries.length+" událostí";
    $("cal-view-status").textContent=state.loaded?
      (state.stale?"Pozor, data mohou být zastaralá. ":"")+
      "Zobrazeno "+entries.length+" z "+state.events.length+" oficiálních termínů.":
      "Načítám ekonomický kalendář.";
    if(state.focusEvent){
      const selected=[...body.querySelectorAll(".cal-event-row")]
        .find(e=>e.dataset.eventId===state.focusEvent);
      if(selected&&selected.scrollIntoView){
        selected.scrollIntoView({block:"nearest",behavior:"smooth"});
        state.focusEvent="";
      }
    }
  }
  function renderAll(){renderMiniMonth();renderRows();}
  function updateFilters(){
    state.search=$("cal-search").value.trim();
    state.currency=$("cal-currency").value;
    state.source=$("cal-source").value;
    state.impact=$("cal-impact").value;
    state.category=$("cal-category").value;
    state.view=$("cal-view").value;
    state.onlyUpcoming=$("cal-only-upcoming").checked;
    const zone=$("cal-tz").value,offset=Number($("cal-broker-offset").value);
    $("cal-broker-offset-label").hidden=zone!=="broker";
    if(state.timeZone!==zone||state.brokerOffset!==offset){
      state.timeZone=zone;state.brokerOffset=offset;
      state.selected=today();state.monthCursor=C.monthStart(state.selected);
    }
    renderAll();
  }
  function options(selectId,values,allText){
    const select=$(selectId),prev=select.value;
    select.replaceChildren();
    const option=node("option","",allText);option.value="all";select.append(option);
    for(const value of values){const o=node("option","",value);o.value=value;select.append(o);}
    select.value=values.includes(prev)?prev:"all";
  }
  function receiveData(event){
    const payload=event.detail||{};
    state.events=(Array.isArray(payload.events)?payload.events:[])
      .filter(e=>e&&Number.isFinite(Number(e.time))&&Number(e.time)>0)
      .sort((a,b)=>a.time-b.time);
    state.loaded=true;state.error=!!payload.error;
    state.stale=!!payload.stale;
    options("cal-currency",[...new Set(state.events.map(e=>e.currency).filter(Boolean))].sort(),"Všechny dostupné");
    options("cal-source",[...new Set(state.events.map(e=>e.source).filter(Boolean))].sort(),"Všechny dostupné");
    state.currency=$("cal-currency").value;state.source=$("cal-source").value;
    renderAll();
  }
  function upNext(){
    const result=C.nextEvent(state.events,state);
    if(!result){
      $("cal-view-status").textContent="Další odpovídající událost není v dostupných termínech BEA/BLS.";
      return;
    }
    navigate(C.zoneDate(result.time,state.timeZone,state.brokerOffset).date,"day",result.id);
  }
  function init(){
    if(!C||!$("cal-v2-body"))return;
    const q=new URLSearchParams(window.location.search);
    const date=q.get("date");
    if(C.parseISO(date)){
      state.selected=date;state.monthCursor=C.monthStart(date);state.mode="day";
    }
    const id=q.get("event");
    if(id&&/^[a-f0-9]{64}$/i.test(id)){state.expanded.add(id);state.focusEvent=id;}
    for(const b of document.querySelectorAll("[data-cal-preset]"))
      b.addEventListener("click",()=>preset(b.dataset.calPreset));
    $("cal-month-prev").addEventListener("click",()=>{state.monthCursor=C.addMonths(state.monthCursor,-1);renderMiniMonth();});
    $("cal-month-next").addEventListener("click",()=>{state.monthCursor=C.addMonths(state.monthCursor,1);renderMiniMonth();});
    $("cal-prev-week").addEventListener("click",()=>move(-1));
    $("cal-next-week").addEventListener("click",()=>move(1));
    $("cal-today").addEventListener("click",()=>preset("today"));
    $("cal-up-next").addEventListener("click",upNext);
    for(const id of ["cal-currency","cal-source","cal-impact","cal-category",
      "cal-view","cal-only-upcoming","cal-tz","cal-broker-offset"])
      $(id).addEventListener("change",updateFilters);
    $("cal-search").addEventListener("input",updateFilters);
    $("cal-reset-filters").addEventListener("click",()=>{
      $("cal-search").value="";
      for(const id of ["cal-currency","cal-source","cal-impact","cal-category"])$(id).value="all";
      $("cal-view").value="compact";$("cal-only-upcoming").checked=false;
      updateFilters();$("cal-filter-panel").open=false;
    });
    document.addEventListener("stocktool:calendar-data",receiveData);
    renderAll();
  }
  document.addEventListener("DOMContentLoaded",init);
})();