<?php
declare(strict_types=1);
require __DIR__ . '/common.php';
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') {
    header('Allow: GET');
    respond(405, ['ok'=>false, 'error'=>'get_required']);
}
$cfg = setup();
$symbol = validate_symbol((string)($_GET['symbol'] ?? ''));
$timeframe = validate_timeframe((string)($_GET['timeframe'] ?? ''));
$limit = max(1, min(5000, (int)($_GET['limit'] ?? 1000)));
$path = data_path($cfg['store'], $symbol, $timeframe);
if (!is_file($path)) respond(404, ['ok'=>false, 'error'=>'dataset_not_found']);
$fp = @fopen($path, 'rb');
if (!$fp || !flock($fp, LOCK_SH)) respond(503, ['ok'=>false, 'error'=>'storage_unavailable']);
$data = load_locked($fp);
flock($fp, LOCK_UN);
fclose($fp);
$bars = $data['bars'] ?? [];
respond(200, [
    'ok'=>true, 'symbol'=>$symbol, 'timeframe'=>$timeframe,
    'updated_at'=>(int)($data['updated_at'] ?? 0),
    'total'=>count($bars),
    'bars'=>array_slice($bars, -$limit)
]);
