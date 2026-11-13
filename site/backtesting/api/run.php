<?php
declare(strict_types=1);
/**
 * StockTool Backtesting v0.1. Read-only, authenticated, chunked to protect FORPSI.
 */
require __DIR__ . '/../../data-manager/api/common.php';
if (($_SERVER['REQUEST_METHOD'] ?? '')!=='GET') {
    header('Allow: GET');
    respond(405,['ok'=>false,'error'=>'get_required']);
}
$cfg=setup(true);
define('STOCKTOOL_BACKTEST_ENGINE',true);
require __DIR__.'/engine.php';

$strategy=strtoupper(trim((string)($_GET['strategy']??'BUY')));
if($strategy==='ALL') {
    $strategies=BT_STRATEGIES;
} elseif(in_array($strategy,BT_STRATEGIES,true)) {
    $strategies=[$strategy];
} else {
    respond(422,['ok'=>false,'error'=>'invalid_strategy']);
}
$rawH=(string)($_GET['horizons']??'5,20');
if (!preg_match('/^[0-9]{1,2}(,[0-9]{1,2}){0,4}$/D',$rawH)) {
    respond(422,['ok'=>false,'error'=>'invalid_horizons']);
}
$horizons=array_values(array_unique(array_map('intval',explode(',',$rawH))));
sort($horizons,SORT_NUMERIC);
if (!$horizons || count(array_diff($horizons,BT_HORIZONS))) {
    respond(422,['ok'=>false,'error'=>'invalid_horizons']);
}
$costs=[];
foreach (['commission','spread','slippage'] as $field) {
    $value=(string)($_GET[$field]??($field==='commission'?'1':($field==='spread'?'5':'2')));
    if(!preg_match('/^\d{1,2}(?:\.\d{1,2})?$/D',$value)) {
        respond(422,['ok'=>false,'error'=>'invalid_'.$field]);
    }
    $costs[$field]=min(99.99,(float)$value);
}
$offset=max(0,min(20000,(int)($_GET['offset']??0)));
$limit=max(1,min($strategy==='ALL'?4:12,(int)($_GET['limit']??8)));
$paths=glob($cfg['store'].DIRECTORY_SEPARATOR.'*__D1.json')?:[];
sort($paths,SORT_STRING);
$total=count($paths);
$batch=array_slice($paths,$offset,$limit);
$results=[];$errors=0;$now=time();
foreach($batch as $path) {
    $fp=@fopen($path,'rb');
    if(!$fp){$errors++;continue;}
    if(!@flock($fp,LOCK_SH)){fclose($fp);$errors++;continue;}
    $raw=stream_get_contents($fp);
    flock($fp,LOCK_UN);fclose($fp);
    if(!is_string($raw)||$raw===''){$errors++;continue;}
    $payload=json_decode($raw,true);
    if(!is_array($payload) ||
       !preg_match('/^[A-Z0-9._:-]{1,30}$/D',(string)($payload['symbol']??'')) ||
       ($payload['timeframe']??'')!=='D1' ||
       !is_array($payload['bars']??null)){
        $errors++;continue;
    }
    $results[]=bt_analyze_dataset($payload,$strategies,$horizons,$costs,$now);
}
respond(200,[
    'ok'=>true,'version'=>'backtesting-v0.1','source'=>'MT5 D1',
    'total'=>$total,'offset'=>$offset,'scanned'=>count($batch),
    'limit'=>$limit,'read_errors'=>$errors,'server_time'=>$now,
    'strategies'=>$strategies,'horizons'=>$horizons,
    'costs_bps'=>$costs,
    'entry_model'=>'next_D1_open','exit_model'=>'open_after_h_bars',
    'rules'=> 'canonical_live_scanner_rules_at_signal_time',
    'rows'=>$results
]);
