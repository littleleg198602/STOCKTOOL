<?php
declare(strict_types=1);
require __DIR__ . '/common.php';
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') {
    header('Allow: GET');
    respond(405, ['ok'=>false, 'error'=>'get_required']);
}
$cfg = setup();
$datasets = [];

// Files are much smaller than OHLCV datasets and can be listed frequently.
foreach (glob($cfg['store'] . DIRECTORY_SEPARATOR . '*.meta.json') ?: [] as $path) {
    $raw = @file_get_contents($path);
    if (!$raw) continue;
    $meta = json_decode($raw, true);
    if (!is_array($meta) || !isset($meta['symbol'], $meta['timeframe'])) continue;
    $datasets[$meta['symbol'].'|'.$meta['timeframe']] = [
        'symbol' => $meta['symbol'],
        'timeframe' => $meta['timeframe'],
        'count' => max(0, (int)($meta['count'] ?? 0)),
        'updated_at' => (int)($meta['updated_at'] ?? 0),
        'last_time' => isset($meta['last_time']) ? (int)$meta['last_time'] : null,
    ];
}

// Legacy compatibility: read data files without their small metadata sibling.
// This path is used only once, until the MT5 bridge updates that dataset.
foreach (glob($cfg['store'] . DIRECTORY_SEPARATOR . '*.json') ?: [] as $path) {
    if (str_ends_with($path, '.meta.json')) continue;
    $metaPath = substr($path, 0, -5) . '.meta.json';
    if (is_file($metaPath)) continue;
    $fp = @fopen($path, 'rb');
    if (!$fp) continue;
    if (!flock($fp, LOCK_SH)) { fclose($fp); continue; }
    $payload = load_locked($fp);
    flock($fp, LOCK_UN);
    fclose($fp);
    if (!isset($payload['symbol'], $payload['timeframe'], $payload['bars']) ||
        !is_array($payload['bars'])) continue;
    $bars = $payload['bars'];
    $count = count($bars);
    $item = [
        'symbol'=>$payload['symbol'], 'timeframe'=>$payload['timeframe'],
        'count'=>$count, 'updated_at'=>(int)($payload['updated_at'] ?? 0),
        'last_time'=>$count ? (int)$bars[$count-1]['t'] : null
    ];
    $datasets[$item['symbol'].'|'.$item['timeframe']] = $item;
}
$datasets = array_values($datasets);
usort($datasets, static function($a,$b): int {
    $name = strcmp($a['symbol'], $b['symbol']);
    return $name ?: strcmp($a['timeframe'], $b['timeframe']);
});
respond(200, ['ok'=>true, 'datasets'=>$datasets, 'server_time'=>time()]);
