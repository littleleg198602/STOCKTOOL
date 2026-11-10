<?php
declare(strict_types=1);
require __DIR__ . '/common.php';
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') {
    header('Allow: GET');
    respond(405, ['ok'=>false, 'error'=>'get_required']);
}
$cfg = setup();
$datasets = [];
foreach (glob($cfg['store'] . DIRECTORY_SEPARATOR . '*.json') ?: [] as $path) {
    $fp = @fopen($path, 'rb');
    if (!$fp) continue;
    if (!flock($fp, LOCK_SH)) { fclose($fp); continue; }
    $payload = load_locked($fp);
    flock($fp, LOCK_UN);
    fclose($fp);
    if (!isset($payload['symbol'], $payload['timeframe'], $payload['bars'])) continue;
    $bars = $payload['bars'];
    $count = count($bars);
    $datasets[] = [
        'symbol' => $payload['symbol'],
        'timeframe' => $payload['timeframe'],
        'count' => $count,
        'updated_at' => (int)($payload['updated_at'] ?? 0),
        'last_time' => $count ? (int)$bars[$count - 1]['t'] : null
    ];
}
usort($datasets, fn($a, $b) => strcmp($a['symbol'].$a['timeframe'], $b['symbol'].$b['timeframe']));
respond(200, ['ok'=>true, 'datasets'=>$datasets, 'server_time'=>time()]);
