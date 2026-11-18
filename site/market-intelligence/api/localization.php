<?php
declare(strict_types=1);
/**
 * Deterministic Czech UI labels: NOT machine translation.
 * If no DeepL key is configured, primary display is an explicitly labelled
 * Czech topic summary. English originals remain visible for verification.
 */
if(!defined('STOCKTOOL_INTELLIGENCE')){http_response_code(404);exit;}
function mi_cz_topic_title(string $title,string $source,string $topic): string {
    // Ordered specific patterns; these only describe text visibly present.
    $patterns=[
      '~financial stability review~i' => 'Přehled finanční stability',
      '~financial stability outlook~i' => 'Výhled finanční stability',
      '~monetary policy communication~i' => 'Komunikace měnové politiky',
      '~natural gas (inventor|storag|inject)~i' => 'Zásoby zemního plynu v USA',
      '~crude oil (inventor|stock|storag)~i' => 'Zásoby ropy v USA',
      '~oil (price|market|production|supply)~i' => 'Vývoj na trhu s ropou',
      '~natural gas~i' => 'Vývoj na trhu se zemním plynem',
      '~inflation expectations~i' => 'Očekávání inflace',
      '~interest rate (decision|announcement)~i' => 'Rozhodnutí o úrokových sazbách',
      '~fomc (statement|minutes|meeting)~i' => 'Zasedání nebo zápis Fedu (FOMC)',
      '~unemployment (rate|claims)~i' => 'Vývoj nezaměstnanosti',
      '~non.?farm payroll~i' => 'Zaměstnanost mimo zemědělství (NFP)',
      '~consumer price index|\bCPI\b~i' => 'Index spotřebitelských cen (CPI)',
      '~producer price index|\bPPI\b~i' => 'Index cen výrobců (PPI)',
      '~employment (situation|report|data)~i' => 'Zpráva o zaměstnanosti',
      '~gross domestic product|\bGDP\b~i' => 'Hrubý domácí produkt (HDP)',
      '~industrial production~i' => 'Průmyslová výroba',
      '~retail sales~i' => 'Maloobchodní tržby',
      '~consumer spending|personal consumption~i' => 'Výdaje spotřebitelů',
      '~business (activity|survey|outlook)~i' => 'Výhled podnikatelské aktivity',
      '~manufactur|factory (orders|activity)~i' => 'Aktivita ve zpracovatelském průmyslu',
      '~economic (growth|outlook|activity)~i' => 'Hospodářský výhled a růst',
      '~financial (risk|regulation|market)~i' => 'Rizika finančního systému',
      '~artificial intelligence|\bAI\b~i' => 'Umělá inteligence a finanční trhy',
      '~energy|electricity|petroleum~i' => 'Energetické trhy',
      '~gold|silver|precious metal~i' => 'Zlato a drahé kovy',
      '~speech|speaks|remarks|address|testimony~i' => 'Projev představitele finanční instituce',
    ];
    foreach($patterns as $pattern=>$label)if(preg_match($pattern,$title))return $source.': '.$label;
    return $source.': '.($topic!==''?$topic:'Ekonomické a finanční zprávy');
}
function mi_cz_event_title(string $title): string {
    $t=trim($title);
    if($t==='')return 'Ekonomická událost';
    $patterns=[
      '~\b(core cpi|core consumer price index)\b~i'=>'Jádrová inflace (CPI)',
      '~\b(trimmed mean cpi|trimmed cpi)\b~i'=>'Očištěná inflace (CPI)',
      '~\b(median cpi)\b~i'=>'Mediánová inflace (CPI)',
      '~\b(core ppi|core producer price index)\b~i'=>'Jádrový index cen výrobců (PPI)',
      '~\b(gdp price index|gdp deflator)\b~i'=>'Cenový deflátor HDP',
      '~\b(nonfarm payrolls?|employment situation)\b~i'=>'Nová pracovní místa mimo zemědělství (NFP)',
      '~\b(initial|continuing) jobless claims\b~i'=>'Žádosti o podporu v nezaměstnanosti',
      '~\b(unemployment rate)\b~i'=>'Míra nezaměstnanosti',
      '~\b(employment change)\b~i'=>'Změna zaměstnanosti',
      '~\b(average hourly earnings)\b~i'=>'Průměrný hodinový výdělek',
      '~\b(consumer price index|\bcpi\b)\b~i'=>'Index spotřebitelských cen (CPI)',
      '~\b(core cpi)\b~i'=>'Jádrová inflace CPI',
      '~\b(producer price index|\bppi\b)\b~i'=>'Index cen výrobců (PPI)',
      '~\b(core pce)\b~i'=>'Jádrový index osobní spotřeby (PCE)',
      '~\b(pce price|personal consumption expenditures)\b~i'=>'Index výdajů na osobní spotřebu (PCE)',
      '~\b(gross domestic product|\bgdp\b)\b~i'=>'Hrubý domácí produkt (HDP)',
      '~\b(retail sales)\b~i'=>'Maloobchodní tržby',
      '~\b(industrial production)\b~i'=>'Průmyslová výroba',
      '~\b(manufacturing pmi)\b~i'=>'Index nákupních manažerů ve výrobě (PMI)',
      '~\b(services pmi)\b~i'=>'Index nákupních manažerů ve službách (PMI)',
      '~\b(composite pmi)\b~i'=>'Souhrnný index PMI',
      '~\b(interest rate decision|rate decision)\b~i'=>'Rozhodnutí o úrokových sazbách',
      '~\b(fomc (statement|minutes|press conference))\b~i'=>'Oznámení nebo tisková konference Fedu',
      '~\b(ecb (press conference|rate decision|statement))\b~i'=>'Rozhodnutí nebo tisková konference ECB',
      '~\b(boj rate decision)\b~i'=>'Rozhodnutí japonské centrální banky',
      '~\b(boe rate decision)\b~i'=>'Rozhodnutí britské centrální banky',
      '~\b(consumer confidence)\b~i'=>'Spotřebitelská důvěra',
      '~\b(business confidence)\b~i'=>'Podnikatelská důvěra',
      '~\b(trade balance)\b~i'=>'Bilance zahraničního obchodu',
      '~\b(building permits)\b~i'=>'Stavební povolení',
      '~\b(housing starts)\b~i'=>'Zahájená výstavba domů',
      '~\b(job openings|jolts)\b~i'=>'Volná pracovní místa (JOLTS)',
      '~\b(factory orders)\b~i'=>'Průmyslové zakázky',
      '~\b(personal income)\b~i'=>'Osobní příjmy',
      '~\b(personal spending|personal outlays)\b~i'=>'Osobní spotřební výdaje',
      '~\b(import prices|export prices)\b~i'=>'Ceny dovozu a vývozu',
      '~\b(bank holiday|public holiday|market holiday)\b~i'=>'Státní svátek / zavřený trh',
    ];
    // Distinguish core/headline and period comparisons; never conflate
    // month-over-month with year-over-year in the displayed Czech label.
    foreach($patterns as $re=>$label){
        if(!preg_match($re,$t))continue;
        if(preg_match('~\\b(m/m|mom|month.over.month)\\b~i',$t))$label.=' · meziměsíčně';
        elseif(preg_match('~\\b(y/y|yoy|year.over.year)\\b~i',$t))$label.=' · meziročně';
        elseif(preg_match('~\\b(q/q|qoq|quarter.over.quarter)\\b~i',$t))$label.=' · mezikvartálně';
        if(preg_match('~\\b(prelim|preliminary)\\b~i',$t))$label='Předběžně: '.$label;
        elseif(preg_match('~\\b(final)\\b~i',$t))$label='Konečně: '.$label;
        elseif(preg_match('~\\b(revised)\\b~i',$t))$label='Revidováno: '.$label;
        return $label;
    }
    if(preg_match('~\b(speech|speaks|remarks|testimony)\b~i',$t)){
        return 'Projev představitele centrální banky';
    }
    // Unknown title remains verifiable; page displays Czech topic category and
    // English original as supporting info, not a false claim of translation.
    return '';
}
