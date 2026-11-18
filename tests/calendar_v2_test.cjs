"use strict";
/** node tests/calendar_v2_test.cjs - deterministic, offline; no external data. */
const assert=require("node:assert/strict");
require("../site/market-intelligence/calendar-core.js");
const C=globalThis.StockToolCalendarCore;
let passed=0;
function test(label,fn){fn();passed++;console.log("PASS "+label);}
const sample=[
  {id:"A",name_cs:"Index spotřebitelských cen",name_original:"Consumer Price Index",currency:"USD",
   impact:"high",source:"BLS",time:Date.parse("2026-11-18T13:30:00Z")/1000,
   actual:null,forecast:null,previous:null,topic_cs:"Inflace a cenové tlaky"},
  {id:"B",name_cs:"Hrubý domácí produkt",name_original:"Gross Domestic Product",currency:"USD",
   impact:"high",source:"BEA",time:Date.parse("2026-11-20T13:30:00Z")/1000,
   actual:"2.2%",forecast:"2.1%",previous:"2.0%"},
  {id:"C",name_cs:"Zahraniční obchod",name_original:"International Trade",currency:"EUR",
   impact:"medium",source:"OTHER",time:Date.parse("2026-11-23T10:30:00Z")/1000,
   actual:"0",forecast:null,previous:null}
];
const base=()=>({
  selected:"2026-11-18",mode:"week",timeZone:"prague",brokerOffset:2,
  search:"",currency:"all",impact:"all",source:"all",category:"all",onlyUpcoming:false
});
test("Date validation catches impossible dates",()=>{
  assert.equal(C.parseISO("2026-11-31"),null);
  assert.ok(C.parseISO("2026-11-18"));
  assert.equal(C.parseISO("bad"),null);
});
test("Weeks begin Monday and include Sunday",()=>{
  assert.equal(C.startWeek("2026-11-22"),"2026-11-16");
  assert.equal(C.period(base()).start,"2026-11-16");
  assert.equal(C.period(base()).end,"2026-11-23");
});
test("Moving across year boundary preserves correct week",()=>{
  assert.equal(C.startWeek("2027-01-01"),"2026-12-28");
  assert.equal(C.addDays("2026-12-31",1),"2027-01-01");
  assert.equal(C.addMonths("2026-12-25",1),"2027-01-01");
});
test("Mini month respects full 6-week grid when needed",()=>{
  const days=C.monthDays("2026-11-01");
  assert.equal(days[0],"2026-10-26");
  assert.equal(days[days.length-1],"2026-12-06");
});
test("CET and CEST correctly convert official UTC releases",()=>{
  const before=Date.parse("2026-03-29T00:30:00Z")/1000;
  const after=Date.parse("2026-03-29T01:30:00Z")/1000;
  assert.deepEqual(C.zoneDate(before,"prague"),{date:"2026-03-29",time:"01:30"});
  assert.deepEqual(C.zoneDate(after,"prague"),{date:"2026-03-29",time:"03:30"});
  assert.equal(C.zoneDate(after,"utc").time,"01:30");
});
test("Broker time uses explicit offset, never guessed broker DST",()=>{
  const epoch=Date.parse("2026-11-18T23:30:00Z")/1000;
  assert.deepEqual(C.zoneDate(epoch,"broker",2),{date:"2026-11-19",time:"01:30"});
  assert.deepEqual(C.zoneDate(epoch,"prague"),{date:"2026-11-19",time:"00:30"});
});
test("Weekly source filtering is correctly applied",()=>{
  const result=C.filter(sample,base());
  assert.deepEqual(result.map(e=>e.id),["A","B"]);
  assert.deepEqual(C.filter(sample,{...base(),source:"BLS"}).map(e=>e.id),["A"]);
  assert.deepEqual(C.filter(sample,{...base(),currency:"EUR"}),[]);
});
test("Day navigation and impact/category search",()=>{
  assert.deepEqual(C.filter(sample,{...base(),mode:"day",selected:"2026-11-18"}).map(e=>e.id),["A"]);
  assert.deepEqual(C.filter(sample,{...base(),category:"inflation"}).map(e=>e.id),["A"]);
  assert.deepEqual(C.filter(sample,{...base(),search:"hrubý"}).map(e=>e.id),["B"]);
});
test("Latest event lookup finds next future date ignoring current view",()=>{
  const now=Date.parse("2026-11-18T14:00:00Z");
  assert.equal(C.nextEvent(sample,base(),now)?.id,"B");
  assert.equal(C.nextEvent(sample,{...base(),currency:"EUR"},now)?.id,"C");
});
test("Missing data is not zero and never earns surprise color",()=>{
  assert.equal(C.value(null),"—");
  assert.equal(C.value(undefined),"—");
  assert.equal(C.value(""),"—");
  assert.equal(C.value(0),"0");
  assert.equal(C.surprise(sample[1]),null);
});
test("Surprise colors require explicit trusted direction metadata",()=>{
  assert.equal(C.surprise({actual:2,forecast:1,better_direction:"higher"}),"positive");
  assert.equal(C.surprise({actual:2,forecast:1,better_direction:"lower"}),"negative");
  assert.equal(C.surprise({actual:2,forecast:1}),null);
});
console.log("\nCalendar v2:",passed,"offline tests passed.");
