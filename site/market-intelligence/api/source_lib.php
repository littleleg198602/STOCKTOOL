<?php
declare(strict_types=1);
/**
 * StockTool Market Intelligence v0.1. Primary source feeds only.
 * NEVER import Forex Factory pages, their FEED calendar, or Hot Stories.
 * Feed items retain ONLY title, link, time and issuer: no copyrighted body.
 */
if (!defined('STOCKTOOL_INTELLIGENCE')) { http_response_code(404); exit; }

function mi_get(string $url): ?string {
    // All callers supply constant HTTPS URLs; do not accept user-supplied URLs.
    if (strncmp($url, 'https://', 8) !== 0) return null;
    if (function_exists('curl_init')) {
        $ch=curl_init($url);
        curl_setopt_array($ch,[
            CURLOPT_RETURNTRANSFER=>true, CURLOPT_FOLLOWLOCATION=>false,
            CURLOPT_CONNECTTIMEOUT=>5, CURLOPT_TIMEOUT=>10,
            CURLOPT_USERAGENT=>'StockTool.eu/0.1 (public economic research; contact website)',
            CURLOPT_HTTPHEADER=>['Accept: application/json, application/rss+xml, text/calendar, */*'],
            CURLOPT_MAXREDIRS=>0, CURLOPT_SSL_VERIFYPEER=>true
        ]);
        $body=curl_exec($ch);
        $code=(int)curl_getinfo($ch,CURLINFO_HTTP_CODE);
        curl_close($ch);
        return $code===200 && is_string($body) && strlen($body)<=2000000 ? $body : null;
    }
    $ctx=stream_context_create(['http'=>[
        'method'=>'GET','timeout'=>9,'follow_location'=>0,
        'header'=>"User-Agent: StockTool.eu/0.1 (public economic research)\r\n"
    ]]);
    $body=@file_get_contents($url,false,$ctx,0,2000001);
    if(!is_string($body)||strlen($body)>2000000)return null;
    $status=$http_response_header[0]??'';
    return preg_match('~^HTTP/\S+\s+200\b~',$status)?$body:null;
}
function mi_cache_dir(): string {
    $base=dirname(__DIR__,4).DIRECTORY_SEPARATOR.'stocktool-private'.DIRECTORY_SEPARATOR.'intelligence-cache';
    if(!is_dir($base))@mkdir($base,0700,true);
    return is_dir($base)?$base:sys_get_temp_dir();
}
function mi_cached(string $key,int $seconds, callable $producer): array {
    $path=mi_cache_dir().DIRECTORY_SEPARATOR.'mi_'.preg_replace('/[^a-z0-9_]/','',$key).'.json';
    $now=time();
    $saved=is_file($path)?json_decode((string)@file_get_contents($path),true):null;
    if(is_array($saved)&&isset($saved['updated_at'],$saved['value'])&&$now-(int)$saved['updated_at']<$seconds)
        return ['items'=>$saved['value'],'updated_at'=>(int)$saved['updated_at'],'stale'=>false,'ok'=>true];
    try{$result=$producer();}catch(Throwable $e){$result=null;}
    if(is_array($result)) {
        $payload=['updated_at'=>$now,'value'=>$result];
        $bytes=json_encode($payload,JSON_UNESCAPED_UNICODE|JSON_INVALID_UTF8_SUBSTITUTE);
        if(is_string($bytes))@file_put_contents($path,$bytes,LOCK_EX);
        return ['items'=>$result,'updated_at'=>$now,'stale'=>false,'ok'=>true];
    }
    if(is_array($saved)&&isset($saved['updated_at'],$saved['value'])&&
        $now-(int)$saved['updated_at']<86400*3)
        return ['items'=>$saved['value'],'updated_at'=>(int)$saved['updated_at'],'stale'=>true,'ok'=>true];
    return ['items'=>[],'updated_at'=>null,'stale'=>true,'ok'=>false];
}
function mi_html(string $text): string {
    return trim(html_entity_decode(strip_tags($text),ENT_QUOTES|ENT_HTML5,'UTF-8'));
}
function mi_topic(string $title): array {
    $checks=[
        ['inflation|consumer price|cpi|price index|pce|producer price','Inflace a cenové tlaky','Inflace může změnit očekávání úrokových sazeb a rozhýbat USD, indexy i zlato.',3],
        ['interest rate|monetary policy|fomc|central bank|federal reserve|ecb|rate decision','Centrální banky a úroky','Rozhodnutí a komentáře centrálních bank mohou ovlivnit výnosy dluhopisů, měny, indexy i kovy.',3],
        ['employment|unemployment|payroll|jobs|labor market|labour market|job opening','Trh práce','Vývoj zaměstnanosti může změnit očekávání sazeb. Reakce trhu závisí na překvapení proti konsenzu.',3],
        ['gross domestic product|\bgdp\b|economic growth|growth outlook','Hospodářský růst','Údaje o růstu ekonomiky mohou ovlivnit očekávání sazeb a rizikovou náladu.',3],
        ['trade balance|international trade|imports|exports|tariff','Mezinárodní obchod','Obchodní data a cla mohou ovlivňovat měny, průmyslové indexy a rizikový sentiment.',2],
        ['oil|petroleum|energy|gas|crude','Energie a ropa','Pohyby v energetice mohou ovlivnit inflaci, komoditní měny a akciové sektory.',2],
        ['gold|silver|precious metal|bullion','Zlato a stříbro','Sleduj současně USD, reálné výnosy, rizikovou náladu a případný cenový šok.',2],
        ['retail|consumer spending|personal income|outlays','Spotřeba domácností','Spotřebitelská data pomáhají odhadovat stav ekonomiky a možné rozhodování centrální banky.',2],
        ['industrial production|manufactur|pmi|factory','Průmyslová aktivita','Změna v průmyslu může ovlivnit indexy, cyklické akcie a měnové páry.',2],
        ['speech|remarks|testimony|interview|statement','Projev nebo vyjádření','Výroky představitelů mohou přinést nové informace. Bez znalosti jejich obsahu nelze odhadnout směr reakce.',1],
    ];
    foreach($checks as [$pattern,$topic,$why,$weight]){
        if(preg_match('~'.$pattern.'~iu',$title))return ['topic_cs'=>$topic,'context_cs'=>$why,'weight'=>$weight];
    }
    return ['topic_cs'=>'Ekonomika a finanční trhy','context_cs'=>'Otevři původní zdroj a ověř podrobnosti. Samotný titulek nestačí pro rozhodnutí o obchodu.','weight'=>1];
}
function mi_translate_event(string $title): string {
    $map=[
        'Consumer Price Index'=>'Index spotřebitelských cen (CPI)',
        'Producer Price Index'=>'Index cen výrobců (PPI)',
        'Employment Situation'=>'Zpráva o zaměstnanosti (NFP)',
        'Unemployment Rate'=>'Míra nezaměstnanosti',
        'Gross Domestic Product'=>'Hrubý domácí produkt (HDP)',
        'Personal Income and Outlays'=>'Osobní příjmy a spotřební výdaje',
        'U.S. International Trade in Goods and Services'=>'Zahraniční obchod USA',
        'U.S. Import and Export Price Indexes'=>'Ceny dovozu a vývozu v USA',
        'Job Openings and Labor Turnover Survey'=>'Volná pracovní místa a fluktuace (JOLTS)',
        'Employment Cost Index'=>'Index nákladů práce',
        'Productivity and Costs'=>'Produktivita a náklady práce',
        'Real Earnings'=>'Reálné výdělky',
        'Personal Consumption Expenditures'=>'Výdaje na osobní spotřebu (PCE)',
        'Retail Sales'=>'Maloobchodní tržby',
        'Industrial Production'=>'Průmyslová výroba'
    ];
    foreach($map as $original=>$cs)
        if(stripos($title,$original)!==false)return $cs;
    return $title;
}
function mi_rating(string $text): string {
    return mi_topic($text)['weight']===3?'high':(mi_topic($text)['weight']===2?'medium':'low');
}
/* Official issuer RSS, linked-only headlines. Does not copy article bodies. */
function mi_parse_rss(string $xml,string $source): array {
    $out=[];
    if(function_exists('simplexml_load_string')){
        $previous=libxml_use_internal_errors(true);
        $root=simplexml_load_string($xml,'SimpleXMLElement',LIBXML_NONET|LIBXML_NOCDATA);
        libxml_clear_errors();libxml_use_internal_errors($previous);
        if($root){
            $items=isset($root->channel->item)?$root->channel->item:$root->entry;
            foreach($items as $item){
                $title=mi_html((string)$item->title);
                $link=(string)$item->link;
                if(!$link&&isset($item->link['href']))$link=(string)$item->link['href'];
                $time=(string)($item->pubDate?:$item->updated?:$item->published);
                $out[]=mi_make_story($title,$link,$time,$source);
            }
        }
    }else{
        // Conservative fallback for PHP builds without SimpleXML.
        preg_match_all('~<(item|entry)(?:\s[^>]*)?>(.*?)</\1>~is',$xml,$matches,PREG_SET_ORDER);
        foreach(array_slice($matches,0,50) as $m){
            $body=$m[2];
            preg_match('~<title\b[^>]*>(.*?)</title>~is',$body,$t);
            preg_match('~<link\b[^>]*>(.*?)</link>~is',$body,$l);
            if(!$l)preg_match('~<link\b[^>]*href=["\x27]([^"\x27]+)~i',$body,$l);
            preg_match('~<(?:pubDate|updated|published)\b[^>]*>(.*?)</(?:pubDate|updated|published)>~is',$body,$p);
            $out[]=mi_make_story(mi_html($t[1]??''),mi_html($l[1]??''),mi_html($p[1]??''),$source);
        }
    }
    return array_values(array_filter($out));
}
function mi_make_story(string $title,string $link,string $time,string $source): ?array {
    if($title===''||strlen($title)>450||!filter_var($link,FILTER_VALIDATE_URL)||
       !str_starts_with($link,'https://'))return null;
    // Avoid redirects to untrusted user-contributed content: issuer feeds only.
    $ts=strtotime($time)?:null;
    $topic=mi_topic($title);
    return [
        'id'=>hash('sha256',$link),'title_original'=>$title,'url'=>$link,
        'source'=>$source,'published_at'=>$ts,'topic_cs'=>$topic['topic_cs'],
        'context_cs'=>$topic['context_cs'],'weight'=>$topic['weight'],
        'title_cs'=>null,'translated'=>false
    ];
}
function mi_parse_bea(string $json,int $now): array {
    $parsed=json_decode($json,true);
    if(!is_array($parsed))return [];
    $events=[];
    foreach($parsed as $name=>$data){
        if(!is_array($data)||!is_array($data['release_dates']??null))continue;
        foreach($data['release_dates'] as $str){
            try{$dt=new DateTimeImmutable((string)$str);}catch(Throwable $e){continue;}
            $ts=$dt->getTimestamp();
            if($ts<$now-14*86400||$ts>$now+65*86400)continue;
            $name=(string)$name;
            $topic=mi_topic($name);
            $events[]=[
                'id'=>hash('sha256','BEA|'.$name.'|'.$ts),
                'time'=>$ts,'currency'=>'USD','name_cs'=>mi_translate_event($name),
                'name_original'=>$name,'source'=>'BEA','impact'=>mi_rating($name),
                'context_cs'=>$topic['context_cs'],
                'url'=>'https://www.bea.gov/news/schedule',
                'actual'=>null,'forecast'=>null,'previous'=>null
            ];
        }
    }
    return $events;
}
function mi_unfold_ics(string $raw): string {
    // RFC5545 continuation lines (one leading space/tab).
    return preg_replace("/\r?\n[ \t]/",'',$raw)??$raw;
}
function mi_parse_bls_ics(string $ics,int $now): array {
    $events=[];
    $ics=mi_unfold_ics($ics);
    preg_match_all('~BEGIN:VEVENT\r?\n(.*?)\r?\nEND:VEVENT~s',$ics,$matches);
    foreach(array_slice($matches[1]??[],0,500) as $entry){
        preg_match('/^SUMMARY:(.*)$/mi',$entry,$names);
        preg_match('/^DTSTART(?:;TZID=([^:;\r\n]+))?:(.*)$/mi',$entry,$dates);
        $name=trim(str_replace(['\\,','\\n','\\;'],[',',' ',';'],$names[1]??''));
        $str=trim($dates[2]??'');
        if($name===''||$str==='')continue;
        try{
            if(str_ends_with($str,'Z')){$dt=DateTimeImmutable::createFromFormat('!Ymd\THis\Z',$str,new DateTimeZone('UTC'));}
            elseif(strlen($str)===8){$dt=DateTimeImmutable::createFromFormat('!Ymd',$str,new DateTimeZone('America/New_York'));}
            else{
                $zone=trim($dates[1]??'');
                try{$tz=new DateTimeZone($zone?:'America/New_York');}catch(Throwable $e){$tz=new DateTimeZone('America/New_York');}
                $dt=DateTimeImmutable::createFromFormat('!Ymd\THis',$str,$tz);
            }
        }catch(Throwable $e){continue;}
        if(!$dt)continue;
        $ts=$dt->getTimestamp();
        if($ts<$now-14*86400||$ts>$now+65*86400)continue;
        $topic=mi_topic($name);
        $events[]=[
            'id'=>hash('sha256','BLS|'.$name.'|'.$ts),
            'time'=>$ts,'currency'=>'USD','name_cs'=>mi_translate_event($name),
            'name_original'=>$name,'source'=>'BLS',
            'impact'=>mi_rating($name),'context_cs'=>$topic['context_cs'],
            'url'=>'https://www.bls.gov/schedule/news_release/',
            'actual'=>null,'forecast'=>null,'previous'=>null
        ];
    }
    return $events;
}
function mi_unique_events(array $events): array {
    $seen=[];$out=[];
    usort($events,static fn($a,$b)=>$a['time']<=>$b['time']);
    foreach($events as $e) {
        $id=$e['id'];
        if(isset($seen[$id]))continue;
        $seen[$id]=1;$out[]=$e;
    }
    return $out;
}
