<?php
/** Existing BUY Scanner analysis. Also consumed by the backtest engine. */
declare(strict_types=1);
if (!defined('STOCKTOOL_BUY_RULES')) { http_response_code(404); exit; }

function average_last(array $items, int $n, int $shift = 0): ?float {
    if ($n <= 0 || count($items) < $n + $shift) return null;
    $slice = array_slice($items, -($n + $shift), $n);
    return array_sum($slice) / $n;
}
function rsi14(array $closes): ?float {
    $n = count($closes);
    if ($n < 15) return null;
    $gains = 0.0; $losses = 0.0;
    for ($i = 1; $i <= 14; $i++) {
        $change = $closes[$i] - $closes[$i-1];
        $gains += max(0.0, $change);
        $losses += max(0.0, -$change);
    }
    $avgGain = $gains / 14; $avgLoss = $losses / 14;
    for ($i = 15; $i < $n; $i++) {
        $change = $closes[$i] - $closes[$i-1];
        $avgGain = ($avgGain * 13 + max(0.0, $change)) / 14;
        $avgLoss = ($avgLoss * 13 + max(0.0, -$change)) / 14;
    }
    if ($avgLoss == 0.0) return $avgGain == 0.0 ? 50.0 : 100.0;
    return 100.0 - (100.0 / (1.0 + $avgGain / $avgLoss));
}
function atr14(array $bars): ?float {
    $n = count($bars);
    if ($n < 15) return null;
    $ranges = [];
    for ($i = 1; $i < $n; $i++) {
        $bar = $bars[$i];
        $prevClose = (float)$bars[$i-1]['c'];
        $ranges[] = max(
            (float)$bar['h'] - (float)$bar['l'],
            abs((float)$bar['h'] - $prevClose),
            abs((float)$bar['l'] - $prevClose)
        );
    }
    // Wilder-smoothed ATR.
    $atr = array_sum(array_slice($ranges, 0, 14)) / 14;
    for ($i = 14, $num = count($ranges); $i < $num; $i++) {
        $atr = ($atr * 13 + $ranges[$i]) / 14;
    }
    return $atr;
}
function rounded(?float $value, int $digits = 4): ?float {
    return $value === null || !is_finite($value) ? null : round($value, $digits);
}
function analyze_dataset(array $payload, int $clock): array {
    $symbol = (string)($payload['symbol'] ?? '');
    $input = $payload['bars'] ?? [];
    if (!is_array($input)) $input = [];
    $map = [];
    $invalid = 0; $duplicates = 0;
    foreach ($input as $bar) {
        if (!is_array($bar) || !isset($bar['t'],$bar['o'],$bar['h'],$bar['l'],$bar['c'])) {
            $invalid++; continue;
        }
        $t = (int)$bar['t'];
        $o = (float)$bar['o']; $h = (float)$bar['h'];
        $l = (float)$bar['l']; $c = (float)$bar['c'];
        if ($t <= 0 || !is_finite($o) || !is_finite($h) || !is_finite($l) ||
            !is_finite($c) || $o <= 0 || $h < max($o,$l,$c) || $l > min($o,$h,$c)) {
            $invalid++; continue;
        }
        if (isset($map[(string)$t])) $duplicates++;
        $map[(string)$t] = ['t'=>$t,'o'=>$o,'h'=>$h,'l'=>$l,'c'=>$c,
            'v'=>isset($bar['v']) && is_numeric($bar['v']) ? max(0.0, (float)$bar['v']) : 0.0];
    }
    ksort($map, SORT_NUMERIC);
    $bars = array_values($map);
    $n = count($bars);
    $last = $n ? $bars[$n-1] : null;
    $time = $last ? $last['t'] : null;
    $fresh = $time !== null && $time <= $clock + 86400 && $time >= $clock - 10*86400;
    $base = [
        'symbol'=>$symbol,'timeframe'=>'D1','count'=>$n,
        'last_time'=>$time,'updated_at'=>(int)($payload['updated_at'] ?? 0),
        'fresh'=>$fresh,'setup'=>'NONE','raw_setup'=>'NONE',
        'candidate'=>false,'close'=>$last ? rounded($last['c'], 6) : null,
        'sma20'=>null,'sma50'=>null,'sma200'=>null,'rsi14'=>null,'atr_pct'=>null,
        'ret20_pct'=>null,'vs_sma200_pct'=>null,'from_52w_high_pct'=>null,
        'tick_volume_ratio'=>null,'invalid_bars'=>$invalid,'duplicate_times'=>$duplicates,
        'reasons'=>[]
    ];
    if ($n < 210) {
        $base['setup'] = 'INSUFFICIENT';
        $base['raw_setup'] = 'INSUFFICIENT';
        $base['reasons'] = ["Pouze $n dokončených D1 svíček; pro tuto analýzu je potřeba nejméně 210."];
        return $base;
    }
    $closes = array_column($bars, 'c');
    $highs = array_column($bars, 'h');
    $volumes = array_column($bars, 'v');
    $close = $last['c'];
    $sma20 = average_last($closes, 20);
    $sma50 = average_last($closes, 50);
    $sma50past = average_last($closes, 50, 5);
    $sma200 = average_last($closes, 200);
    $rsi = rsi14($closes);
    $atr = atr14($bars);
    $atrPct = ($atr !== null && $close > 0) ? $atr / $close * 100 : null;
    $ret20 = ($closes[$n-21] > 0) ? ($close / $closes[$n-21] - 1)*100 : null;
    $above200 = ($sma200 !== null && $sma200 > 0) ? ($close / $sma200 - 1)*100 : null;
    $yearHigh = max(array_slice($highs, -min(252, $n)));
    $fromHigh = $yearHigh > 0 ? ($close / $yearHigh - 1)*100 : null;
    $prior20High = max(array_slice($highs, -21, 20));
    $recentVol = average_last($volumes, 20);
    $priorVol = average_last($volumes, 20, 20);
    $volumeRatio = $priorVol !== null && $priorVol > 0 && $recentVol !== null ?
                   $recentVol / $priorVol : null;
    $uptrend = $close > $sma200 && $sma50 > $sma200 && $sma50 >= $sma50past;
    $reasons = [];
    if ($uptrend) $reasons[] = 'Trend: close nad SMA200 a rostoucí SMA50 nad SMA200.';
    if (!$uptrend) $reasons[] = 'Nenalezen úplný dlouhodobý růstový trend.';
    if ($rsi !== null) $reasons[] = 'RSI(14): '.number_format($rsi, 1, '.', '').'.';
    if ($volumeRatio !== null) $reasons[] = 'Poměr tick volume 20 dní / předchozích 20 dní: '.number_format($volumeRatio, 2, '.', '').'× (nejde o burzovní objem).';

    $rawSetup = 'NONE';
    if ($uptrend && $close >= $prior20High && $rsi >= 45 && $rsi <= 76) {
        $rawSetup = 'BREAKOUT';
        $reasons[] = 'Close překonal maximum předchozích 20 obchodních svíček.';
    } elseif ($uptrend && $close >= $sma50*0.97 && $close <= $sma50*1.025
        && $rsi >= 40 && $rsi <= 65) {
        $rawSetup = 'PULLBACK';
        $reasons[] = 'Cena je v pásmu -3 % až +2,5 % kolem SMA50.';
    } elseif ($uptrend && $rsi >= 48 && $rsi <= 70) {
        $rawSetup = 'TREND';
        $reasons[] = 'Rostoucí trend s RSI mezi 48 a 70.';
    } elseif ($close > $sma200 && $rsi >= 35 && $rsi <= 78) {
        $rawSetup = 'WATCH';
        $reasons[] = 'Nad SMA200, ale bez kompletní nákupní formace.';
    } else {
        $reasons[] = 'Nesplňuje podmínky aktuálních BUY technických filtrů.';
    }
    $setup = $fresh ? $rawSetup : 'STALE';
    if (!$fresh) $reasons[] = 'Pozor: poslední D1 svíčka je starší než 10 dní nebo má neobvyklý čas.';
    $base['setup'] = $setup;
    $base['raw_setup'] = $rawSetup;
    $base['candidate'] = $fresh && in_array($rawSetup, ['BREAKOUT','PULLBACK','TREND'], true);
    $base['sma20'] = rounded($sma20, 6);
    $base['sma50'] = rounded($sma50, 6);
    $base['sma200'] = rounded($sma200, 6);
    $base['rsi14'] = rounded($rsi, 2);
    $base['atr_pct'] = rounded($atrPct, 2);
    $base['ret20_pct'] = rounded($ret20, 2);
    $base['vs_sma200_pct'] = rounded($above200, 2);
    $base['from_52w_high_pct'] = rounded($fromHigh, 2);
    $base['tick_volume_ratio'] = rounded($volumeRatio, 2);
    $base['reasons'] = $reasons;
    return $base;
}

