<?php
declare(strict_types=1);
require __DIR__ . '/common.php';

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    header('Allow: POST');
    respond(405, ['ok'=>false,'error'=>'post_required']);
}
$origin = (string)($_SERVER['HTTP_ORIGIN'] ?? '');
$hostname = (string)($_SERVER['HTTP_HOST'] ?? '');
if ($origin !== '' && (
    parse_url($origin, PHP_URL_SCHEME) !== 'https' ||
    strcasecmp((string)parse_url($origin, PHP_URL_HOST), preg_replace('/:\d+$/', '', $hostname)) !== 0
)) {
    respond(403, ['ok'=>false,'error'=>'origin_not_allowed']);
}
if (!empty($_COOKIE[STOCKTOOL_SESSION_NAME])) {
    start_stocktool_session();
    $_SESSION = [];
    session_destroy();
}
setcookie(STOCKTOOL_SESSION_NAME, '', [
    'expires'=>time()-3600,
    'path'=>'/test/',
    'domain'=>'stocktool.eu',
    'secure'=>true,
    'httponly'=>true,
    'samesite'=>'Lax'
]);
respond(200, ['ok'=>true,'authenticated'=>false]);
