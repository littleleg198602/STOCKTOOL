<?php
declare(strict_types=1);
/** Offline regressions: php tests/market_intelligence_test.php */
define('STOCKTOOL_INTELLIGENCE',true);
require dirname(__DIR__).'/site/market-intelligence/api/source_lib.php';
require dirname(__DIR__).'/site/market-intelligence/api/calendar_provider.php';
require dirname(__DIR__).'/site/market-intelligence/api/translation.php';
function check(bool $ok,string $message):void {
    if(!$ok)throw new RuntimeException('FAIL '.$message);
    echo "PASS $message\n";
}
$today=(new DateTimeImmutable('2026-11-16 12:00:00',new DateTimeZone('UTC')))->getTimestamp();

check(mi_translate_event('Consumer Price Index for October 2026')==='Index spotřebitelských cen (CPI)',
    'Known macro release translated to Czech label');
check(mi_rating('Consumer Price Index for October')==='high','CPI is high topic');
check(mi_rating('Employment Situation October')==='high','Jobs is high topic');
check(mi_rating('An unrelated speech')==='low','Speech is not fabricated high-impact');
check(mi_topic('Gold prices sharply lower')['topic_cs']==='Zlato a stříbro',
    'Commodity context is Czech');
check(strpos(mi_html('<b>Fed</b> &amp; ECB'),'Fed & ECB')!==false,
    'Basic RSS headline entities decoded and HTML removed');

$bea=json_encode([
    'Gross Domestic Product'=>[
        'release_dates'=>['2026-11-25T13:30:00+00:00','2026-11-25T13:30:00+00:00','2028-01-01T13:30:00+00:00']
    ],
    'Personal Income and Outlays'=>[
        'release_dates'=>['2026-11-25T13:30:00+00:00']
    ]
]);
$b=mi_parse_bea($bea,$today);
check(count($b)===3,'BEA parses supplied dates without fabricating values (duplicates handled later)');
check($b[0]['time']===(new DateTimeImmutable('2026-11-25T13:30:00+00:00'))->getTimestamp(),
    'BEA offset-aware date parsed as UTC timestamp');
check($b[0]['actual']===null&&$b[0]['forecast']===null&&$b[0]['previous']===null,
    'No invented calendar actual, forecast or previous numbers');

$ics="BEGIN:VCALENDAR\r\nVERSION:2.0\r\n".
    "BEGIN:VEVENT\r\nSUMMARY:Consumer Price Index for October 2026\r\n".
    "DTSTART;TZID=America/New_York:20261117T083000\r\nEND:VEVENT\r\n".
    "BEGIN:VEVENT\r\nSUMMARY:Employment Situation\r\n".
    "DTSTART:20261204T133000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
$bls=mi_parse_bls_ics($ics,$today);
check(count($bls)===2,'BLS ICS parses local timezone and UTC dates');
check($bls[0]['time']===(new DateTimeImmutable('2026-11-17T13:30:00+00:00'))->getTimestamp(),
    'BLS November New York 08:30 = 13:30 UTC (winter DST)');
check($bls[1]['time']===(new DateTimeImmutable('2026-12-04T13:30:00+00:00'))->getTimestamp(),
    'BLS explicit UTC timestamp parsed');
check($bls[0]['impact']==='high','CPI label rated as high importance by our own heuristic');
check(count(mi_unique_events(array_merge($b,$b)))===2,'BEA duplicate records removed via stable id');

$rss='<?xml version="1.0"?><rss><channel><item>'.
    '<title>Federal Reserve announces monetary policy decision</title>'.
    '<link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20261116a.htm</link>'.
    '<pubDate>Mon, 16 Nov 2026 12:00:00 GMT</pubDate>'.
    '</item><item><title>Bad link</title><link>javascript:alert(1)</link></item>'.
    '</channel></rss>';
$news=mi_parse_rss($rss,'Fed');
check(count($news)===1,'Official RSS link valid HTTPS; javascript URL rejected');
check($news[0]['source']==='Fed','News is attributed to original issuer');
check($news[0]['published_at']===$today,'RSS RFC822 timestamp preserved');
check(is_string($news[0]['title_cs'])&&str_contains($news[0]['title_cs'],'Fed:')&&
      !$news[0]['translated']&&($news[0]['localization']??'')==='topic_summary',
    'Czech summary must be visibly distinct from a verified translation');

check(mi_cz_event_title('Core CPI m/m')==='Jádrová inflace (CPI) · meziměsíčně',
    'Core CPI and monthly qualifiers stay distinct');
check(mi_cz_event_title('GDP Price Index q/q')==='Cenový deflátor HDP · mezikvartálně',
    'GDP deflator is not conflated with real GDP');

$ts=$today+8*86400;
$providerFixture=json_encode([
    'events'=>[
        ['id'=>'usd-cpi-mom.test-001','ts'=>$ts,'title'=>'Core CPI m/m',
          'currency'=>'USD','impact'=>'high','forecast'=>'0.3%','actual'=>'0.0%',
          'previous'=>'0.2%','status'=>'scheduled'],
        ['id'=>'eur-ecb-rate.test-002','ts'=>$ts+3600,'title'=>'ECB Rate Decision',
          'currency'=>'EUR','impact'=>'high','forecast'=>null,'actual'=>null,
          'previous'=>'0','status'=>'scheduled'],
        ['id'=>'invalid','ts'=>$ts,'title'=>'Invalid currency',
          'currency'=>'FOO','impact'=>'high','forecast'=>null],
    ],
    'attribution'=>[
        'required'=>false,
        'text'=>'Economic calendar by ShowMyTrades',
        'url'=>'https://showmytrades.com/tools/economic-calendar'
    ]
],JSON_UNESCAPED_UNICODE);
$smt=mi_parse_smt($providerFixture,$today);
check(is_array($smt)&&count($smt['events'])===2,
    'Public calendar returns only valid major FX currencies');
check($smt['events'][0]['actual']==='0.0%'&&$smt['events'][1]['previous']==='0',
    'Real zero is kept distinct from missing source figures');
check($smt['events'][1]['forecast']===null,'Missing forecast stays null');
check($smt['events'][0]['name_cs']==='Jádrová inflace (CPI) · meziměsíčně',
    'Imported foreign currency events get Czech indicator labels');
check($smt['attribution']['required']===true&&
    $smt['attribution']['url']==='https://showmytrades.com/tools/economic-calendar',
    'External provider must receive visible data credit');

$merged=mi_merge_calendar($b,$smt['events'],$today);
check(count($merged)>=2,'Merger contains both valid international and official events');
check(mi_parse_smt('{"error":"down"}',$today)===null,
    'External API outage is not fabricated and triggers official fallback');

check(mi_parse_translation('{"responseStatus":200,"responseData":{"translatedText":"Centrální banky oznamují změny"}}')
    ==='Centrální banky oznamují změny',
    'Machine translation JSON result is validated and kept as Czech text');
check(mi_parse_translation('{"responseStatus":429,"responseData":{"translatedText":"LIMIT"}}')===null,
    'Rate-limited translation cannot replace Czech topic fallback');

echo "\nMarket Intelligence offline parser regression tests passed.\n";
