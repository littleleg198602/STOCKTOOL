<?php
declare(strict_types=1);

/**
 * StockTool BUY Scanner v0.1 – transparent D1 price/volume screening.
 * Shares ONLY the read-only MT5 storage and API authentication with Data Manager.
 * No external sources, no orders, no fundamentals or simulated order flow.
 * Batches protect shared FORPSI hosting from expensive full-universe reads.
 */
require __DIR__ . '/../../data-manager/api/common.php';

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') {
    header('Allow: GET');
    respond(405, ['ok' => false, 'error' => 'get_required']);
}
$cfg = setup(true); // accepts secure browser session or original API key
$offset = max(0, min(20000, (int)($_GET['offset'] ?? 0)));
$limit = max(1, min(80, (int)($_GET['limit'] ?? 60)));
$paths = glob($cfg['store'] . DIRECTORY_SEPARATOR . '*__D1.json') ?: [];
sort($paths, SORT_STRING);
$total = count($paths);
$subset = array_slice($paths, $offset, $limit);

define('STOCKTOOL_BUY_RULES', true);
require __DIR__ . '/buy_rules.php';

$now = time();
$results = [];
$errors = 0;
foreach ($subset as $path) {
    $fp = @fopen($path, 'rb');
    if ($fp === false) { $errors++; continue; }
    if (!@flock($fp, LOCK_SH)) { fclose($fp); $errors++; continue; }
    $raw = stream_get_contents($fp);
    flock($fp, LOCK_UN); fclose($fp);
    if (!is_string($raw) || $raw === '') { $errors++; continue; }
    $payload = json_decode($raw, true);
    if (!is_array($payload) || ($payload['timeframe'] ?? '') !== 'D1') {
        $errors++; continue;
    }
    $result = analyze_dataset($payload, $now);
    if (preg_match('/^[A-Z0-9._:-]{1,30}$/D', $result['symbol'])) {
        $results[] = $result;
    } else { $errors++; }
}
respond(200, [
    'ok'=>true,'version'=>'buy-scanner-v0.1','source'=>'MT5 D1',
    'total'=>$total,'offset'=>$offset,'limit'=>$limit,'scanned'=>count($subset),
    'errors'=>$errors,'server_time'=>$now,'results'=>$results
]);
