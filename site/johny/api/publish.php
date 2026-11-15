<?php
declare(strict_types=1);
require __DIR__ . '/storage.php';
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    header('Allow: POST'); respond(405, ['ok'=>false,'error'=>'post_required']);
}
setup(); // Publishing always requires a header key; a browser session cannot write state.
$result = $_POST['result'] ?? null;
$expected = $_POST['expected_revision'] ?? null;
$upload = $_FILES['database'] ?? null;
if (!is_string($result) || strlen($result) > SCORE_RESULT_LIMIT || !is_string($expected)
    || ($expected !== 'empty' && !preg_match('/^[a-f0-9]{32}$/D', $expected))) {
    respond(422, ['ok'=>false,'error'=>'invalid_publish_request_or_php_post_limit']);
}
$payload = json_decode($result, true);
if (!is_array($payload) || ($payload['schema_version'] ?? null) !== 1
    || !is_array($payload['signals'] ?? null) || count($payload['signals']) < 1
    || count($payload['signals']) > 1000 || !is_array($payload['metadata'] ?? null)
    || !is_string($payload['generated_at'] ?? null) || strtotime($payload['generated_at']) === false
    || !is_int($payload['run_id'] ?? null) || $payload['run_id'] < 1
    || !is_array($payload['learning'] ?? null)) {
    respond(422, ['ok'=>false,'error'=>'invalid_result_schema']);
}
if (!is_array($upload) || ($upload['error'] ?? -1) !== UPLOAD_ERR_OK
    || !is_uploaded_file($upload['tmp_name']) || $upload['size'] < 100
    || $upload['size'] > SCORE_DB_LIMIT) {
    respond(413, ['ok'=>false,'error'=>'database_upload_failed_check_php_limits']);
}
$handle = fopen($upload['tmp_name'], 'rb');
$magic = $handle ? fread($handle, 16) : false;
if ($handle) fclose($handle);
if ($magic !== "SQLite format 3\0") respond(422, ['ok'=>false,'error'=>'invalid_database']);

$root = score_root();
$lock = fopen($root . '/publish.lock', 'c');
if (!$lock || !flock($lock, LOCK_EX)) respond(503, ['ok'=>false,'error'=>'publication_lock_failed']);
$current = score_manifest($root);
if (!hash_equals($current['revision'], $expected)) {
    flock($lock, LOCK_UN); fclose($lock);
    respond(409, ['ok'=>false,'error'=>'state_changed_restore_and_recompute']);
}
$revision = bin2hex(random_bytes(16));
$directory = $root . '/' . $revision;
if (!mkdir($directory, 0700)) respond(503, ['ok'=>false,'error'=>'publication_failed']);
$payload['ok'] = true;
$payload['revision'] = $revision;
$summary = ['revision'=>$revision, 'previous_revision'=>$current['revision'], 'generated_at'=>$payload['generated_at'],
    'run_id'=>$payload['run_id'], 'count'=>count($payload['signals']),
    'learning_status'=>$payload['learning']['status'] ?? 'UNKNOWN'];
$manifest = $summary + ['database_sha256'=>hash_file('sha256', $upload['tmp_name'])];
$files = [
    $directory . '/result.json' => json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES),
    $directory . '/summary.json' => json_encode($summary),
    $root . '/current.next.json' => json_encode($manifest)
];
$ok = move_uploaded_file($upload['tmp_name'], $directory . '/history.sqlite');
foreach ($files as $file => $contents) {
    if ($contents === false || file_put_contents($file, $contents, LOCK_EX) !== strlen($contents)) $ok = false;
}
// The pointer changes only after the DB and result have both been written successfully.
if (!$ok || !rename($root . '/current.next.json', $root . '/current.json')) {
    foreach (array_keys($files) as $file) if (is_file($file)) @unlink($file);
    @unlink($directory . '/history.sqlite'); @rmdir($directory);
    flock($lock, LOCK_UN); fclose($lock);
    respond(503, ['ok'=>false,'error'=>'publication_failed_previous_state_retained']);
}
@chmod($directory . '/history.sqlite', 0600);
flock($lock, LOCK_UN); fclose($lock);
respond(200, ['ok'=>true,'revision'=>$revision]);
