<?php
declare(strict_types=1);
/**
 * StockTool Backtesting Engine v0.1 – pure PHP library.
 *
 * Reuses the EXACT current live BUY, SHORT and Market Pressure rules.
 * Signal at completed D1 bar i; execution at open(i+1);
 * exit at open(i+1+horizon). Neither signal nor entry can see future bars.
 * Per symbol / strategy / horizon: at most ONE open trade at a time.
 */
if (!defined('STOCKTOOL_BACKTEST_ENGINE')) {
    http_response_code(404);
    exit;
}
define('STOCKTOOL_BUY_RULES', true);
define('STOCKTOOL_SHORT_RULES', true);
define('STOCKTOOL_PRESSURE_RULES', true);
require_once __DIR__ . '/../../buy-scanner/api/buy_rules.php';
require_once __DIR__ . '/../../short-scanner/api/short_rules.php';
require_once __DIR__ . '/../../market-pressure/api/pressure_rules.php';

const BT_STRATEGIES = ['BUY', 'SHORT', 'PRESSURE_REVERSAL', 'PRESSURE_CONTINUATION'];
const BT_HORIZONS = [1, 5, 10, 20, 60];

/** Reject corrupted datasets instead of silently producing a profitable curve. */
function bt_prepare(array $dataset, int $now): array {
    $source = $dataset['bars'] ?? null;
    if (!is_array($source)) return ['ok'=>false,'reason'=>'not_an_array','bars'=>[]];
    if (($dataset['timeframe'] ?? '') !== 'D1') return ['ok'=>false,'reason'=>'not_D1','bars'=>[]];
    $clean = []; $seen = [];
    foreach ($source as $row) {
        if (!is_array($row) ||
            !isset($row['t'],$row['o'],$row['h'],$row['l'],$row['c'])) {
            return ['ok'=>false,'reason'=>'bad_OHLC','bars'=>[]];
        }
        $t = (int)$row['t'];
        $o = (float)$row['o'];$h=(float)$row['h'];
        $l = (float)$row['l'];$c=(float)$row['c'];
        $v = isset($row['v']) && is_numeric($row['v']) ? (float)$row['v'] : 0.0;
        if ($t < 946684800 || $t > $now+86400 ||
            !is_finite($o) || !is_finite($h) || !is_finite($l) ||
            !is_finite($c) || !is_finite($v) ||
            $o<=0 || $h<=0 || $l<=0 || $c<=0 || $v<0 ||
            $h < max($o,$c,$l) || $l > min($o,$c,$h)) {
            return ['ok'=>false,'reason'=>'bad_OHLC','bars'=>[]];
        }
        if (isset($seen[(string)$t])) {
            return ['ok'=>false,'reason'=>'duplicate_timestamp','bars'=>[]];
        }
        $seen[(string)$t]=true;
        $clean[]=['t'=>$t,'o'=>$o,'h'=>$h,'l'=>$l,'c'=>$c,'v'=>$v];
    }
    usort($clean, static fn($a,$b) => $a['t']<=>$b['t']);
    $n=count($clean);
    // A delayed upload is still valid historical research but is marked stale.
    $stale = $n>0 && $clean[$n-1]['t'] < $now-10*86400;
    return ['ok'=>true,'reason'=>null,'bars'=>$clean,'stale'=>$stale];
}
function bt_direction(string $strategy): int {
    return in_array($strategy, ['SHORT','PRESSURE_CONTINUATION'], true) ? -1 : 1;
}
function bt_min_history(string $strategy): int {
    return in_array($strategy, ['BUY','SHORT'], true) ? 210 : 80;
}
/** Return a canonical current scanner setup on this historical signal date. */
function bt_signal(array $knownBars, string $symbol, string $strategy): ?string {
    $last=$knownBars[count($knownBars)-1]??null;
    if ($last===null || count($knownBars) < bt_min_history($strategy)) return null;
    // Clock simulates end of THIS bar only. Its future is not in knownBars.
    $asOf = $last['t']+1;
    $input=['symbol'=>$symbol,'timeframe'=>'D1','bars'=>$knownBars];
    if ($strategy==='BUY') {
        $x=analyze_dataset($input,$asOf);
        return $x['candidate'] ? (string)$x['raw_setup'] : null;
    }
    if ($strategy==='SHORT') {
        $x=sh_analyze($input,$asOf);
        return $x['candidate'] ? (string)$x['raw_setup'] : null;
    }
    $x=mp_analyze($input,$asOf);
    if ($strategy==='PRESSURE_REVERSAL' && $x['watch_buy']) return (string)$x['setup'];
    if ($strategy==='PRESSURE_CONTINUATION' && $x['watch_down']) return (string)$x['setup'];
    return null;
}

/**
 * Execution at following OPEN (no same-bar fill), fixed OPEN h trading bars
 * later. Spread is full bid-ask in bps, half paid at each execution.
 * Slippage and commissions apply to both entry and exit.
 */
function bt_trade(array $bars, int $signalIndex, string $symbol,
                  string $strategy, string $setup, int $h,
                  array $costs): array {
    $entryIndex=$signalIndex+1;
    $exitIndex=$entryIndex+$h;
    $direction=bt_direction($strategy);
    $entryOpen=$bars[$entryIndex]['o'];
    $exitOpen=$bars[$exitIndex]['o'];
    $impact=($costs['spread']/2+$costs['slippage'])/10000;
    $entryExecuted=$entryOpen*(1+$direction*$impact);
    $exitExecuted=$exitOpen*(1-$direction*$impact);
    $gross=$direction*($exitOpen/$entryOpen-1)*100;
    $net=$direction*($exitExecuted/$entryExecuted-1)*100
        -2*$costs['commission']/100;
    return [
        'symbol'=>$symbol,'strategy'=>$strategy,'setup'=>$setup,
        'horizon'=>$h, 'side'=>$direction===1?'LONG':'SHORT',
        'signal_time'=>$bars[$signalIndex]['t'],
        'entry_time'=>$bars[$entryIndex]['t'],
        'exit_time'=>$bars[$exitIndex]['t'],
        'entry'=>round($entryOpen,6),
        'exit'=>round($exitOpen,6),
        'gross_pct'=>round($gross,5),'net_pct'=>round($net,5)
    ];
}

/** Evaluate all selected horizons using ONE historical signal pass. */
function bt_evaluate(array $bars,string $symbol,string $strategy,
                     array $horizons,array $costs): array {
    $n=count($bars);
    $min=bt_min_history($strategy);
    // Evaluate ALL historical signal dates, including the most recent D1.
    // A recent signal without a future exit is counted as "unclosed",
    // never as a winning or losing trade.
    $lastSignalIndex=$n-1;
    $signals=[];
    for($i=$min-1; $i<=$lastSignalIndex; $i++) {
        $known=array_slice($bars,0,$i+1);
        $setup=bt_signal($known,$symbol,$strategy);
        if($setup!==null) $signals[]=['i'=>$i,'setup'=>$setup];
    }
    $groups=[];
    foreach($horizons as $h) {
        $items=[]; $nextAvailableEntry=0; $unclosed=0; $overlaps=0;
        foreach($signals as $signal) {
            $enter=$signal['i']+1;
            $leave=$enter+$h;
            if($leave >= $n) { $unclosed++; continue; }
            if($enter < $nextAvailableEntry) { $overlaps++; continue; }
            $items[]=bt_trade($bars,$signal['i'],$symbol,$strategy,$signal['setup'],$h,$costs);
            // A new trade may enter at the NEXT day's open after exit.
            // A signal at close before this day is still eligible.
            $nextAvailableEntry=$leave+1;
        }
        $groups[]=[
            'strategy'=>$strategy,'horizon'=>$h,'trades'=>$items,
            'count'=>count($items),'unclosed'=>$unclosed,'overlap_skipped'=>$overlaps,
            'signals_seen'=>count($signals),
            'min_bars_required'=>$min+$h+1
        ];
    }
    return $groups;
}
function bt_analyze_dataset(array $data,array $strategies,array $horizons,
                            array $costs,int $now): array {
    $symbol=(string)($data['symbol']??'');
    $prepared=bt_prepare($data,$now);
    $bars=$prepared['bars'];
    $n=count($bars);
    $result=[
        'symbol'=>$symbol,'status'=>'ok','reason'=>null,
        'bars'=>$n,'stale'=>($prepared['stale']??false),
        'last_time'=>$n?$bars[$n-1]['t']:null,
        'groups'=>[]
    ];
    if (!$prepared['ok']) {
        $result['status']='bad_data';
        $result['reason']=$prepared['reason'];
        return $result;
    }
    foreach($strategies as $strategy) {
        $min=bt_min_history($strategy)+min($horizons)+1;
        if ($n<$min) {
            $result['groups'][]=['strategy'=>$strategy,'status'=>'too_short',
                'required'=>$min,'available'=>$n,'horizons'=>$horizons];
            continue;
        }
        $groups=bt_evaluate($bars,$symbol,$strategy,$horizons,$costs);
        foreach($groups as $group) {
            $required=bt_min_history($strategy)+(int)$group['horizon']+1;
            if($n<$required) {
                $result['groups'][]=[
                    'strategy'=>$strategy, 'horizon'=>(int)$group['horizon'],
                    'status'=>'too_short','required'=>$required,'available'=>$n
                ];
            } else {
                $result['groups'][]=['strategy'=>$strategy,'status'=>'ok']+$group;
            }
        }
    }
    return $result;
}
