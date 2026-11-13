<?php
declare(strict_types=1);

/**
 * StockTool SHORT Scanner v0.1.
 * Separate, read-only bearish-structure screener. Uses stored broker MT5 D1
 * OHLCV; it does NOT imply borrow availability or permission to short.
 */
require __DIR__ . '/../../data-manager/api/common.php';
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') {
    header('Allow: GET');
    respond(405, ['ok' => false, 'error' => 'get_required']);
}
$cfg = setup(true);
$offset = max(0, min(20000, (int)($_GET['offset'] ?? 0)));
$limit = max(1, min(60, (int)($_GET['limit'] ?? 35)));
$files = glob($cfg['store'] . DIRECTORY_SEPARATOR . '*__D1.json') ?: [];
sort($files, SORT_STRING);
$total = count($files);
$batch = array_slice($files, $offset, $limit);

function sh_mean(array $values, int $length, int $shift = 0): ?float {
    if ($length < 1 || count($values) < $length + $shift) return null;
    return array_sum(array_slice($values, -($length + $shift), $length)) / $length;
}
function sh_rsi(array $closes): ?float {
    $n = count($closes);
    if ($n < 15) return null;
    $gain = 0.0; $loss = 0.0;
    for ($i = 1; $i <= 14; $i++) {
        $diff = $closes[$i] - $closes[$i - 1];
        $gain += max($diff, 0.0);
        $loss += max(-$diff, 0.0);
    }
    $gain /= 14; $loss /= 14;
    for ($i = 15; $i < $n; $i++) {
        $diff = $closes[$i] - $closes[$i - 1];
        $gain = ($gain * 13 + max($diff, 0.0)) / 14;
        $loss = ($loss * 13 + max(-$diff, 0.0)) / 14;
    }
    if ($loss == 0.0) return $gain == 0.0 ? 50.0 : 100.0;
    return 100.0 - 100.0 / (1.0 + $gain / $loss);
}
function sh_atr(array $bars): ?float {
    if (count($bars) < 15) return null;
    $ranges = [];
    for ($i = 1, $n = count($bars); $i < $n; $i++) {
        $b = $bars[$i];
        $prev = $bars[$i - 1]['c'];
        $ranges[] = max($b['h'] - $b['l'], abs($b['h'] - $prev), abs($b['l'] - $prev));
    }
    $atr = array_sum(array_slice($ranges, 0, 14)) / 14;
    for ($i = 14, $n = count($ranges); $i < $n; $i++) {
        $atr = ($atr * 13 + $ranges[$i]) / 14;
    }
    return $atr;
}
function sh_round(?float $value, int $decimals = 3): ?float {
    return $value === null || !is_finite($value) ? null : round($value, $decimals);
}
function sh_analyze(array $data, int $now): array {
    $map = []; $invalid = 0; $duplicates = 0;
    foreach (($data['bars'] ?? []) as $item) {
        if (!is_array($item) || !isset($item['t'], $item['o'], $item['h'], $item['l'], $item['c'])) {
            $invalid++; continue;
        }
        $t = (int)$item['t'];
        $o = (float)$item['o']; $h = (float)$item['h'];
        $l = (float)$item['l']; $c = (float)$item['c'];
        $v = (float)($item['v'] ?? 0);
        if ($t < 946684800 || $t > $now + 86400 || !is_finite($o) ||
            !is_finite($h) || !is_finite($l) || !is_finite($c) ||
            !is_finite($v) || $o <= 0 || $c <= 0 || $l <= 0 ||
            $h < max($o, $l, $c) || $l > min($o, $h, $c) || $v < 0) {
            $invalid++; continue;
        }
        $id = (string)$t;
        if (isset($map[$id])) $duplicates++;
        $map[$id] = ['t'=>$t,'o'=>$o,'h'=>$h,'l'=>$l,'c'=>$c,'v'=>$v];
    }
    ksort($map, SORT_NUMERIC);
    $bars = array_values($map);
    $n = count($bars);
    $last = $n ? $bars[$n-1] : null;
    $stamp = $last['t'] ?? null;
    $fresh = $stamp !== null && $stamp >= $now - 10 * 86400;
    $out = [
        'symbol' => (string)($data['symbol'] ?? ''), 'timeframe' => 'D1',
        'count' => $n, 'last_time' => $stamp,
        'fresh' => $fresh, 'candidate' => false, 'risk' => false,
        'avoid' => false, 'setup' => 'NONE', 'raw_setup' => 'NONE',
        'close' => $last ? sh_round($last['c'], 6) : null,
        'sma20' => null, 'sma50' => null, 'sma200' => null,
        'rsi14' => null, 'atr_pct' => null, 'ret5_pct' => null,
        'ret20_pct' => null, 'vs_sma50_pct' => null, 'vs_sma200_pct' => null,
        'from_52w_low_pct' => null, 'tick_volume_ratio' => null,
        'invalid_bars' => $invalid, 'duplicate_times' => $duplicates,
        'risk_flags' => [], 'reasons' => []
    ];
    if ($n < 210) {
        $out['setup'] = 'INSUFFICIENT';
        $out['raw_setup'] = 'INSUFFICIENT';
        $out['avoid'] = true;
        $out['reasons'] = ['Nedostatek dokončených denních svíček (minimálně 210).'];
        return $out;
    }
    $closes = array_column($bars, 'c');
    $lows = array_column($bars, 'l');
    $volumes = array_column($bars, 'v');
    $close = $last['c'];
    $sma20 = sh_mean($closes, 20);
    $sma50 = sh_mean($closes, 50);
    $sma50prev = sh_mean($closes, 50, 5);
    $sma200 = sh_mean($closes, 200);
    $rsi = sh_rsi($closes);
    $atr = sh_atr($bars);
    $atrPct = $atr / $close * 100;
    $return5 = ($close / $closes[$n-6] - 1.0) * 100;
    $return20 = ($close / $closes[$n-21] - 1.0) * 100;
    $vs50 = ($close / $sma50 - 1.0) * 100;
    $vs200 = ($close / $sma200 - 1.0) * 100;
    $yearLow = min(array_slice($lows, -min(252, $n)));
    $lowDistance = ($close / $yearLow - 1.0) * 100;
    $prior20Low = min(array_slice($lows, -21, 20));
    $vol20 = sh_mean($volumes, 20);
    $priorVol20 = sh_mean($volumes, 20, 20);
    $volumeRatio = $priorVol20 > 0 ? $vol20 / $priorVol20 : null;
    $downtrend = $close < $sma200 && $sma50 < $sma200 && $sma50 < $sma50prev;
    $below50 = $close < $sma50;
    $bearishCandle = $last['c'] < $last['o'];
    $reasons = [];
    $reasons[] = $downtrend
        ? 'Klesající dlouhodobý trend: close i SMA50 pod SMA200 a SMA50 klesá.'
        : 'Plný dlouhodobý klesající trend není potvrzen.';
    $reasons[] = 'RSI(14): ' . number_format($rsi, 1, '.', '') .
        '; 20denní výnos: ' . number_format($return20, 1, '.', '') . ' %.';
    $raw = 'NONE';
    // Separate SELL/SHORT rules; not an inversion of BUY Scanner.
    if ($downtrend && $close < $prior20Low && $rsi >= 30 && $rsi <= 60) {
        $raw = 'BREAKDOWN';
        $reasons[] = 'Close prorazil minimum předchozích 20 dokončených svíček.';
    } elseif ($downtrend && $below50 && $last['h'] >= 0.98*$sma50 &&
              $bearishCandle && $rsi >= 32 && $rsi <= 65) {
        $raw = 'FAILED_RALLY';
        $reasons[] = 'Neúspěšný návrat k SMA50: denní high v blízkosti SMA50, poklesová svíčka uzavřela pod SMA50.';
    } elseif ($downtrend && $below50 && $return20 <= -3.0 &&
              $rsi >= 30 && $rsi <= 65) {
        $raw = 'DOWNTREND';
        $reasons[] = 'Pokračující slabost: klesající trend a nejméně 3% pokles za 20 svíček.';
    } elseif ($close < $sma200 && ($below50 || $return20 < -3.0)) {
        $raw = 'WATCH';
        $reasons[] = 'Akcie je slabá, ale technická SHORT formace není potvrzena.';
    } else {
        $reasons[] = 'Aktuální technická struktura nesplňuje SHORT filtr.';
    }

    // Short squeeze / snapback risks. Flags are intentionally conservative:
    // low RSI, steep decline, excessive volatility can invalidate entry.
    $riskFlags = [];
    if ($rsi < 30.0) $riskFlags[] = 'RSI pod 30: překoupení shortů / riziko rychlého odrazu.';
    if ($vs50 < -12.0) $riskFlags[] = 'Cena více než 12 % pod SMA50: protažený pokles.';
    if ($return5 <= -15.0) $riskFlags[] = 'Více než 15% propad za 5 svíček: riziko prudké korekce.';
    if ($atrPct >= 7.0) $riskFlags[] = 'ATR nad 7 % ceny: vysoká denní volatilita.';
    if ($n >= 2 && $last['c'] / $bars[$n-2]['c'] >= 1.10)
        $riskFlags[] = 'Poslední svíčka rostla více než 10 %: riziko obratu / squeeze.';
    if ($invalid > 0 || $duplicates > 0)
        $riskFlags[] = 'Historie má neplatné nebo duplicitní svíčky.';

    $isTechnicalShort = in_array($raw, ['BREAKDOWN','FAILED_RALLY','DOWNTREND'], true);
    $risky = count($riskFlags) > 0;
    $setup = $raw;
    if (!$fresh) {
        $setup = 'STALE';
        $reasons[] = 'Poslední denní svíčka je starší než 10 kalendářních dní.';
    } elseif ($isTechnicalShort && $risky) {
        $setup = 'AVOID';
        $reasons[] = 'Formace existuje, ale zvýšené riziko odrazu/volatility ji vyřazuje.';
    }
    foreach ($riskFlags as $flag) $reasons[] = $flag;
    $out['raw_setup'] = $raw;
    $out['setup'] = $setup;
    $out['candidate'] = $fresh && $isTechnicalShort && !$risky;
    $out['risk'] = $fresh && $risky && $close < $sma200;
    $out['avoid'] = !$fresh || $risky || $raw === 'NONE';
    $out['sma20'] = sh_round($sma20, 5);
    $out['sma50'] = sh_round($sma50, 5);
    $out['sma200'] = sh_round($sma200, 5);
    $out['rsi14'] = sh_round($rsi, 2);
    $out['atr_pct'] = sh_round($atrPct, 2);
    $out['ret5_pct'] = sh_round($return5, 2);
    $out['ret20_pct'] = sh_round($return20, 2);
    $out['vs_sma50_pct'] = sh_round($vs50, 2);
    $out['vs_sma200_pct'] = sh_round($vs200, 2);
    $out['from_52w_low_pct'] = sh_round($lowDistance, 2);
    $out['tick_volume_ratio'] = sh_round($volumeRatio, 2);
    $out['risk_flags'] = $riskFlags;
    $out['reasons'] = $reasons;
    return $out;
}

$now = time();
$results = [];
$errors = 0;
foreach ($batch as $path) {
    $fp = @fopen($path, 'rb');
    if (!$fp) { $errors++; continue; }
    if (!@flock($fp, LOCK_SH)) { fclose($fp); $errors++; continue; }
    $raw = stream_get_contents($fp);
    flock($fp, LOCK_UN);
    fclose($fp);
    if (!is_string($raw) || $raw === '') { $errors++; continue; }
    $decoded = json_decode($raw, true);
    if (!is_array($decoded) || ($decoded['timeframe'] ?? '') !== 'D1' ||
        !is_array($decoded['bars'] ?? null)) {
        $errors++; continue;
    }
    $item = sh_analyze($decoded, $now);
    if (preg_match('/^[A-Z0-9._:-]{1,30}$/D', $item['symbol'])) {
        $results[] = $item;
    } else {
        $errors++;
    }
}
respond(200, [
    'ok'=>true,'version'=>'short-scanner-v0.1','source'=>'MT5 D1',
    'total'=>$total,'offset'=>$offset,'limit'=>$limit,
    'scanned'=>count($batch),'errors'=>$errors,'server_time'=>$now,
    'results'=>$results
]);