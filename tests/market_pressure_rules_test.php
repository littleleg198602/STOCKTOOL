<?php
declare(strict_types=1);
/**
 * php tests/market_pressure_rules_test.php
 * Offline synthetic regression; no FORPSI API key, MT5 or internet needed.
 */
define('STOCKTOOL_PRESSURE_RULES', true);
require dirname(__DIR__) . '/site/market-pressure/api/pressure_rules.php';

function mp_expect(bool $assertion, string $label): void {
    if (!$assertion) throw new RuntimeException('FAIL: ' . $label);
    echo "PASS: " . $label . PHP_EOL;
}
function mp_fixture(int $count=120, int $ageDays=1): array {
    $bars = [];
    $midnight = (int)floor(time()/86400)*86400;
    for($i=0;$i<$count;$i++) {
        $bars[] = [
            't'=>$midnight-($ageDays+$count-1-$i)*86400,
            'o'=>100.0,'h'=>100.7,'l'=>99.3,'c'=>100.0,'v'=>100
        ];
    }
    return ['symbol'=>'SYNTH','timeframe'=>'D1','bars'=>$bars];
}
function mp_candle(array &$dataset, int $index, float $o, float $h,
                   float $l, float $c, float $vol=100): void {
    $dataset['bars'][$index]['o']=$o;
    $dataset['bars'][$index]['h']=$h;
    $dataset['bars'][$index]['l']=$l;
    $dataset['bars'][$index]['c']=$c;
    $dataset['bars'][$index]['v']=$vol;
}

$panic=mp_fixture();
mp_candle($panic,119,100.0,100.5,92.9,93.0,300);
$row=mp_analyze($panic,time());
mp_expect($row['panic']===true, 'Sharp downside / expanded range / weak close => panic proxy');
mp_expect($row['setup']==='PANIC','Panic setup classified');
mp_expect($row['tick_volume_ratio']>=2.9,'Tick-volume activity compared to prior 20 D1');
mp_expect($row['pressure_points']>=5 && $row['pressure_points']<=9,'Pressure evidence is 0-9 and bounded');
mp_expect(!$row['reversal'],'Price crash is not a bullish reversal');

$forced=mp_fixture();
for($i=115;$i<120;$i++){
    $o=100.0-3.0*($i-115);
    $c=$o-3.0;
    mp_candle($forced,$i,$o,$o+0.7,$c-0.7,$c,130);
}
$forcedRow=mp_analyze($forced,time());
mp_expect($forcedRow['forced_proxy']===true,'Five-bar/20-bar multi-day selling pressure => forced proxy');
mp_expect($forcedRow['setup']==='FORCED_PROXY','Forced proxy labeled as such, not proven liquidation');

$reversal=mp_fixture();
mp_candle($reversal,118,100,100.6,91.8,92,300);
mp_candle($reversal,119,92,102.5,91,102,200);
$revRow=mp_analyze($reversal,time());
mp_expect($revRow['reversal']===true && $revRow['watch_buy']===true,
    'Bullish reclaim after previous completed panic => possible reversal');
mp_expect($revRow['setup']==='REVERSAL','Reversal has own label, not confirmed BUY');

$exhaustion=mp_fixture();
mp_candle($exhaustion,118,100,100.6,91.8,92,300);
mp_candle($exhaustion,119,95,99,90.5,97.5,140);
$exRow=mp_analyze($exhaustion,time());
mp_expect($exRow['exhaustion']===true && !$exRow['reversal'],
    'Lower wick at new low after panic => exhaustion rather than reversal');

$boring=mp_analyze(mp_fixture(),time());
mp_expect(!$boring['panic'] && !$boring['forced_proxy'] &&
    !$boring['watch_buy'] && !$boring['watch_down'],
    'Stable price remains out of signal Top10');

$stale=mp_analyze(mp_fixture(120,22),time());
mp_expect($stale['setup']==='STALE' && !$stale['panic'],
    'Stale data never enters current pressure watchlist');

$short=mp_analyze(mp_fixture(50),time());
mp_expect($short['setup']==='INSUFFICIENT','Minimum history requirement');

$bad=mp_fixture();
$bad['bars'][]=$bad['bars'][119];
$badRow=mp_analyze($bad,time());
mp_expect($badRow['setup']==='BAD_DATA' && $badRow['duplicate_times']===1,
    'Duplicate times disqualify current signals');

$zero=mp_fixture();
mp_candle($zero,119,100,100.5,92.9,93,0);
$zeroRow=mp_analyze($zero,time());
mp_expect($zeroRow['panic'] && $zeroRow['tick_volume_ratio']===null,
    'Missing tick volume is unknown, not fabricated evidence');

echo PHP_EOL . 'MARKET PRESSURE synthetic tests complete.' . PHP_EOL;
