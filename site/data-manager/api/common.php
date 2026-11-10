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

function setup(): array {
    $private = private_dir();
    $path = $private . DIRECTORY_SEPARATOR . 'config.php';
    if (!is_file($path)) {
        respond(503, ['ok' => false, 'error' => 'not_configured']);
    }
    $config = require $path;
    $key = is_array($config) ? ($config['api_key'] ?? '') : '';
    if (!is_string($key) || strlen($key) < 32 || strpos($key, 'SEM_VLOZ') !== false) {
        respond(503, ['ok' => false, 'error' => 'invalid_private_configuration']);
    }
    $provided = $_SERVER['HTTP_X_STOCKTOOL_KEY'] ?? '';
    if (!is_string($provided) || !hash_equals($key, $provided)) {
        respond(401, ['ok' => false, 'error' => 'invalid_api_key']);
    }
    $store = $private . DIRECTORY_SEPARATOR . 'data';
    if (!is_dir($store) && !@mkdir($store, 0700, true) && !is_dir($store)) {
        respond(503, ['ok' => false, 'error' => 'storage_unavailable']);
    }
    return ['store' => $store];
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
