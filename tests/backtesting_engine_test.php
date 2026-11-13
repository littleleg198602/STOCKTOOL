<?php
declare(strict_types=1);
/**
 * php tests/backtesting_engine_test.php
 * Offline reproducible tests; no API key, MT5, network or server data required.
 */
define('STOCKTOOL_BACKTEST_ENGINE',true);
require dirname(__DIR__).'/site/backtesting/api/engine.php';

function bt_assert(bool $ok,string $msg):void{
    if(!$ok)throw new RuntimeException('FAIL: '.$msg);
    echo 'PASS: '.$msg.PHP_EOL;
}
function bt_fixture(int $n=315,float $slope=0.18):array{
    $bars=[];
    $start=(int)floor(time()/86400)*86400-($n+2)*86400;
    $previous=100.0;
    for($i=0;$i<$n;$i++){
        $close=100.0+$slope*$i+2.7*sin($i*.57);
        $open=$previous;
        $bars[]=[
            't'=>$start+$i*86400,'o'=>$open,
            'h'=>max($close,$open)+.35,
            'l'=>min($close,$open)-.35,
            'c'=>$close,'v'=>1000+($i%17)*11
        ];
        $previous=$close;
    }
    return ['symbol'=>'SYNTH','timeframe'=>'D1','bars'=>$bars];
}
$prices=[
 ['t'=>100,'o'=>100,'h'=>102,'l'=>99,'c'=>100,'v'=>100],
 ['t'=>200,'o'=>100,'h'=>105,'l'=>99,'c'=>103,'v'=>100],
 ['t'=>300,'o'=>107,'h'=>109,'l'=>105,'c'=>107,'v'=>100],
 ['t'=>400,'o'=>110,'h'=>112,'l'=>109,'c'=>111,'v'=>100]
];
$zero=['commission'=>0.0,'spread'=>0.0,'slippage'=>0.0];
$paid=['commission'=>2.0,'spread'=>10.0,'slippage'=>3.0];
$buy=bt_trade($prices,0,'SYNTH','BUY','BREAKOUT',2,$zero);
bt_assert($buy['entry_time']===200&&$buy['exit_time']===400,
    'Signal at close(0) enters next open(1) and exits open(3)');
bt_assert(abs($buy['gross_pct']-10.0)<1e-6&&abs($buy['net_pct']-10.0)<1e-6,
    'Gross and net both 10 pct when there are no costs');
$buyPaid=bt_trade($prices,0,'SYNTH','BUY','BREAKOUT',2,$paid);
bt_assert($buyPaid['net_pct']<$buyPaid['gross_pct'],
    'Realistic per-side costs reduce a profitable LONG result');
$short=bt_trade($prices,0,'SYNTH','SHORT','BREAKDOWN',2,$zero);
$shortPaid=bt_trade($prices,0,'SYNTH','SHORT','BREAKDOWN',2,$paid);
bt_assert(abs($short['gross_pct']+10.0)<1e-6,'Short profit has inverse sign');
bt_assert($shortPaid['net_pct']<$short['net_pct'],'Costs worsen SHORT results too');
bt_assert($short['side']==='SHORT'&&$buy['side']==='LONG',
    'BUY and SHORT are different directions');

$fixture=bt_fixture();
$bars=$fixture['bars'];
$prepared=bt_prepare($fixture,time());
bt_assert($prepared['ok']&&count($prepared['bars'])===315,'Valid D1 dataset prepared');
$dup=$fixture;
$dup['bars'][]=$dup['bars'][299];
bt_assert(bt_prepare($dup,time())['reason']==='duplicate_timestamp',
    'Duplicate timestamp rejects the entire dataset, no fabricated returns');
$broken=$fixture;
$broken['bars'][45]['h']=$broken['bars'][45]['l']-.2;
bt_assert(bt_prepare($broken,time())['reason']==='bad_OHLC',
    'Invalid OHLC rejects corrupt historical data');
$shortHistory=bt_fixture(235);
$r=bt_analyze_dataset($shortHistory,['BUY'],[60],$zero,time());
bt_assert($r['groups'][0]['status']==='too_short'&&$r['groups'][0]['required']===271,
    '210 candle warm-up + next open + 60D holding requires 271 bars');

$signalIndex=270;
$known=array_slice($bars,0,$signalIndex+1);
$later=$bars;
for($i=$signalIndex+1;$i<count($later);$i++){
    $later[$i]['c']+=120;
    $later[$i]['o']+=120;
    $later[$i]['h']+=120;
    $later[$i]['l']+=120;
}
foreach(BT_STRATEGIES as $strategy){
    $a=bt_signal($known,'SYNTH',$strategy);
    $b=bt_signal(array_slice($later,0,$signalIndex+1),'SYNTH',$strategy);
    bt_assert($a===$b,"No future data used in $strategy historical signal");
}
// Canonical scanner parity at an arbitrary historical date, including risk veto.
$clock=$known[count($known)-1]['t']+1;
$input=['symbol'=>'SYNTH','timeframe'=>'D1','bars'=>$known];
$buyCanonical=analyze_dataset($input,$clock);
$shortCanonical=sh_analyze($input,$clock);
$pressureCanonical=mp_analyze($input,$clock);
bt_assert(bt_signal($known,'SYNTH','BUY')===
    ($buyCanonical['candidate']?$buyCanonical['raw_setup']:null),
    'BUY backtest invokes canonical live BUY candidate rule');
bt_assert(bt_signal($known,'SYNTH','SHORT')===
    ($shortCanonical['candidate']?$shortCanonical['raw_setup']:null),
    'SHORT backtest invokes canonical live SHORT rule including risk veto');
bt_assert(bt_signal($known,'SYNTH','PRESSURE_REVERSAL')===
    ($pressureCanonical['watch_buy']?$pressureCanonical['setup']:null),
    'Pressure reversal backtest uses canonical watch-buy signal');
bt_assert(bt_signal($known,'SYNTH','PRESSURE_CONTINUATION')===
    ($pressureCanonical['watch_down']?$pressureCanonical['setup']:null),
    'Pressure continuation backtest uses canonical watch-down signal');

$run=bt_analyze_dataset($fixture,BT_STRATEGIES,[1,5,10,20,60],$paid,time());
bt_assert(count($run['groups'])===20,'All 4 strategies x 5 horizons supported');
$tradeCount=0;
foreach($run['groups'] as $g) {
    bt_assert($g['status']==='ok','Sufficient historical bars for '.$g['strategy'].'/'.$g['horizon']);
    $lastExit=0;
    foreach($g['trades'] as $t) {
        $tradeCount++;
        bt_assert($t['signal_time']<$t['entry_time']&&
                  $t['entry_time']<$t['exit_time'],
                  'Every trade waits for future session OPEN, no same-bar fill');
        bt_assert($t['entry_time']>$lastExit,
                  'No overlapping trades within symbol/strategy/horizon');
        $lastExit=$t['exit_time'];
        bt_assert($t['net_pct']<$t['gross_pct']+0.0001,
            'Cost model never improves trade return');
    }
}
bt_assert($tradeCount>0,'Synthetic trends generated at least one canonical completed trade');

echo PHP_EOL.'BACKTESTING ENGINE offline regression tests passed.'.PHP_EOL;
