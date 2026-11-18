<?php
declare(strict_types=1);
/**
 * Rate-capped free MyMemory lookup for short PUBLIC official-source headlines.
 * Public headlines only, never private user input, credentials, or article bodies.
 * Never runs in visitors' browsers; permanent private translation cache.
 */
if(!defined('STOCKTOOL_INTELLIGENCE')){http_response_code(404);exit;}
function mi_parse_translation(string $raw): ?string {
    $body=json_decode($raw,true);
    if(!is_array($body)||(int)($body['responseStatus']??0)!==200)return null;
    $result=mi_html((string)($body['responseData']['translatedText']??''));
    if($result===''||strlen($result)>1000||
       preg_match('~(query length limit|usage limit|translation not available|invalid language)~i',$result))return null;
    return $result;
}
function mi_translate_public_headlines(array $stories): array {
    if(!function_exists('curl_multi_init')||!function_exists('curl_init'))return [$stories,0];
    $dir=mi_cache_dir();
    $path=$dir.DIRECTORY_SEPARATOR.'mi_cz_titles_v1.json';
    $lock=@fopen($path.'.lock','c');
    if(!$lock||!@flock($lock,LOCK_EX|LOCK_NB)){
        if(is_resource($lock))fclose($lock);
        return [$stories,0];
    }
    try{
        $raw=is_file($path)?@file_get_contents($path):false;
        $db=is_string($raw)?json_decode($raw,true):null;
        if(!is_array($db))$db=['day'=>'','spent'=>0,'items'=>[],'attempted'=>[]];
        if(($db['day']??'')!==gmdate('Y-m-d')){
            $db['day']=gmdate('Y-m-d');$db['spent']=0;$db['attempted']=[];
        }
        if(!is_array($db['items']??null))$db['items']=[];
        if(!is_array($db['attempted']??null))$db['attempted']=[];
        $queue=[];$spent=(int)($db['spent']??0);
        foreach($stories as $i=>&$story){
            if(!empty($story['translated']))continue;
            $title=trim((string)($story['title_original']??''));
            $key=hash('sha256',$title);
            if(isset($db['items'][$key]['text'])){
                $story['title_cs']=$db['items'][$key]['text'];
                $story['translated']=true;
                $story['localization']='machine_translation';
                $story['translation_provider']='MyMemory';
                continue;
            }
            $len=strlen($title);
            if($len<8||$len>350||$spent+$len>3200||count($queue)>=12||
               isset($db['attempted'][$key]))continue;
            $queue[]=['index'=>$i,'title'=>$title,'key'=>$key,'len'=>$len];
            $spent+=$len;
            $db['attempted'][$key]=gmdate('Y-m-d');
        }
        unset($story);
        $db['spent']=$spent;
        if($queue){
            $mh=curl_multi_init();$handles=[];
            foreach($queue as $q){
                $url='https://api.mymemory.translated.net/get?q='.rawurlencode($q['title']).'&langpair=en%7Ccs&mt=1';
                $ch=curl_init($url);
                curl_setopt_array($ch,[
                    CURLOPT_RETURNTRANSFER=>true,CURLOPT_FOLLOWLOCATION=>false,
                    CURLOPT_CONNECTTIMEOUT=>2,CURLOPT_TIMEOUT=>5,
                    CURLOPT_SSL_VERIFYPEER=>true,
                    CURLOPT_USERAGENT=>'StockTool.eu/0.3 (public official headlines)'
                ]);
                curl_multi_add_handle($mh,$ch);
                $handles[]=['handle'=>$ch,'item'=>$q];
            }
            $running=0;$deadline=microtime(true)+7;
            do{
                $status=curl_multi_exec($mh,$running);
                if($running&&$status===CURLM_OK&&microtime(true)<$deadline)
                    curl_multi_select($mh,0.4);
                else break;
            }while($running&&microtime(true)<$deadline);
            foreach($handles as $h){
                $ch=$h['handle'];$q=$h['item'];
                $body=curl_multi_getcontent($ch);
                $code=(int)curl_getinfo($ch,CURLINFO_HTTP_CODE);
                if($code===200&&is_string($body)){
                    $cz=mi_parse_translation($body);
                    if($cz!==null&&strcasecmp($cz,$q['title'])!==0){
                        $db['items'][$q['key']]=['text'=>$cz,'at'=>time()];
                        $stories[$q['index']]['title_cs']=$cz;
                        $stories[$q['index']]['translated']=true;
                        $stories[$q['index']]['localization']='machine_translation';
                        $stories[$q['index']]['translation_provider']='MyMemory';
                    }
                }
                curl_multi_remove_handle($mh,$ch);curl_close($ch);
            }
            curl_multi_close($mh);
        }
        // Bound state size and prevent long-term accumulation on cheap hosting.
        uasort($db['items'],static fn($a,$b)=>(int)($b['at']??0)<=>(int)($a['at']??0));
        $db['items']=array_slice($db['items'],0,300,true);
        if(count($db['attempted'])>500)$db['attempted']=array_slice($db['attempted'],-500,null,true);
        $payload=json_encode($db,JSON_UNESCAPED_UNICODE|JSON_INVALID_UTF8_SUBSTITUTE);
        if(is_string($payload))@file_put_contents($path,$payload,LOCK_EX);
        $translated=count(array_filter($stories,static fn($x)=>!empty($x['translated'])));
        return [$stories,$translated];
    }finally{@flock($lock,LOCK_UN);@fclose($lock);}
}
