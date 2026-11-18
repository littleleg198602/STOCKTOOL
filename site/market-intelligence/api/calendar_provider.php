<?php
declare(strict_types=1);
/**
 * ShowMyTrades public economic calendar (9 currencies).
 * Attribution on the same page is mandatory; NEVER remove the returned credit.
 * Does not scrape Forex Factory or any source website.
 */
if(!defined('STOCKTOOL_INTELLIGENCE')){http_response_code(404);exit;}
function mi_smt_value($v): ?string {
    if($v===null||!is_scalar($v))return null;
    $x=trim((string)$v);
    return $x===''?null:(function_exists('mb_substr')?mb_substr($x,0,60,'UTF-8'):substr($x,0,120));
}
function mi_smt_attribution(array $body): array {
    $a=is_array($body['attribution']??null)?$body['attribution']:[];
    $text=trim((string)($a['text']??''));
    $url=trim((string)($a['url']??''));
    // Only accept supplied credit from the expected provider. If unavailable
    // fallback to official documented calendar credit, NEVER omit attribution.
    if(!in_array($text,['Economic calendar by ShowMyTrades','Data from ShowMyTrades'],true))
        $text='Economic calendar by ShowMyTrades';
    $host=parse_url($url,PHP_URL_HOST);
    if(!in_array($host,['showmytrades.com','www.showmytrades.com'],true)||
       !str_starts_with($url,'https://'))
        $url='https://showmytrades.com/tools/economic-calendar';
    return ['text'=>$text,'url'=>$url,'required'=>true];
}
function mi_parse_smt(string $raw,int $now): ?array {
    $body=json_decode($raw,true);
    if(!is_array($body)||!is_array($body['events']??null))return null;
    // A 200 JSON response with [] is valid: don't fabricate calendar entries.
    $out=[];
    $currencies=['USD','EUR','GBP','JPY','AUD','NZD','CAD','CHF','CNY'];
    foreach(array_slice($body['events'],0,2500) as $row){
        if(!is_array($row))continue;
        $currency=strtoupper(trim((string)($row['currency']??'')));
        if(!in_array($currency,$currencies,true))continue;
        $ts=filter_var($row['ts']??null,FILTER_VALIDATE_INT);
        if($ts===false||$ts<$now-2*86400||$ts>$now+32*86400)continue;
        $title=trim((string)($row['title']??''));
        if($title===''||strlen($title)>600)continue;
        $originId=trim((string)($row['id']??''));
        if($originId===''||strlen($originId)>200)continue;
        $topic=mi_topic($title);
        $nameCs=mi_cz_event_title($title);
        if($nameCs==='')$nameCs='Ekonomická událost: '.$topic['topic_cs'];
        $impact=strtolower(trim((string)($row['impact']??'')));
        if(!in_array($impact,['high','medium','low','holiday'],true))$impact='low';
        $status=strtolower(trim((string)($row['status']??'')));
        if(!in_array($status,['scheduled','moved','tentative'],true))$status='scheduled';
        $out[]=[
          'id'=>hash('sha256','SMT|'.$originId),
          'time'=>(int)$ts,'currency'=>$currency,'name_cs'=>$nameCs,
          'name_original'=>$title,'source'=>'ShowMyTrades','impact'=>$impact,
          'context_cs'=>$topic['context_cs'],
          'url'=>'https://showmytrades.com/tools/economic-calendar',
          'actual'=>mi_smt_value($row['actual']??null),
          'forecast'=>mi_smt_value($row['forecast']??null),
          'previous'=>mi_smt_value($row['previous']??null),
          'period'=>mi_smt_value($row['period']??null),
          'status'=>$status,
          'confidence'=>mi_smt_value($row['confidence']??null)
        ];
    }
    return ['events'=>$out,'attribution'=>mi_smt_attribution($body)];
}
function mi_merge_calendar(array $official,array $provider,int $now): array {
    if(!$provider)return mi_unique_events($official);
    // Provider is the richer source only for the release window it covers.
    // Preserve future and historical BEA/BLS schedules outside that window.
    $start=$now-6*3600;$end=$now+30*86400;
    $keys=[];
    foreach($provider as $p){
      $title=strtolower(preg_replace('/[^a-z0-9]+/i','',substr($p['name_original'],0,90)));
      $keys[$p['currency'].'|'.(int)floor($p['time']/3600).'|'.$title]=true;
    }
    $out=$provider;
    foreach($official as $e){
      if($e['time']<$start||$e['time']>$end){$out[]=$e;continue;}
      $title=strtolower(preg_replace('/[^a-z0-9]+/i','',substr($e['name_original'],0,90)));
      $key=$e['currency'].'|'.(int)floor($e['time']/3600).'|'.$title;
      if(!isset($keys[$key]))$out[]=$e;
    }
    return mi_unique_events($out);
}
