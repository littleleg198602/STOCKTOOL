"use strict";
/* Calendar v2 pure functions. No network, UI or copyrighted calendar content. */
(function(root){
  const pad=n=>String(n).padStart(2,"0");
  const isoUTC=d=>d.getUTCFullYear()+"-"+pad(d.getUTCMonth()+1)+"-"+pad(d.getUTCDate());
  function parseISO(key){
    if(!/^\d{4}-\d{2}-\d{2}$/.test(String(key)))return null;
    const d=new Date(key+"T12:00:00Z");
    return Number.isFinite(d.getTime())&&isoUTC(d)===key?d:null;
  }
  function addDays(key,n){
    const d=parseISO(key);if(!d)return null;
    d.setUTCDate(d.getUTCDate()+n);return isoUTC(d);
  }
  function addMonths(key,n){
    const d=parseISO(key);if(!d)return null;
    return isoUTC(new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+n,1,12)));
  }
  function monthStart(key){const d=parseISO(key);return d?isoUTC(new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),1,12))):null;}
  function monday(key){const d=parseISO(key);return d?addDays(key,-(d.getUTCDay()+6)%7):null;}
  // Monday's preceding offset must be calculated before applying unary minus.
  function startWeek(key){
    const d=parseISO(key);return d?addDays(key,-((d.getUTCDay()+6)%7)):null;
  }
  const formatCivil=(key,options)=>{
    const d=parseISO(key);
    return d?new Intl.DateTimeFormat("cs-CZ",{timeZone:"UTC",...options}).format(d):"—";
  };
  const dayLong=key=>formatCivil(key,{weekday:"long",day:"numeric",month:"long",year:"numeric"});
  const dayShort=key=>formatCivil(key,{weekday:"short",day:"numeric",month:"numeric"});
  const monthLabel=key=>formatCivil(key,{month:"long",year:"numeric"});
  function zoneDate(ts,zone="prague",offset=2){
    if(!Number.isFinite(Number(ts))||Number(ts)<=0)return null;
    const valid=Number.isFinite(Number(offset))?Number(offset):0;
    const date=new Date((Number(ts)+(zone==="broker"?valid*3600:0))*1000);
    const tz=zone==="prague"?"Europe/Prague":"UTC";
    const parts=new Intl.DateTimeFormat("en-GB",{
      timeZone:tz,year:"numeric",month:"2-digit",day:"2-digit",
      hour:"2-digit",minute:"2-digit",hour12:false,hourCycle:"h23"
    }).formatToParts(date);
    const o=Object.fromEntries(parts.map(p=>[p.type,p.value]));
    return {date:o.year+"-"+o.month+"-"+o.day,time:o.hour+":"+o.minute};
  }
  function today(zone="prague",offset=2,now=Date.now()){return zoneDate(now/1000,zone,offset).date;}
  function monthDays(key){
    const first=monthStart(key),start=startWeek(first),last=addDays(addMonths(first,1),-1);
    if(!first)return [];
    const count=addDays(start,34)<last?42:35;
    return Array.from({length:count},(_,i)=>addDays(start,i));
  }
  function period(state){
    const key=state.selected;
    if(state.mode==="month"){
      const start=monthStart(key);
      return {start,end:addMonths(start,1),unit:"month",title:monthLabel(start)};
    }
    if(state.mode==="day")return{start:key,end:addDays(key,1),unit:"day",title:dayLong(key)};
    const start=startWeek(key),end=addDays(start,7);
    return{start,end,unit:"week",title:dayShort(start)+" – "+dayShort(addDays(end,-1))+" "+end.slice(0,4)};
  }
  function category(e){
    const t=[e.name_original,e.name_cs,e.topic_cs].map(x=>String(x||"")).join(" ").toLowerCase();
    if(/inflation|cpi|pce|price index|inflac|cen spotřeb|cen výrob/.test(t))return"inflation";
    if(/employment|unemployment|payroll|jobs|labor|labour|jolts|zaměstnan|práce/.test(t))return"jobs";
    if(/fomc|monetary policy|interest rate|central bank|úrok|centrální/.test(t))return"rates";
    if(/gross domestic|\bgdp\b|hospodář|economic growth|\bhdp\b/.test(t))return"growth";
    if(/industrial|manufactur|factory|průmysl|výrob/.test(t))return"industry";
    if(/trade|import|export|obchod|dovoz|vývoz/.test(t))return"trade";
    return"other";
  }
  function allowed(e,state){
    if(state.currency!=="all"&&e.currency!==state.currency)return false;
    if(state.source!=="all"&&e.source!==state.source)return false;
    if(state.impact==="high"&&e.impact!=="high")return false;
    if(state.impact==="medium"&&!["medium","high"].includes(e.impact))return false;
    if(state.impact==="low"&&e.impact!=="low")return false;
    if(state.category!=="all"&&category(e)!==state.category)return false;
    const q=(state.search||"").trim().toLocaleLowerCase("cs-CZ");
    if(q&&!([e.name_original,e.name_cs,e.topic_cs,e.context_cs,e.currency,e.source]
      .map(x=>String(x||"")).join(" ").toLocaleLowerCase("cs-CZ").includes(q)))return false;
    return true;
  }
  function filter(events,state,now=Date.now()){
    const window=period(state);
    return (Array.isArray(events)?events:[]).filter(e=>{
      const date=zoneDate(e?.time,state.timeZone,state.brokerOffset)?.date;
      return date&&date>=window.start&&date<window.end&&
        (!state.onlyUpcoming||Number(e.time)>=now/1000)&&allowed(e,state);
    }).sort((a,b)=>Number(a.time)-Number(b.time)||String(a.name_original).localeCompare(String(b.name_original)));
  }
  function nextEvent(events,state,now=Date.now()){
    return (Array.isArray(events)?events:[]).filter(e=>
      Number.isFinite(Number(e?.time))&&e.time>now/1000&&allowed(e,state))
      .sort((a,b)=>a.time-b.time)[0]||null;
  }
  function value(v){return v===null||v===undefined||String(v).trim()===""?"—":String(v);}
  function surprise(e){
    if(!["higher","lower"].includes(e?.better_direction)||e.actual==null||e.forecast==null)return null;
    const a=Number(e.actual),f=Number(e.forecast);
    if(!Number.isFinite(a)||!Number.isFinite(f)||a===f)return null;
    return (e.better_direction==="higher"?a>f:a<f)?"positive":"negative";
  }
  root.StockToolCalendarCore={
    parseISO,addDays,addMonths,monthStart,startWeek,dayLong,dayShort,monthLabel,
    zoneDate,today,monthDays,period,category,allowed,filter,nextEvent,value,surprise
  };
})(typeof window!=="undefined"?window:globalThis);