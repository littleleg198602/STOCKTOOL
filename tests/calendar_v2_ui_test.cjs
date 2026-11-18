"use strict";
/** Minimal DOM smoke test for calendar-v2.js. No browser/network/dependencies. */
const assert=require("node:assert/strict");
require("../site/market-intelligence/calendar-core.js");
const C=globalThis.StockToolCalendarCore;
const controls=new Map(),listeners=new Map();
class FakeNode {
  constructor(tag="div"){
    this.tag=tag;this.children=[];this.textContent="";this.className="";this.style={};
    this.dataset={};this.hidden=false;this.checked=false;this.value="all";
    this.attributes={};this.classList={
      add:()=>{},remove:()=>{},toggle:()=>{}
    };
  }
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=[...children];}
  setAttribute(name,value){this.attributes[name]=value;}
  addEventListener(name,callback){listeners.set(this.id+":"+name,callback);}
  querySelectorAll(cls){return cls===".cal-event-row"?this.children.filter(x=>x.className==="cal-event-row"):[];}
  scrollIntoView(){}
  dispatch(name){const cb=listeners.get(this.id+":"+name);if(cb)cb();}
}
for(const [id,value] of Object.entries({
  "cal-currency":"all","cal-source":"all","cal-impact":"all","cal-category":"all",
  "cal-view":"compact","cal-tz":"prague","cal-broker-offset":"2","cal-search":""
})){
  const n=new FakeNode();n.id=id;n.value=value;controls.set(id,n);
}
const presets=["today","tomorrow","week","next-week","last-week","month","next-month","last-month"]
  .map(value=>{const n=new FakeNode("button");n.id="preset-"+value;n.dataset.calPreset=value;return n;});
const document={
  getElementById(id){
    if(!controls.has(id)){const el=new FakeNode();el.id=id;controls.set(id,el);}
    return controls.get(id);
  },
  createElement(tag){const n=new FakeNode(tag);n.id=tag;return n;},
  querySelectorAll(sel){return sel==="[data-cal-preset]"?presets:[];},
  addEventListener(name,callback){listeners.set("document:"+name,callback);}
};
let replaceCount=0;
global.window={
  StockToolCalendarCore:C,
  location:{href:"https://www.stocktool.eu/test/market-intelligence/",search:""},
  history:{replaceState(){replaceCount++;}}
};
global.document=document;
require("../site/market-intelligence/calendar-v2.js");
assert.ok(listeners.has("document:DOMContentLoaded"));
listeners.get("document:DOMContentLoaded")();
const val=id=>controls.get(id)?.textContent;
assert.ok([35,42].includes(document.getElementById("cal-month-grid").children.length));
const now=Math.floor(Date.now()/1000);
const e={
 id:"a".repeat(64),time:now+3600,source:"BLS",currency:"USD",impact:"high",
 name_cs:"Index spotřebitelských cen",name_original:"Consumer Price Index",
 context_cs:"Inflace ovlivňuje úroková očekávání.",actual:null,forecast:null,previous:null,
 url:"https://www.bls.gov/schedule/news_release/"
};
listeners.get("document:stocktool:calendar-data")({detail:{events:[e],stale:false}});
assert.equal(document.getElementById("cal-currency").children.length,2);
document.getElementById("cal-up-next").dispatch("click");
assert.equal(val("cal-result-count"),"1 událostí");
assert.equal(document.getElementById("cal-v2-body").children.length,3,
  "day group + event + expanded details");
assert.ok(replaceCount>0,"Up Next preserves a direct calendar URL");
const impact=document.getElementById("cal-impact");
impact.value="low";impact.dispatch("change");
assert.equal(val("cal-result-count"),"0 událostí");
document.getElementById("cal-reset-filters").dispatch("click");
assert.equal(val("cal-result-count"),"1 událostí");
const next=val("cal-period-title");
document.getElementById("cal-next-week").dispatch("click");
assert.notEqual(val("cal-period-title"),next,"Period arrows must change date");
document.getElementById("cal-tz").value="utc";
document.getElementById("cal-tz").dispatch("change");
assert.ok(val("cal-zone-status").includes("UTC"));
console.log("Calendar v2 UI smoke test passed: mini calendar, data feed, Up Next, expanded details, filters, week navigation, timezones.");
