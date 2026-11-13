<?php
declare(strict_types=1);
/**
 * StockTool MT5 Bridge API.
 * Requires private config outside the public www directory:
 * /stocktool.eu/stocktool-private/config.php
 */
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, private');
header('X-Content-Type-Options: nosniff');

function respond(int $code, array $payload): void {
    http_response_code($code);
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE);
    exit;
}

function private_dir(): string {
    // /stocktool.eu/www/test/data-manager/api -> /stocktool.eu/stocktool-private
    return dirname(__DIR__, 4) . DIRECTORY_SEPARATOR . 'stocktool-private';
}

/**
 * Shared StockTool login for Data Manager, BUY Scanner and SHORT Scanner.
 * The PHP session contains only authorization state, NOT the raw API key.
 * The browser receives an HttpOnly + Secure + SameSite cookie.
 */
const STOCKTOOL_SESSION_NAME = 'STOCKTOOL_AUTH';
const STOCKTOOL_SESSION_LIFETIME = 2592000; // rolling 30 days

function private_key(): string {
    $path = private_dir() . DIRECTORY_SEPARATOR . 'config.php';
    if (!is_file($path)) respond(503, ['ok'=>false,'error'=>'not_configured']);
    $config = require $path;
    $key = is_array($config) ? ($config['api_key'] ?? '') : '';
    if (!is_string($key) || strlen($key) < 32 || strpos($key, 'SEM_VLOZ') !== false) {
        respond(503, ['ok'=>false,'error'=>'invalid_private_configuration']);
    }
    return $key;
}

function start_stocktool_session(): void {
    if (session_status() === PHP_SESSION_ACTIVE) return;
    $sessions = private_dir() . DIRECTORY_SEPARATOR . 'sessions';
    if (!is_dir($sessions) && !@mkdir($sessions, 0700, true) && !is_dir($sessions)) {
        respond(503, ['ok'=>false,'error'=>'session_storage_unavailable']);
    }
    ini_set('session.use_strict_mode', '1');
    ini_set('session.use_only_cookies', '1');
    ini_set('session.gc_maxlifetime', (string)STOCKTOOL_SESSION_LIFETIME);
    // Keep sessions away from the hoster's shared PHP session folder.
    session_save_path($sessions);
    session_name(STOCKTOOL_SESSION_NAME);
    session_set_cookie_params([
        'lifetime' => STOCKTOOL_SESSION_LIFETIME,
        'path' => '/test/',
        'domain' => 'stocktool.eu',
        'secure' => true,
        'httponly' => true,
        'samesite' => 'Lax'
    ]);
    if (!session_start()) respond(503, ['ok'=>false,'error'=>'session_unavailable']);
}

function valid_stocktool_session(): bool {
    if (empty($_COOKIE[STOCKTOOL_SESSION_NAME])) return false;
    start_stocktool_session();
    $valid = isset($_SESSION['authorized'], $_SESSION['key_hash'], $_SESSION['valid_until'])
        && $_SESSION['authorized'] === true
        && (int)$_SESSION['valid_until'] >= time()
        && is_string($_SESSION['key_hash'])
        && hash_equals($_SESSION['key_hash'], hash('sha256', private_key()));
    if ($valid) {
        // Active browser stays signed in; an unused browser expires after 30 days.
        $_SESSION['valid_until'] = time() + STOCKTOOL_SESSION_LIFETIME;
        $params = session_get_cookie_params();
        setcookie(STOCKTOOL_SESSION_NAME, session_id(), [
            'expires' => time() + STOCKTOOL_SESSION_LIFETIME,
            'path' => $params['path'],
            'domain' => $params['domain'],
            'secure' => true,
            'httponly' => true,
            'samesite' => 'Lax'
        ]);
    }
    session_write_close();
    return $valid;
}

function setup(bool $allowBrowserSession = false): array {
    $private = private_dir();
    $key = private_key();
    $provided = $_SERVER['HTTP_X_STOCKTOOL_KEY'] ?? '';
    $keyMatch = is_string($provided) && hash_equals($key, $provided);
    if (!$keyMatch && (!$allowBrowserSession || !valid_stocktool_session())) {
        respond(401, ['ok'=>false,'error'=>'invalid_api_key']);
    }
    $store = $private . DIRECTORY_SEPARATOR . 'data';
    if (!is_dir($store) && !@mkdir($store, 0700, true) && !is_dir($store)) {
        respond(503, ['ok'=>false,'error'=>'storage_unavailable']);
    }
    return ['store'=>$store];
}

function validate_symbol(string $symbol): string {
    $symbol = strtoupper(trim($symbol));
    if (!preg_match('/^[A-Z0-9._:-]{1,30}$/D', $symbol)) {
        respond(422, ['ok' => false, 'error' => 'invalid_symbol']);
    }
    return $symbol;
}

function validate_timeframe(string $timeframe): string {
    $timeframe = strtoupper(trim($timeframe));
    if (!in_array($timeframe, ['M1','M5','M15','M30','H1','H4','D1','W1'], true)) {
        respond(422, ['ok' => false, 'error' => 'invalid_timeframe']);
    }
    return $timeframe;
}

function data_path(string $root, string $symbol, string $timeframe): string {
    return $root . DIRECTORY_SEPARATOR . rawurlencode($symbol) . '__' . $timeframe . '.json';
}

function load_locked($file): array {
    rewind($file);
    $raw = stream_get_contents($file);
    if ($raw === false || trim($raw) === '') return [];
    $data = json_decode($raw, true);
    if (!is_array($data)) respond(500, ['ok' => false, 'error' => 'storage_corrupt']);
    return $data;
}
