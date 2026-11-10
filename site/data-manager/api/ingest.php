<?php
declare(strict_types=1);
require __DIR__ . '/common.php';
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    header('Allow: POST');
    respond(405, ['ok' => false, 'error' => 'post_required']);
}
$cfg = setup();
$length = (int)($_SERVER['CONTENT_LENGTH'] ?? 0);
if ($length <= 0 || $length > 512000) {
    respond(413, ['ok' => false, 'error' => 'body_size_invalid']);
}
$body = file_get_contents('php://input');
if ($body === false || strlen($body) > 512000) {
    respond(413, ['ok' => false, 'error' => 'body_size_invalid']);
}
$input = json_decode($body, true);
if (!is_array($input) || !isset($input['symbol'], $input['timeframe'], $input['bars']) ||
    !is_string($input['symbol']) || !is_string($input['timeframe']) || !is_array($input['bars'])) {
    respond(422, ['ok' => false, 'error' => 'invalid_request']);
}
$symbol = validate_symbol($input['symbol']);
$timeframe = validate_timeframe($input['timeframe']);
$received = $input['bars'];
if (count($received) < 1 || count($received) > 300) {
    respond(422, ['ok' => false, 'error' => 'bars_limit_1_to_300']);
}
$clean = [];
foreach ($received as $bar) {
    if (!is_array($bar)) respond(422, ['ok' => false, 'error' => 'invalid_bar']);
    foreach (['t','o','h','l','c','v'] as $key) {
        if (!isset($bar[$key]) || !is_numeric($bar[$key])) {
            respond(422, ['ok' => false, 'error' => 'invalid_bar_field']);
        }
    }
    $t = (int)$bar['t']; // Unix seconds, as sent by MT5 CopyRates.
    $o = (float)$bar['o']; $h = (float)$bar['h'];
    $l = (float)$bar['l']; $c = (float)$bar['c'];
    $v = (float)$bar['v'];
    if ($t < 946684800 || $t > time() + 86400 ||
        !is_finite($o) || !is_finite($h) || !is_finite($l) || !is_finite($c) || !is_finite($v) ||
        $h < max($o, $l, $c) || $l > min($o, $h, $c) || $v < 0) {
        respond(422, ['ok' => false, 'error' => 'invalid_bar_values']);
    }
    $clean[(string)$t] = ['t' => $t, 'o' => $o, 'h' => $h, 'l' => $l, 'c' => $c, 'v' => $v];
}

$path = data_path($cfg['store'], $symbol, $timeframe);
$fp = @fopen($path, 'c+');
if ($fp === false || !flock($fp, LOCK_EX)) {
    respond(503, ['ok' => false, 'error' => 'storage_lock_failed']);
}
$old = load_locked($fp);
$combined = [];
foreach (($old['bars'] ?? []) as $bar) {
    if (isset($bar['t'])) $combined[(string)$bar['t']] = $bar;
}
foreach ($clean as $t => $bar) $combined[(string)$t] = $bar;
ksort($combined, SORT_NUMERIC);
$bars = array_values($combined);
if (count($bars) > 20000) $bars = array_slice($bars, -20000);
$output = [
    'symbol' => $symbol, 'timeframe' => $timeframe,
    'updated_at' => time(), 'bars' => $bars
];
$encoded = json_encode($output, JSON_UNESCAPED_SLASHES);
if ($encoded === false || ftruncate($fp, 0) === false || rewind($fp) === false ||
    fwrite($fp, $encoded) !== strlen($encoded) || fflush($fp) === false) {
    flock($fp, LOCK_UN);
    fclose($fp);
    respond(503, ['ok' => false, 'error' => 'storage_write_failed']);
}
flock($fp, LOCK_UN);
fclose($fp);
respond(200, ['ok' => true, 'symbol' => $symbol, 'timeframe' => $timeframe, 'received' => count($clean), 'stored' => count($bars)]);
