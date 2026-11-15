<?php
declare(strict_types=1);
require __DIR__ . '/storage.php';
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') {
    header('Allow: GET'); respond(405, ['ok'=>false,'error'=>'get_required']);
}
$kind = (string)($_GET['kind'] ?? 'results');
if (!in_array($kind, ['manifest','database','results','history'], true)) {
    respond(422, ['ok'=>false,'error'=>'invalid_kind']);
}
// A browser session can read results; only a key-authenticated worker can read the DB.
setup($kind !== 'database');
$root = score_root();
$manifest = score_manifest($root);
if ($kind === 'manifest') respond(200, ['ok'=>true] + $manifest);
if ($kind === 'history') {
    $items = [];
    $revision = $manifest['revision'];
    // Follow only committed revisions. A crash before changing current.json may
    // leave a staged generation on disk, which must not appear in history.
    while ($revision !== 'empty' && count($items) < 100) {
        $revision = score_revision($revision);
        $file = $root . '/' . $revision . '/summary.json';
        if (!is_file($file)) break;
        $summary = json_decode((string)file_get_contents($file), true);
        if (!is_array($summary)) break;
        $items[] = $summary;
        $revision = (string)($summary['previous_revision'] ?? 'empty');
    }
    usort($items, static function(array $a, array $b): int {
        return strcmp((string)$b['generated_at'], (string)$a['generated_at']);
    });
    respond(200, ['ok'=>true, 'runs'=>$items]);
}
if ($manifest['revision'] === 'empty') respond(200, ['ok'=>true, 'empty'=>true]);
$revision = score_revision((string)($_GET['revision'] ?? $manifest['revision']));
$file = $root . '/' . $revision . ($kind === 'database' ? '/history.sqlite' : '/result.json');
if (!is_file($file)) respond(404, ['ok'=>false,'error'=>'revision_not_found']);
header('Content-Type: ' . ($kind === 'database' ? 'application/octet-stream' : 'application/json; charset=utf-8'));
header('Content-Length: ' . (string)filesize($file));
if ($kind === 'database') header('Content-Disposition: attachment; filename="history.sqlite"');
readfile($file);
