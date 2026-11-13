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

define('STOCKTOOL_SHORT_RULES', true);
require __DIR__ . '/short_rules.php';

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