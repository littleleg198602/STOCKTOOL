<?php
declare(strict_types=1);
/*
 * Offline test: php tests/short_rules_test.php
 * No broker account, API key, network or access to trading account required.
 */
define('STOCKTOOL_SHORT_RULES', true);
require dirname(__DIR__) . '/site/short-scanner/api/short_rules.php';

function test_expect(bool $ok, string $what): void {
    if (!$ok) throw new RuntimeException('FAIL: ' . $what);
    echo "PASS: $what\n";
}
function example_series(int $length = 300, float $trend = -0.1,
                        float $lastDrop = 1.5, int $ageDays = 1): array {
    $bars = [];
    $first = (int)(floor(time() / 86400) * 86400)
        - $ageDays * 86400 - ($length - 1) * 86400;
    $previous = 200.0;
    for ($i = 0; $i < $length; $i++) {
        $close = 200 + $trend * $i + sin($i * 0.8);
        if ($i === $length - 1) $close -= $lastDrop;
        $open = $previous;
        $bars[] = [
            't'=>$first + $i*86400,
            'o'=>$open, 'h'=>max($close, $open) + .25,
            'l'=>min($close, $open) - .25,
            'c'=>$close, 'v'=>2500 + $i
        ];
        $previous = $close;
    }
    return ['symbol'=>'TEST', 'timeframe'=>'D1', 'bars'=>$bars];
}

$downtrend = sh_analyze(example_series(), time());
test_expect($downtrend['count'] === 300, '300 platných dokončených svíček');
test_expect($downtrend['raw_setup'] === 'BREAKDOWN', 'samostatné pravidlo prorážení podpory');
test_expect($downtrend['candidate'] === true, 'potvrzený SHORT bez risk veto');
test_expect($downtrend['fresh'] === true, 'aktuální D1 historie');
test_expect($downtrend['rsi14'] >= 30 && $downtrend['rsi14'] <= 60, 'RSI není extrémně přeprodané');

$oversold = sh_analyze(example_series(300,-0.1,3.0), time());
test_expect($oversold['candidate'] === false, 'přeprodaná akcie se nesmí objevit v SHORT Top10');
test_expect($oversold['risk'] === true, 'přeprodaná akcie mezi rizikovými');

$volatile = example_series();
$last = count($volatile['bars']) - 1;
$volatile['bars'][$last]['h'] += 180.0;
$volatile['bars'][$last]['l'] -= 30.0;
$vol = sh_analyze($volatile, time());
test_expect($vol['raw_setup'] === 'BREAKDOWN', 'stále existuje cenový SHORT signál');
test_expect($vol['candidate'] === false && $vol['setup'] === 'AVOID',
            'extrémní ATR vyřazuje jinak platný SHORT');
test_expect($vol['atr_pct'] >= 7, 'ATR přes 7 % zaznamenáno');

$stale = sh_analyze(example_series(300,-0.1,1.5,20), time());
test_expect($stale['setup'] === 'STALE' && !$stale['candidate'], 'stará data neprocházejí');

$insufficient = sh_analyze(example_series(90),time());
test_expect($insufficient['setup'] === 'INSUFFICIENT' && !$insufficient['candidate'],
    'málo dat neprochází');

$uptrend = sh_analyze(example_series(300,0.2,0),time());
test_expect(!$uptrend['candidate'], 'rostoucí trh není vydáván za SHORT');

$duplicates = example_series();
$duplicates['bars'][] = $duplicates['bars'][299];
$checked = sh_analyze($duplicates,time());
test_expect($checked['duplicate_times'] === 1 && $checked['candidate'] === false,
    'duplicitní čas zastavuje SHORT doporučení');

echo "\nStockTool SHORT Scanner pravidla: TESTY HOTOVY.\n";
