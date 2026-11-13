<?php
declare(strict_types=1);
/**
 * Market Pressure Scanner: deterministic OHLCV *proxies*, not actual order flow
 * or proof of forced liquidation. No broker orders, no external sources.
 */
if (!defined('STOCKTOOL_PRESSURE_RULES')) {
    http_response_code(404);
    exit;
}

function mp_round(?float $value, int $precision = 2): ?float {
    return $value === null || !is_finite($value) ? null : round($value, $precision);
}
function mp_average(array $values): ?float {
    return count($values) ? array_sum($values) / count($values) : null;
}
function mp_range(array $bar, float $prevClose): float {
    return max($bar['h'] - $bar['l'], abs($bar['h'] - $prevClose),
               abs($bar['l'] - $prevClose));
}
/** Average true range of 14 bars BEFORE position $index; no look-ahead. */
function mp_prior_atr(array $bars, int $index): ?float {
    if ($index < 15) return null;
    $sum = 0.0;
    for ($i = $index - 14; $i < $index; $i++) {
        $sum += mp_range($bars[$i], $bars[$i - 1]['c']);
    }
    return $sum / 14;
}
/** Price / activity evidence for one completed bar, using past bars only. */
function mp_features(array $bars, int $index): ?array {
    if ($index < 21 || $index >= count($bars)) return null;
    $b = $bars[$index];
    $prior = $bars[$index - 1];
    $atr = mp_prior_atr($bars, $index);
    if ($atr === null || $atr <= 0 || $prior['c'] <= 0 || $bars[$index - 5]['c'] <= 0) {
        return null;
    }
    $range = $b['h'] - $b['l'];
    $trueRange = mp_range($b, $prior['c']);
    $move = $b['c'] - $prior['c'];
    $low20 = min(array_column(array_slice($bars, $index - 20, 20), 'l'));
    $high20 = max(array_column(array_slice($bars, $index - 20, 20), 'h'));
    $volBefore = array_column(array_slice($bars, $index - 20, 20), 'v');
    $volAvg = mp_average($volBefore);
    // Missing or all-zero tick activity -> unknown, NEVER a fabricated volume signal.
    $volRatio = $volAvg !== null && $volAvg > 0 && $b['v'] > 0
        ? $b['v'] / $volAvg : null;
    $negative = 0;
    $wideDown = 0;
    for ($k = $index - 4; $k <= $index; $k++) {
        if ($bars[$k]['c'] < $bars[$k - 1]['c']) $negative++;
        $atrK = mp_prior_atr($bars, $k);
        if ($atrK !== null && $atrK > 0 && $bars[$k]['c'] < $bars[$k]['o'] &&
            mp_range($bars[$k], $bars[$k - 1]['c']) >= $atrK * 1.3) {
            $wideDown++;
        }
    }
    $ret1 = ($b['c'] / $prior['c'] - 1) * 100;
    $ret5 = ($b['c'] / $bars[$index - 5]['c'] - 1) * 100;
    $ret20 = ($b['c'] / $bars[$index - 20]['c'] - 1) * 100;
    $clv = $range > 0 ? ($b['c'] - $b['l']) / $range : 0.5;
    $wick = $range > 0 ? (min($b['o'], $b['c']) - $b['l']) / $range : 0.0;
    $moveAtr = $move / $atr;
    $rangeAtr = $trueRange / $atr;

    // A strict *market-data proxy*: cannot establish that anyone was forced to sell.
    $panic = $ret1 <= -2.0 && $moveAtr <= -1.25 &&
             $rangeAtr >= 1.4 && $clv <= 0.32;
    $forcedProxy = $ret5 <= -7.0 && $ret20 <= -10.0 &&
                   $negative >= 4 && $wideDown >= 2;
    $pressure = $ret5 <= -4.0 && $negative >= 3 &&
                ($b['c'] < $low20 || $clv <= 0.35);

    // Transparent evidence count, not probability or prediction.
    $points = ($ret1 <= -2.0 ? 1 : 0)
            + ($moveAtr <= -1.25 ? 2 : 0)
            + ($rangeAtr >= 1.4 ? 1 : 0)
            + ($clv <= 0.30 ? 1 : 0)
            + ($volRatio !== null && $volRatio >= 1.5 ? 1 : 0)
            + ($negative >= 4 ? 1 : 0)
            + ($ret5 <= -7.0 ? 1 : 0)
            + ($b['c'] < $low20 ? 1 : 0);
    return [
        'ret1'=>$ret1, 'ret5'=>$ret5, 'ret20'=>$ret20,
        'atr_pct'=>$atr / $b['c'] * 100, 'move_atr'=>$moveAtr,
        'range_atr'=>$rangeAtr, 'clv'=>$clv, 'lower_wick'=>$wick,
        'tick_ratio'=>$volRatio, 'down5'=>$negative, 'wide_down5'=>$wideDown,
        'low20'=>$low20, 'high20'=>$high20, 'panic'=>$panic,
        'forced'=>$forcedProxy, 'pressure'=>$pressure, 'points'=>$points
    ];
}
function mp_analyze(array $dataset, int $now): array {
    $map = []; $invalid = 0; $duplicates = 0;
    $source = $dataset['bars'] ?? [];
    if (!is_array($source)) $source = [];
    foreach ($source as $item) {
        if (!is_array($item) || !isset($item['t'],$item['o'],$item['h'],$item['l'],$item['c'])) {
            $invalid++; continue;
        }
        $t = (int)$item['t'];
        $o = (float)$item['o']; $h = (float)$item['h'];
        $l = (float)$item['l']; $c = (float)$item['c'];
        $v = isset($item['v']) && is_numeric($item['v']) ? (float)$item['v'] : 0.0;
        if ($t < 946684800 || $t > $now + 86400 ||
            !is_finite($o)||!is_finite($h)||!is_finite($l)||!is_finite($c)||
            !is_finite($v) || $o<=0 || $h<=0 || $l<=0 || $c<=0 || $v<0 ||
            $h < max($o,$l,$c) || $l > min($o,$h,$c)) {
            $invalid++; continue;
        }
        if (isset($map[(string)$t])) $duplicates++;
        $map[(string)$t] = ['t'=>$t,'o'=>$o,'h'=>$h,'l'=>$l,'c'=>$c,'v'=>$v];
    }
    ksort($map, SORT_NUMERIC);
    $bars = array_values($map);
    $n = count($bars);
    $last = $n ? $bars[$n-1] : null;
    $fresh = $last !== null && $last['t'] >= $now - 10 * 86400;
    $valid = $invalid === 0 && $duplicates === 0;
    $base = [
        'symbol'=>(string)($dataset['symbol']??''),'timeframe'=>'D1','count'=>$n,
        'last_time'=>$last['t']??null, 'updated_at'=>(int)($dataset['updated_at']??0),
        'fresh'=>$fresh,'data_ok'=>$valid,
        'setup'=>'NONE','primary'=>'NONE',
        'panic'=>false,'forced_proxy'=>false,'exhaustion'=>false,'reversal'=>false,
        'continuation'=>false,'watch_buy'=>false,'watch_down'=>false,
        'pressure_points'=>0,'price'=>$last ? mp_round($last['c'],6):null,
        'ret1_pct'=>null,'ret5_pct'=>null,'ret20_pct'=>null,
        'atr_pct'=>null,'move_atr'=>null,'range_atr'=>null,
        'close_location_pct'=>null,'lower_wick_pct'=>null,'tick_volume_ratio'=>null,
        'down_days5'=>null,'wide_down5'=>null,'last_panic_bars_ago'=>null,
        'invalid_bars'=>$invalid,'duplicate_times'=>$duplicates,
        'reasons'=>[],'warnings'=>[
            'Pouze proxy z OHLC a brokerova tick volume. Nucený výprodej ani skutečný order flow nelze potvrdit.'
        ]
    ];
    if ($n < 80) {
        $base['setup']='INSUFFICIENT';
        $base['reasons'][]="Jen $n D1 svíček. Pro porovnání aktivity a předchozích výprodejů je potřeba alespoň 80.";
        return $base;
    }
    if (!$valid) {
        $base['setup']='BAD_DATA';
        $base['reasons'][]='Chybné nebo duplicitní časové svíčky; výsledek je z bezpečnostních důvodů vyřazen.';
        return $base;
    }
    if (!$fresh) {
        $base['setup']='STALE';
        $base['reasons'][]='Poslední uložená D1 svíčka je starší než 10 kalendářních dní.';
        return $base;
    }

    $features = mp_features($bars, $n - 1);
    if ($features === null) {
        $base['setup']='INSUFFICIENT';
        $base['reasons'][]='Nelze bezpečně vypočítat ATR nebo srovnávací období.';
        return $base;
    }
    $base['ret1_pct']=mp_round($features['ret1']);
    $base['ret5_pct']=mp_round($features['ret5']);
    $base['ret20_pct']=mp_round($features['ret20']);
    $base['atr_pct']=mp_round($features['atr_pct']);
    $base['move_atr']=mp_round($features['move_atr']);
    $base['range_atr']=mp_round($features['range_atr']);
    $base['close_location_pct']=mp_round($features['clv']*100,1);
    $base['lower_wick_pct']=mp_round($features['lower_wick']*100,1);
    $base['tick_volume_ratio']=mp_round($features['tick_ratio']);
    $base['down_days5']=$features['down5'];
    $base['wide_down5']=$features['wide_down5'];
    $base['pressure_points']=$features['points'];

    // Historical precursor signal uses only PREVIOUS, already completed bars.
    $prevPanic = null; $prevForced = false;
    for ($i = max(21, $n - 6); $i <= $n - 2; $i++) {
        $earlier = mp_features($bars, $i);
        if ($earlier === null) continue;
        if ($earlier['panic'] || $earlier['forced']) {
            $prevPanic = $n - 1 - $i;
            $prevForced = $prevForced || $earlier['forced'];
        }
    }
    $prev = $bars[$n-2];
    $b = $bars[$n-1];
    $reversal = $prevPanic !== null && $b['c'] > $b['o'] &&
                $b['c'] > $prev['h'] && $features['clv'] >= 0.68;
    $exhaustion = !$reversal && ($prevPanic !== null ||
                  $features['panic'] || $features['forced']) &&
                  $b['l'] < $features['low20'] &&
                  $features['lower_wick'] >= 0.35 && $features['clv'] >= 0.55;
    $continuation = !$reversal && !$exhaustion &&
                    ($features['panic'] || $features['forced'] || $features['pressure']);
    $base['panic']=$features['panic'];
    $base['forced_proxy']=$features['forced'];
    $base['reversal']=$reversal;
    $base['exhaustion']=$exhaustion;
    $base['continuation']=$continuation;
    $base['watch_buy']=$reversal || $exhaustion;
    $base['watch_down']=$continuation;
    $base['last_panic_bars_ago']=$prevPanic;

    if ($reversal) {
        $base['setup']='REVERSAL';
        $base['reasons'][]='Po výprodejové epizodě posledních pěti svíček přišla růstová svíčka uzavřená nad předchozím High a v horních 32 % rozpětí.';
    } elseif ($exhaustion) {
        $base['setup']='EXHAUSTION';
        $base['reasons'][]='Po výprodejovém tlaku vzniklo nové 20svíčkové Low, dlouhý spodní knot (≥35 %) a Close v horních 45 % rozpětí.';
    } elseif ($features['forced']) {
        $base['setup']='FORCED_PROXY';
        $base['reasons'][]='Proxy nuceného výprodeje: výrazný pěti- i dvacetisvíčkový pokles, ≥4 klesající dny a ≥2 široké medvědí svíčky.';
    } elseif ($features['panic']) {
        $base['setup']='PANIC';
        $base['reasons'][]='Panický výprodej – cenová proxy: denní propad ≥2 %, pokles ≥1,25 předchozího ATR, rozpětí ≥1,4 ATR a Close poblíž Low.';
    } elseif ($features['pressure']) {
        $base['setup']='CONTINUATION';
        $base['reasons'][]='Pokračující tlak: pětidenní pokles alespoň 4 %, nejméně tři poklesové dny a slabé uzavření či průraz 20svíčkového Low.';
    } elseif ($features['ret5']<=-3.0) {
        $base['setup']='WATCH';
        $base['reasons'][]='Slabost ceny během posledních pěti svíček bez plného signálu paniky či obratu.';
    } else {
        $base['reasons'][]='Nezjištěna dostatečně neobvyklá výprodejová aktivita podle pravidel v0.1.';
    }
    $base['primary']=$base['setup'];
    $base['reasons'][]='Změna za 1 / 5 / 20 D1: ' .
        number_format($features['ret1'],1,'.','') . ' / ' .
        number_format($features['ret5'],1,'.','') . ' / ' .
        number_format($features['ret20'],1,'.','') . ' %.';
    $base['reasons'][]='Rozpětí poslední svíčky / předchozí ATR14: ' .
        number_format($features['range_atr'],2,'.','') . '×; uzavření v ' .
        number_format($features['clv']*100,0,'.','') . ' % jejího rozpětí.';
    $base['reasons'][]='Transparentní počet tlakových bodů: ' .
        $features['points'] . '/9; není to pravděpodobnost ani predikce výnosu.';

    if ($features['tick_ratio'] !== null) {
        $base['reasons'][]='Tick volume poslední D1 / průměr předchozích 20 D1: ' .
            number_format($features['tick_ratio'],2,'.','') . '×.';
        if ($features['tick_ratio']>=1.5)
            $base['reasons'][]='Zvýšená tick aktivita podporuje pozorování výprodeje; není to objem obchodů na burze.';
    } else {
        $base['warnings'][]='Tick volume pro poslední den chybí nebo je nulové. Potvrzení zvýšené aktivity není možné.';
    }
    if ($reversal || $exhaustion) {
        $base['warnings'][]='Možný obrat po výprodeji je hypotéza. Cena může znovu klesat, nejde o BUY pokyn.';
    }
    if ($features['panic'] || $features['forced']) {
        $base['warnings'][]='Silný pokles nemusí být koncem výprodeje; bez dalších dat nejde určit jeho příčinu.';
    }
    if ($prevPanic !== null)
        $base['reasons'][]='Předchozí epizoda výprodejového tlaku: před ' . $prevPanic . ' dokončenými svíčkami.';
    return $base;
}
