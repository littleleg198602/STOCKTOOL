<?php
declare(strict_types=1);
require_once __DIR__ . '/../../data-manager/api/common.php';

const SCORE_DB_LIMIT = 134217728;
const SCORE_RESULT_LIMIT = 16777216;

function score_root(): string {
    $root = private_dir() . DIRECTORY_SEPARATOR . 'johny';
    if (!is_dir($root) && !@mkdir($root, 0700, true) && !is_dir($root)) {
        respond(503, ['ok'=>false, 'error'=>'score_storage_unavailable']);
    }
    return $root;
}

function score_manifest(string $root): array {
    $file = $root . '/current.json';
    if (!is_file($file)) return ['revision'=>'empty'];
    $data = json_decode((string)file_get_contents($file), true);
    if (!is_array($data) || !preg_match('/^[a-f0-9]{32}$/D', (string)($data['revision'] ?? ''))) {
        respond(500, ['ok'=>false, 'error'=>'score_state_corrupt']);
    }
    return $data;
}

function score_revision(string $revision): string {
    if (!preg_match('/^[a-f0-9]{32}$/D', $revision)) {
        respond(422, ['ok'=>false, 'error'=>'invalid_revision']);
    }
    return $revision;
}
