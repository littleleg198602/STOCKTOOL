<?php
declare(strict_types=1);
/**
 * StockTool Market Pressure Scanner v0.1.
 * Authenticated read-only analysis in batches for shared FORPSI hosting.
 */
require __DIR__ . '/../../data-manager/api/common.php';
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') {
    header('Allow: GET');
    respond(405, ['ok'=>false,'error'=>'get_required']);
}
$cfg = setup(true);
$offset = max(0, min(20000, (int)($_GET['offset'] ?? 0)));
$limit = max(1, min(50, (int)($_GET['limit'] ?? 30)));
$paths = glob($cfg['store'] . DIRECTORY_SEPARATOR . '*__D1.json') ?: [];
sort($paths, SORT_STRING);
$total = count($paths);
$batch = array_slice($paths, $offset, $limit);
define('STOCKTOOL_PRESSURE_RULES', true);
require __DIR__ . '/pressure_rules.php';

$now = time();
$results = []; $errors = 0;
foreach ($batch as $path) {
    $fp = @fopen($path, 'rb');
    if (!$fp) { $errors++; continue; }
    if (!@flock($fp, LOCK_SH)) { fclose($fp); $errors++; continue; }
    $raw = stream_get_contents($fp);
    flock($fp, LOCK_UN);
    fclose($fp);
    if (!is_string($raw) || $raw === '') { $errors++; continue; }
    $dataset = json_decode($raw, true);
    if (!is_array($dataset) || ($dataset['timeframe'] ?? '') !== 'D1' ||
        !is_array($dataset['bars'] ?? null)) {
        $errors++; continue;
    }
    $row = mp_analyze($dataset, $now);
    if (preg_match('/^[A-Z0-9._:-]{1,30}$/D', $row['symbol'])) {
        $results[] = $row;
    } else {
        $errors++;
    }
}
respond(200, [
    'ok'=>true, 'version'=>'market-pressure-v0.1','source'=>'MT5 D1 OHLCV',
    'total'=>$total,'offset'=>$offset,'limit'=>$limit,
    'scanned'=>count($batch),'errors'=>$errors,
    'server_time'=>$now,'results'=>$results
]);
