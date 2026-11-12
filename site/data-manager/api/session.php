<?php
declare(strict_types=1);
require __DIR__ . '/common.php';

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') {
    header('Allow: GET');
    respond(405, ['ok'=>false,'error'=>'get_required']);
}
$authenticated = valid_stocktool_session();
respond(200, [
    'ok'=>true,
    'authenticated'=>$authenticated,
    'expires_in_days'=>$authenticated ? 30 : 0
]);
