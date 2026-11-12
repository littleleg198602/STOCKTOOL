<?php
declare(strict_types=1);
require __DIR__ . '/common.php';

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    header('Allow: POST');
    respond(405, ['ok'=>false, 'error'=>'post_required']);
}
// Reject cross-site requests. The raw StockTool secret is only accepted over HTTPS.
$origin = (string)($_SERVER['HTTP_ORIGIN'] ?? '');
$hostname = (string)($_SERVER['HTTP_HOST'] ?? '');
if ($origin !== '' && (
    !in_array(parse_url($origin, PHP_URL_SCHEME), ['https'], true) ||
    strcasecmp((string)parse_url($origin, PHP_URL_HOST), preg_replace('/:\d+$/', '', $hostname)) !== 0
)) {
    respond(403, ['ok'=>false, 'error'=>'origin_not_allowed']);
}
// setup() always requires the original header key (a browser session alone
// cannot log in or elevate permissions); Python MT5 key-only ingestion is unchanged.
setup();
start_stocktool_session();
session_regenerate_id(true);
$_SESSION['authorized'] = true;
$_SESSION['key_hash'] = hash('sha256', private_key());
$_SESSION['valid_until'] = time() + STOCKTOOL_SESSION_LIFETIME;
session_write_close();
respond(200, [
    'ok'=>true,
    'authenticated'=>true,
    'expires_in_days'=>30,
    'message'=>'stocktool_session_created'
]);
