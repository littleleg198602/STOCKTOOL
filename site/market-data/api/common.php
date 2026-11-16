<?php
declare(strict_types=1);
/**
 * Market MT5 API — shares ONLY authentication helpers with Equity Data Manager.
 * MARKET data is physically isolated at stocktool-private/market-data.
 * Equity Data Manager and dependent BUY/SHORT/JOHNY paths are unchanged.
 */
require __DIR__ . '/../../data-manager/api/common.php';
function market_setup(bool $allowBrowserSession = false): array {
    // setup() performs the existing protected key / HttpOnly session validation.
    setup($allowBrowserSession);
    $store = private_dir() . DIRECTORY_SEPARATOR . 'market-data';
    if (!is_dir($store) && !@mkdir($store, 0700, true) && !is_dir($store)) {
        respond(503, ['ok'=>false,'error'=>'market_storage_unavailable']);
    }
    return ['store'=>$store];
}
function market_validate_symbol(string $symbol): string {
    $symbol = strtoupper(trim($symbol));
    // Only literal broker symbol characters, never path separators.
    if (!preg_match('/^[A-Z0-9._:#@+\-]{1,40}$/D', $symbol)) {
        respond(422,['ok'=>false,'error'=>'invalid_market_symbol']);
    }
    return $symbol;
}
