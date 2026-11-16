"use strict";
/**
 * node tests/strategy_lab_engine_test.cjs
 * All synthetic: no account data, internet, broker connection, credentials.
 */
const assert=require("node:assert/strict");
require("../site/strategy-lab/engine.js");
const E=globalThis.StockToolStrategyEngine;
assert.ok(E,"Engine must be available in Node and browser");
const eq=(a,b)=>Math.abs(a-b)<1e-6;
function series(n=350){
  const bars=[];let prior=100;
  for(let i=0;i<n;i++){
    const c=100+i*.09+2*Math.sin(i*.62);
    const o=prior;
    bars.push({t:1700000000+i*86400,o,h:Math.max(o,c)+.7,
      l:Math.min(o,c)-.7,c,v:1000+i%15*40});
    prior=c;
  }
  return bars;
}
const bars=E.verifyBars(series());
const base={
  symbol:"TEST",name:"Synthetic test",side:"LONG",join:"AND",exitJoin:"AND",
  entry:[{type:"close_above_sma",period:20,value:0}],exit:[],horizon:5,
  stopLoss:0,takeProfit:0,commission:0,spread:0,slippage:0,oos:30
};
let count=0;
const test=(name,fn)=>{fn();count++;console.log("PASS:",name)};
test("Rejects duplicate data and impossible OHLC",()=>{
  assert.throws(()=>E.verifyBars([...bars,bars[299]]),/duplicitní/i);
  const corrupted=series();corrupted[12].h=corrupted[12].l-.2;
  assert.throws(()=>E.verifyBars(corrupted),/OHLC/i);
});
test("Indicator rules read current and previous bars only",()=>{
  const ctx=E.context(bars),i=225;
  const entry={type:"sma_cross_up",period:10,value:30};
  const a=E.evalRule(ctx,entry,i);
  const changed=series();
  for(let j=i+1;j<changed.length;j++){
    changed[j].o+=400;changed[j].h+=400;changed[j].l+=400;changed[j].c+=400;
  }
  const b=E.evalRule(E.context(changed),entry,i);
  assert.equal(a,b);
});
test("Next-open entry and fixed-horizon exit, no overlap",()=>{
  const r=E.backtest(bars,base);
  assert.ok(r.trades.length>5);
  for(let i=0;i<r.trades.length;i++){
    const t=r.trades[i];
    assert.equal(t.entry_index,t.signal_index+1);
    assert.equal(t.exit_index,t.entry_index+base.horizon);
    assert.ok(t.signal_time<t.entry_time&&t.entry_time<t.exit_time);
    if(i>0)assert.ok(t.entry_index>r.trades[i-1].exit_index);
    assert.equal(t.symbol,"TEST");
  }
});
test("Costs worsen returns for same completed fills",()=>{
  const free=E.backtest(bars,base);
  const costly=E.backtest(bars,{...base,commission:2,spread:8,slippage:3});
  assert.equal(free.trades.length,costly.trades.length);
  for(let i=0;i<free.trades.length;i++){
    assert.ok(costly.trades[i].net_pct<free.trades[i].net_pct);
    assert.equal(free.trades[i].entry_index,costly.trades[i].entry_index);
    assert.equal(free.trades[i].exit_index,costly.trades[i].exit_index);
  }
});
test("Same-day ambiguous SL and TP selects conservative STOP",()=>{
  const flat=[];
  for(let i=0;i<90;i++)flat.push({t:1700000000+i*86400,o:100,h:100.5,l:99.5,c:100,v:100});
  flat[55]={...flat[55],o:99,h:100.5,l:98.5,c:100};
  flat[56]={...flat[56],o:100,h:110,l:90,c:100};
  const config={...base,entry:[{type:"green_candle",period:1,value:0}],
    stopLoss:5,takeProfit:5,horizon:10};
  const r=E.backtest(E.verifyBars(flat),config);
  assert.ok(r.trades.length);
  assert.equal(r.trades[0].reason,"STOP_LOSS");
  assert.ok(eq(r.trades[0].gross_pct,-5));
});
test("Stop gap is executed at worse opening price",()=>{
  const flat=[];
  for(let i=0;i<90;i++)flat.push({t:1700000000+i*86400,o:100,h:100.5,l:99.5,c:100,v:100});
  flat[55]={...flat[55],o:99,h:100.5,l:98.5,c:100};
  flat[56]={...flat[56],o:100,h:100.5,l:99.5,c:100};
  flat[57]={...flat[57],o:92,h:100,l:90,c:97};
  const config={...base,entry:[{type:"green_candle",period:1,value:0}],
    stopLoss:5,takeProfit:0,horizon:10};
  const r=E.backtest(E.verifyBars(flat),config);
  assert.ok(r.trades.length);
  assert.equal(r.trades[0].exit_index,57);
  assert.ok(eq(r.trades[0].gross_pct,-8),"Gap 92 is worse than stop at 95");
});
test("Out-of-sample trades never share boundary with in-sample",()=>{
  const result=E.backtest(bars,base);
  assert.equal(result.trades_is+result.trades_oos+result.boundary,result.trades.length);
  assert.ok(result.trades.filter(t=>t.exit_index<result.split).length===result.trades_is);
  assert.ok(result.trades.filter(t=>t.signal_index>=result.split).length===result.trades_oos);
});
test("Changing FUTURE OHLC cannot change signal from the past",()=>{
  const i=205;
  const rule={type:"rsi_below",period:14,value:40};
  const changed=series();
  for(let j=i+1;j<changed.length;j++){
    changed[j].o+=200;changed[j].h+=200;changed[j].l+=200;changed[j].c+=200;
  }
  assert.equal(E.evalRule(E.context(bars),rule,i),
    E.evalRule(E.context(changed),rule,i));
});
test("Generator is reproducible and returns valid, bounded configs",()=>{
  const a=E.makeVariations(base,30,42),b=E.makeVariations(base,30,42);
  assert.equal(a.length,30);
  assert.deepEqual(a,b);
  for(const c of a){
    assert.equal(c.symbol,"TEST");
    assert.ok(["SHORT","LONG"].includes(c.side));
    assert.doesNotThrow(()=>E.backtest(bars,c));
  }
});
test("Monte Carlo is seeded and requires adequate history",()=>{
  const r=E.backtest(bars,base);
  const a=E.monteCarlo(r.trades,200,42);
  assert.deepEqual(a,E.monteCarlo(r.trades,200,42));
  assert.equal(a.runs,200);
  assert.ok(a.dd95>=a.ddMedian);
  assert.equal(E.monteCarlo([],200,42).runs,0);
});
console.log("\nStrategy Lab:",count,"offline regression tests passed.");
