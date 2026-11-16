"use strict";
/* StockTool Strategy Lab v0.1 — client-side, no orders, no network.
 * LONG/SHORT single-symbol D1 bar model. Rules evaluated at close(i),
 * entry at open(i+1), stop/target resolved on known OHLC afterwards.
 * Conservative assumption when both stop and target touch: STOP first.
 */
(function(root){
  const RULES={
    rsi_below:{name:"RSI pod hodnotou",period:14,value:35},
    rsi_above:{name:"RSI nad hodnotou",period:14,value:65},
    close_above_sma:{name:"Close nad SMA",period:50,value:0},
    close_below_sma:{name:"Close pod SMA",period:50,value:0},
    close_above_ema:{name:"Close nad EMA",period:20,value:0},
    close_below_ema:{name:"Close pod EMA",period:20,value:0},
    sma_cross_up:{name:"SMA křížení nahoru",period:10,value:30},
    sma_cross_down:{name:"SMA křížení dolů",period:10,value:30},
    break_high:{name:"Průraz maxima předchozích N D1",period:20,value:0},
    break_low:{name:"Průraz minima předchozích N D1",period:20,value:0},
    roc_above:{name:"Změna N D1 nad (%)",period:10,value:3},
    roc_below:{name:"Změna N D1 pod (%)",period:10,value:-3},
    tick_spike:{name:"Tick volume nad násobkem",period:20,value:1.5},
    green_candle:{name:"Růstová svíčka",period:1,value:0},
    red_candle:{name:"Poklesová svíčka",period:1,value:0}
  };
  const asNum=(v,df=0)=>Number.isFinite(Number(v))?Number(v):df;
  const round=(n,p=4)=>Number.isFinite(n)?Number(n.toFixed(p)):null;
  function verifyBars(raw){
    if(!Array.isArray(raw))throw Error("API nevrátilo svíčky.");
    const seen=new Set();
    const bars=[];
    for(const item of raw) {
      const b={t:asNum(item.t),o:asNum(item.o),h:asNum(item.h),l:asNum(item.l),c:asNum(item.c),
        v:asNum(item.v,0)};
      if(!(b.t>0&&b.o>0&&b.h>0&&b.l>0&&b.c>0&&b.v>=0)||
         b.h<Math.max(b.o,b.l,b.c)||b.l>Math.min(b.o,b.h,b.c))
        throw Error("Historie obsahuje neplatné OHLC hodnoty.");
      if(seen.has(b.t))throw Error("Historie obsahuje duplicitní časové značky.");
      seen.add(b.t);bars.push(b);
    }
    bars.sort((a,b)=>a.t-b.t);
    if(bars.length<65)throw Error("Pro tento Strategy Lab je potřeba alespoň 65 validních D1 svíček.");
    return bars;
  }
  function config(input){
    const x=input||{};
    const allowed=(rules)=>Array.isArray(rules)&&rules.length<=5&&rules.every(r=>Object.hasOwn(RULES,r.type)&&
      Number.isInteger(Number(r.period))&&r.period>=1&&r.period<=250&&
      Number.isFinite(Number(r.value))&&Math.abs(Number(r.value))<=1000);
    if(!allowed(x.entry)||x.entry.length===0)throw Error("Nastav 1–5 platných pravidel vstupu.");
    if(x.exit&& !allowed(x.exit))throw Error("Výstupní pravidla nejsou platná.");
    const side=x.side==="SHORT"?"SHORT":"LONG";
    const join=x.join==="OR"?"OR":"AND";
    const exitJoin=x.exitJoin==="OR"?"OR":"AND";
    const horizon=Math.round(asNum(x.horizon,10));
    const sl=asNum(x.stopLoss,0),tp=asNum(x.takeProfit,0);
    const commission=asNum(x.commission,1),spread=asNum(x.spread,5),slippage=asNum(x.slippage,2);
    const oos=Math.round(asNum(x.oos,30));
    if(horizon<1||horizon>120||sl<0||sl>50||tp<0||tp>100||
      commission<0||commission>100||spread<0||spread>100||slippage<0||slippage>100||
      oos<15||oos>50)throw Error("Horizont, SL/TP, náklady nebo OOS jsou mimo povolený rozsah.");
    return {
      name:String(x.name||"Nová strategie").slice(0,90),side,join,exitJoin,horizon,
      entry:x.entry.map(r=>({type:r.type,period:Number(r.period),value:Number(r.value)})),
      exit:(x.exit||[]).map(r=>({type:r.type,period:Number(r.period),value:Number(r.value)})),
      stopLoss:sl,takeProfit:tp,commission,spread,slippage,oos
    };
  }
  function context(bars){
    const close=bars.map(b=>b.c),volume=bars.map(b=>b.v);
    const cache=new Map();
    function sma(period){
      const key="s"+period;
      if(cache.has(key))return cache.get(key);
      const values=Array(bars.length).fill(null);
      let sum=0;
      for(let i=0;i<close.length;i++){
        sum+=close[i];
        if(i>=period)sum-=close[i-period];
        if(i>=period-1)values[i]=sum/period;
      }
      cache.set(key,values);return values;
    }
    function ema(period){
      const key="e"+period;
      if(cache.has(key))return cache.get(key);
      const values=Array(bars.length).fill(null);
      const alpha=2/(period+1);
      let sm=0;
      for(let i=0;i<close.length;i++){
        if(i<period)sm+=close[i];
        if(i===period-1)values[i]=sm/period;
        else if(i>period-1)values[i]=close[i]*alpha+values[i-1]*(1-alpha);
      }
      cache.set(key,values);return values;
    }
    function rsi(period){
      const key="r"+period;
      if(cache.has(key))return cache.get(key);
      const values=Array(bars.length).fill(null);
      if(bars.length<=period){cache.set(key,values);return values;}
      let gain=0,loss=0;
      for(let i=1;i<=period;i++){
        const delta=close[i]-close[i-1];
        gain+=Math.max(delta,0);loss+=Math.max(-delta,0);
      }
      gain/=period;loss/=period;
      const calc=()=>loss===0?(gain===0?50:100):100-100/(1+gain/loss);
      values[period]=calc();
      for(let i=period+1;i<close.length;i++){
        const delta=close[i]-close[i-1];
        gain=(gain*(period-1)+Math.max(delta,0))/period;
        loss=(loss*(period-1)+Math.max(-delta,0))/period;
        values[i]=calc();
      }
      cache.set(key,values);return values;
    }
    return {bars,close,volume,sma,ema,rsi};
  }
  function ruleValid(rule){
    return Object.hasOwn(RULES,rule.type);
  }
  function evalRule(ctx,rule,i){
    if(!ruleValid(rule)||i<1)return false;
    const p=rule.period,v=rule.value,c=ctx.close,b=ctx.bars;
    const rsi=()=>ctx.rsi(p)[i];
    let av,current,prev,slow;
    switch(rule.type) {
      case "rsi_below":return rsi()!=null&&rsi()<v;
      case "rsi_above":return rsi()!=null&&rsi()>v;
      case "close_above_sma":av=ctx.sma(p)[i];return av!=null&&c[i]>av;
      case "close_below_sma":av=ctx.sma(p)[i];return av!=null&&c[i]<av;
      case "close_above_ema":av=ctx.ema(p)[i];return av!=null&&c[i]>av;
      case "close_below_ema":av=ctx.ema(p)[i];return av!=null&&c[i]<av;
      case "sma_cross_up":
      case "sma_cross_down":{
        slow=Math.round(v);
        if(slow<=p||slow>250)return false;
        const f=ctx.sma(p),s=ctx.sma(slow);
        if(f[i]==null||f[i-1]==null||s[i]==null||s[i-1]==null)return false;
        return rule.type==="sma_cross_up"
          ? f[i]>s[i]&&f[i-1]<=s[i-1]
          : f[i]<s[i]&&f[i-1]>=s[i-1];
      }
      case "break_high":
        if(i<p)return false;
        return c[i]>Math.max(...b.slice(i-p,i).map(x=>x.h));
      case "break_low":
        if(i<p)return false;
        return c[i]<Math.min(...b.slice(i-p,i).map(x=>x.l));
      case "roc_above":
        return i>=p&&c[i]/c[i-p]*100-100>v;
      case "roc_below":
        return i>=p&&c[i]/c[i-p]*100-100<v;
      case "tick_spike": {
        if(i<p||b[i].v<=0)return false;
        const prior=ctx.volume.slice(i-p,i).reduce((a,b)=>a+b,0)/p;
        return prior>0&&b[i].v/prior>v;
      }
      case "green_candle":return b[i].c>b[i].o;
      case "red_candle":return b[i].c<b[i].o;
      default:return false;
    }
  }
  function match(ctx,rules,join,i){
    if(!rules.length)return false;
    return join==="OR"?rules.some(r=>evalRule(ctx,r,i)):rules.every(r=>evalRule(ctx,r,i));
  }
  function stats(trades){
    const n=trades.length;
    if(!n)return {trades:0,winrate:null,avg:null,pf:null,dd:null,net:null,median:null};
    const rets=trades.map(t=>t.net_pct);
    const wins=rets.filter(x=>x>0),losses=rets.filter(x=>x<0);
    const gain=wins.reduce((a,b)=>a+b,0),lost=Math.abs(losses.reduce((a,b)=>a+b,0));
    const sorted=[...rets].sort((a,b)=>a-b);
    let eq=100,peak=100,dd=0;
    const curve=[{t:trades[0].entry_time-86400,eq:100}];
    for(const t of trades){
      eq=Math.max(0,eq*(1+t.net_pct/100));
      peak=Math.max(peak,eq);
      dd=Math.max(dd,peak?100*(peak-eq)/peak:0);
      curve.push({t:t.exit_time,eq:round(eq,5)});
    }
    return {
      trades:n,winrate:round(wins.length/n*100,2),avg:round(rets.reduce((a,b)=>a+b,0)/n),
      pf:lost>0?round(gain/lost,3):null,dd:round(dd,2),net:round(eq-100,2),
      median:round(sorted.length%2?sorted[(n-1)/2]:(sorted[n/2-1]+sorted[n/2])/2),
      curve
    };
  }
  function backtest(rawBars,userConfig,ctxArg){
    const bars=rawBars,opts=config(userConfig);
    const ctx=ctxArg||context(bars);
    const n=bars.length,warmup=Math.max(55,...[...opts.entry,...opts.exit]
      .map(r=>r.type.startsWith("sma_cross")?Math.round(r.value)+3:r.period+3));
    const direction=opts.side==="LONG"?1:-1;
    const feeEach=(opts.spread/2+opts.slippage)/10000;
    const trades=[];
    let active=null,pendingEntry=null,pendingExit=false,ignored=0,unfinished=0;
    function finish(i,price,reason){
      if(!active)return;
      const raw=direction*(price/active.open-1)*100;
      const executed=price*(1-direction*feeEach);
      const costAdjusted=direction*(executed/active.executed-1)*100-2*opts.commission/100;
      trades.push({
        symbol:opts.symbol||"",side:opts.side,setup:opts.name,
        signal_time:bars[active.signalIndex].t,entry_time:bars[active.entryIndex].t,exit_time:bars[i].t,
        entry:round(active.open,6),exit:round(price,6),
        gross_pct:round(raw),net_pct:round(costAdjusted),reason,
        entry_index:active.entryIndex,exit_index:i,signal_index:active.signalIndex
      });
      active=null;
    }
    for(let i=warmup;i<n;i++){
      const bar=bars[i];
      if(active&&pendingExit) {
        finish(i,bar.o,"EXIT_RULE_OR_HORIZON");
        pendingExit=false;
      }
      if(!active&&pendingEntry!==null){
        const open=bar.o;
        const execution=open*(1+direction*feeEach);
        active={signalIndex:pendingEntry,entryIndex:i,open,executed:execution,
          stop:opts.stopLoss>0?execution*(1-direction*opts.stopLoss/100):null,
          target:opts.takeProfit>0?execution*(1+direction*opts.takeProfit/100):null};
        pendingEntry=null;
      }
      if(active){
        // Any gap through stop is filled at the worse OPEN. If both stop
        // and target are reached within one daily bar, STOP has priority.
        let stopHit=false,targetHit=false;
        if(active.stop!==null)
          stopHit=direction===1?bar.l<=active.stop:bar.h>=active.stop;
        if(active.target!==null)
          targetHit=direction===1?bar.h>=active.target:bar.l<=active.target;
        if(stopHit){
          const worse=direction===1?Math.min(bar.o,active.stop):Math.max(bar.o,active.stop);
          finish(i,worse,"STOP_LOSS");
        }else if(targetHit){
          const exec=direction===1?Math.max(bar.o,active.target):Math.min(bar.o,active.target);
          finish(i,exec,"TAKE_PROFIT");
        }
      }
      // Finish day's close, then potentially schedule NEXT day's OPEN.
      if(active){
        const held=i-active.entryIndex+1;
        if(held>=opts.horizon||match(ctx,opts.exit,opts.exitJoin,i))
          pendingExit=true;
      }else if(pendingEntry===null&&i+1<n&&match(ctx,opts.entry,opts.join,i)){
        pendingEntry=i;
      }
      if(!active&&pendingEntry===null&&i===n-1)ignored++;
    }
    if(active||pendingEntry!==null)unfinished++;
    // IS/OOS assignment must use closed trade boundaries only: no leakage.
    const split=Math.max(warmup+2,Math.min(n-1,Math.floor(n*(1-opts.oos/100))));
    const inSample=trades.filter(t=>t.exit_index<split);
    const outSample=trades.filter(t=>t.signal_index>=split);
    const boundary=trades.length-inSample.length-outSample.length;
    return {
      config:opts,count:n,start:bars[0].t,end:bars[n-1].t,split,split_time:bars[split].t,
      all:stats(trades),is:stats(inSample),oos:stats(outSample),
      trades,trades_is:inSample.length,trades_oos:outSample.length,boundary,
      unfinished,ignored,warmup
    };
  }
  // Reproducible Monte Carlo over closed-trade order. Only drawdown varies
  // if 100% closed-trade compounding; this is NOT bootstrap of market paths.
  function monteCarlo(trades,runs=200,seed=42){
    const n=trades.length;
    if(n<5)return {runs:0,n,dd95:null,ddMedian:null,terminalMedian:null,warning:"Pro Monte Carlo je potřeba alespoň 5 uzavřených obchodů."};
    let state=seed>>>0;
    const rand=()=>{state=(Math.imul(state,1664525)+1013904223)>>>0;return state/4294967296};
    const dds=[],terminal=[];
    for(let k=0;k<runs;k++){
      const values=trades.map(t=>t.net_pct);
      for(let i=n-1;i>0;i--){const j=Math.floor(rand()*(i+1));[values[i],values[j]]=[values[j],values[i]];}
      let eq=100,peak=100,dd=0;
      for(const r of values){
        eq=Math.max(0,eq*(1+r/100));peak=Math.max(peak,eq);
        dd=Math.max(dd,peak?100*(peak-eq)/peak:0);
      }
      dds.push(dd);terminal.push(eq-100);
    }
    const pct=(arr,p)=>{const s=[...arr].sort((a,b)=>a-b);return round(s[Math.floor((s.length-1)*p)],2)};
    return{runs,n,seed,dd95:pct(dds,.95),ddMedian:pct(dds,.5),
      terminalMedian:pct(terminal,.5),
      warning:"Monte Carlo pouze promíchává pořadí obchodů. Neřeší tržní režim, slippage, nové ceny ani přeoptimalizaci."};
  }
  function makeVariations(baseline,limit=100,seed=42){
    const r=[];
    let state=seed>>>0;
    const rand=()=>{state=(Math.imul(state,1664525)+1013904223)>>>0;return state/4294967296};
    const choose=a=>a[Math.floor(rand()*a.length)];
    const entries=[
      {type:"rsi_below",period:14,value:30},
      {type:"rsi_above",period:14,value:65},
      {type:"close_above_sma",period:50,value:0},
      {type:"close_below_sma",period:50,value:0},
      {type:"close_above_ema",period:20,value:0},
      {type:"close_below_ema",period:20,value:0},
      {type:"sma_cross_up",period:10,value:30},
      {type:"sma_cross_down",period:10,value:30},
      {type:"break_high",period:20,value:0},
      {type:"break_low",period:20,value:0},
      {type:"roc_above",period:10,value:3},
      {type:"roc_below",period:10,value:-3}
    ];
    const seen=new Set();
    for(let i=0;i<limit*8&&r.length<limit;i++){
      const a={...choose(entries)};
      a.period=Math.max(2,Math.min(120,a.period+choose([-7,-5,-3,0,0,3,5,7])));
      if(a.type.startsWith("sma_cross"))a.value=Math.max(a.period+5,Math.min(190,a.value+choose([-10,0,10,20])));
      else if(a.type.startsWith("rsi_"))a.value=Math.max(10,Math.min(90,a.value+choose([-10,-5,0,5,10])));
      else if(a.type.startsWith("roc_"))a.value=a.value+choose([-3,-2,0,2,3]);
      const side=a.type.includes("below")||a.type.includes("down")||a.type==="break_low"||a.type==="rsi_above"?"SHORT":"LONG";
      const b=choose(entries.filter(v=>!v.type.startsWith("sma_cross")&&v.type!==a.type));
      const entry=rand()<.5?[a]:[a,{...b}];
      const variation={...baseline,
        name:"GEN "+String(r.length+1).padStart(3,"0"),
        side,join:choose(["AND","AND","OR"]),
        entry,exit:[],horizon:choose([3,5,10,15,20]),
        stopLoss:choose([0,3,5,8]),takeProfit:choose([0,5,10,15])
      };
      const signature=JSON.stringify([variation.side,variation.join,entry,variation.horizon,variation.stopLoss,variation.takeProfit]);
      if(seen.has(signature))continue;
      seen.add(signature);
      r.push(config(variation));
    }
    return r;
  }
  root.StockToolStrategyEngine={
    RULES,verifyBars,config,context,evalRule,match,backtest,stats,monteCarlo,makeVariations
  };
})(typeof window!=="undefined"?window:globalThis);