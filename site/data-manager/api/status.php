<?php
declare(strict_types=1);
require __DIR__ . '/common.php';
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') {
    header('Allow: GET'); respond(405, ['ok'=>false, 'error'=>'get_required']);
}
// Status endpoint does not reveal credentials, environment or data.
$configured = is_file(private_dir() . DIRECTORY_SEPARATOR . 'config.php');
respond(200, ['ok'=>true, 'configured'=>$configured, 'api'=>'stocktool-mt5-bridge-v1']);
