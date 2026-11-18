<?php
declare(strict_types=1);
/**
 * Public, cached StockTool macro brief from primary official issuers.
 * NO FOREX FACTORY redistribution, no user-controlled URLs.
 */
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, private');
header('X-Content-Type-Options: nosniff');
define('STOCKTOOL_INTELLIGENCE',true);
require __DIR__.'/source_lib.php';
if(($_SERVER['REQUEST_METHOD']??'GET')!=='GET'){
    header('Allow: GET');http_response_code(405);
    echo '{"ok":false,"error":"GET required"}';exit;
}
function mi_reply(array $value):void {
    echo json_encode($value,JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_INVALID_UTF8_SUBSTITUTE);exit;
}
function mi_translate_deepl(array $stories): array {
    // Optional translation ONLY when webmaster configures DeepL privately:
    // stocktool-private/config.php => 'deepl_api_key' => '...'
    // This function never reads client input or exposes the credential.
    $configPath=dirname(__DIR__,4).'/stocktool-private/config.php';
    if(!is_file($configPath)||!function_exists('curl_init'))return [$stories,false];
    try{$conf=require $configPath;}catch(Throwable $e){return [$stories,false];}
    $key=is_array($conf)?($conf['deepl_api_key']??''):null;
    if(!is_string($key)||strlen($key)<20)return [$stories,false];
    $host=($conf['deepl_endpoint']??'free')==='pro'
        ?'https://api.deepl.com/v2/translate':'https://api-free.deepl.com/v2/translate';
    $limit=min(24,count($stories));
    // DeepL expects repeated "text" fields, not text[0], text[1].
    $bodyFields='target_lang=CS&source_lang=EN';
    for($i=0;$i<$limit;$i++)
        $bodyFields.='&text='.rawurlencode($stories[$i]['title_original']);
    if(!$limit)return [$stories,true];
    $ch=curl_init($host);
    curl_setopt_array($ch,[
        CURLOPT_POST=>true,CURLOPT_RETURNTRANSFER=>true,CURLOPT_CONNECTTIMEOUT=>4,
        CURLOPT_TIMEOUT=>12,CURLOPT_SSL_VERIFYPEER=>true,
        CURLOPT_HTTPHEADER=>['Authorization: DeepL-Auth-Key '.$key,'Content-Type: application/x-www-form-urlencoded'],
        CURLOPT_POSTFIELDS=>$bodyFields
    ]);
    $body=curl_exec($ch);$status=(int)curl_getinfo($ch,CURLINFO_HTTP_CODE);curl_close($ch);
    if($status!==200||!is_string($body))return [$stories,false];
    $json=json_decode($body,true);
    if(!is_array($json['translations']??null))return [$stories,false];
    foreach($json['translations'] as $i=>$translation){
        $cs=trim((string)($translation['text']??''));
        if($i<$limit&&$cs!==''){
            $stories[$i]['title_cs']=$cs;$stories[$i]['translated']=true;
        }
    }
    return [$stories,true];
}
$cache=mi_cached('overview_official_v2',900,static function():?array {
    $now=time();$stories=[];$events=[];$sources=[];
    $newsfeeds=[
        ['name'=>'Fed','url'=>'https://www.federalreserve.gov/feeds/press_all.xml'],
        ['name'=>'ECB','url'=>'https://www.ecb.europa.eu/rss/press.html'],
        ['name'=>'BLS','url'=>'https://www.bls.gov/feed/bls_latest.rss'],
        ['name'=>'EIA','url'=>'https://www.eia.gov/rss/todayinenergy.xml']
    ];
    foreach($newsfeeds as $feed) {
        $raw=mi_get($feed['url']);
        $items=is_string($raw)?mi_parse_rss($raw,$feed['name']):[];
        $sources[]=['name'=>$feed['name'],'ok'=>(bool)count($items),'url'=>$feed['url']];
        foreach($items as $x)$stories[]=$x;
    }
    $seen=[];$unique=[];
    usort($stories,static fn($a,$b)=>($b['published_at']??0)<=>($a['published_at']??0));
    foreach($stories as $story){
        if(isset($seen[$story['id']]))continue;
        $seen[$story['id']]=true;
        if(($story['published_at']??0)<$now-40*86400)continue;
        $unique[]=$story;
    }
    $stories=array_slice($unique,0,50);
    [$stories,$deeplAvailable]=mi_translate_deepl($stories);
    $bea=mi_get('https://apps.bea.gov/API/signup/release_dates.json');
    $beaEvents=is_string($bea)?mi_parse_bea($bea,$now):[];
    $sources[]=['name'=>'BEA calendar','ok'=>count($beaEvents)>0,'url'=>'https://www.bea.gov/news/schedule/icalendar'];
    $bls=mi_get('https://www.bls.gov/schedule/news_release/bls.ics');
    $blsEvents=is_string($bls)?mi_parse_bls_ics($bls,$now):[];
    $sources[]=['name'=>'BLS calendar','ok'=>count($blsEvents)>0,'url'=>'https://www.bls.gov/schedule/2026/home.htm'];
    $events=mi_unique_events(array_merge($beaEvents,$blsEvents));
    $events=array_slice($events,0,1200);
    // Critical: no fabricated results if official feeds are unavailable.
    // Cache even an outage/empty source response for 15 minutes to avoid
    // hammering official endpoints from shared hosting.
    $hot=$stories;
    usort($hot,static function($a,$b)use($now){
        $score=static fn($s)=>($s['weight']??1)*10+
          max(0,10-($now-(int)($s['published_at']??0))/86400);
        $diff=$score($b)<=>$score($a);
        return $diff?:((int)($b['published_at']??0)<=>(int)($a['published_at']??0));
    });
    $hot=array_slice($hot,0,12);
    return [
        'news'=>$stories,'hot'=>$hot,'calendar'=>$events,'sources'=>$sources,
        'translation_enabled'=>$deeplAvailable,
        'hot_method'=>'Vlastní tematický výběr StockTool podle klíčových makro témat a stáří článku; není to žebříček popularity Forex Factory.',
        'calendar_note'=>'Ověřené termíny BEA/BLS USA s přibližně roční historií a plánem. Actual, Forecast, Previous ani historické grafy zatím nejsou dostupné; nesmějí se dopočítat.'
    ];
});
$payload=$cache['items'];
mi_reply([
    'ok'=>true,'version'=>'market-intelligence-v0.2',
    'updated_at'=>$cache['updated_at'],'stale'=>$cache['stale'],
    'data_available'=>count($payload['news']??[])>0||count($payload['calendar']??[])>0,
    'news'=>$payload['news']??[],'hot'=>$payload['hot']??[],
    'calendar'=>$payload['calendar']??[],'sources'=>$payload['sources']??[],
    'translation_enabled'=>$payload['translation_enabled']??false,
    'hot_method'=>$payload['hot_method']??'',
    'calendar_note'=>$payload['calendar_note']??'Oficiální zdroje dočasně nedostupné.',
    'external'=>[
        'ff_news'=>'https://www.forexfactory.com/news',
        'ff_calendar'=>'https://www.forexfactory.com/calendar',
        'ff_sessions'=>'https://www.forexfactory.com/',
        'ecb'=>'https://www.ecb.europa.eu/press/press_conference/html/index.en.html',
        'fed'=>'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'
    ]
]);
