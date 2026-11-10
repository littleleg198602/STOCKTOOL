//+------------------------------------------------------------------+
//| StockToolBridge.mq5                                               |
//| Read-only MT5 OHLCV -> StockTool HTTPS API. NO TRADING FUNCTIONS.  |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property description "Read-only candle synchronization to stocktool.eu"
#property description "Does not place or modify any trades."

input string          InpApiURL         = "https://www.stocktool.eu/test/data-manager/api/ingest.php";
input string          InpApiKey         = "";
input string          InpSymbol         = "";          // Empty = current chart symbol
input ENUM_TIMEFRAMES InpTimeframe      = PERIOD_H1;
input int             InpInitialBars    = 500;         // Closed candles to sync on startup
input int             InpEverySeconds   = 60;          // Check for new closed bars

string   g_symbol = "";
string   g_tf = "";
datetime g_lastClosed = 0;
bool     g_initialSyncDone = false;

string TimeframeName(ENUM_TIMEFRAMES tf)
{
   switch(tf)
   {
      case PERIOD_M1:  return "M1";
      case PERIOD_M5:  return "M5";
      case PERIOD_M15: return "M15";
      case PERIOD_M30: return "M30";
      case PERIOD_H1:  return "H1";
      case PERIOD_H4:  return "H4";
      case PERIOD_D1:  return "D1";
      case PERIOD_W1:  return "W1";
      default:         return "";
   }
}

// Symbols are restricted to the same safe characters as our PHP API.
bool ValidSymbol(string symbol)
{
   int count = StringLen(symbol);
   if(count < 1 || count > 30) return false;
   for(int i=0; i<count; i++)
   {
      ushort c = StringGetCharacter(symbol,i);
      bool valid = (c>=65 && c<=90) || (c>=97 && c<=122) ||
                   (c>=48 && c<=57) || c==46 || c==95 || c==45 || c==58;
      if(!valid) return false;
   }
   return true;
}

string BarJson(MqlRates &bar)
{
   int digits = (int)SymbolInfoInteger(g_symbol,SYMBOL_DIGITS);
   digits = (int)MathMax(0,MathMin(10,digits));
   return "{\"t\":" + IntegerToString((long)bar.time) +
          ",\"o\":" + DoubleToString(bar.open,digits) +
          ",\"h\":" + DoubleToString(bar.high,digits) +
          ",\"l\":" + DoubleToString(bar.low,digits) +
          ",\"c\":" + DoubleToString(bar.close,digits) +
          ",\"v\":" + IntegerToString((long)bar.tick_volume) + "}";
}

bool SendRates(MqlRates &rates[], int from, int count)
{
   if(count < 1) return true;
   string json = "{\"symbol\":\"" + g_symbol + "\",\"timeframe\":\"" + g_tf + "\",\"bars\":[";
   for(int i=0; i<count; i++)
   {
      if(i>0) json += ",";
      json += BarJson(rates[from+i]);
   }
   json += "]}";

   char post[];
   int length = StringToCharArray(json,post,0,WHOLE_ARRAY,CP_UTF8);
   if(length<=1) return false;
   ArrayResize(post,length-1); // Remove terminating \0 from JSON request.

   char response[];
   string responseHeaders;
   string headers = "Content-Type: application/json\r\n" +
                    "X-StockTool-Key: " + InpApiKey + "\r\n";
   ResetLastError();
   int status = WebRequest("POST",InpApiURL,headers,12000,post,response,responseHeaders);
   if(status != 200)
   {
      Print("StockTool: upload failed. HTTP=",status," MT5 error=",GetLastError(),
            " response=",CharArrayToString(response,0,128,CP_UTF8));
      if(status==-1) Print("StockTool: add https://stocktool.eu to MT5 WebRequest whitelist.");
      return false;
   }
   Print("StockTool: synchronized ",count," ",g_symbol," ",g_tf," closed candles.");
   return true;
}

bool SyncHistory()
{
   MqlRates bars[];
   ArraySetAsSeries(bars,false); // oldest bar first
   int n = CopyRates(g_symbol,InpTimeframe,1,InpInitialBars,bars);
   if(n<=0)
   {
      Print("StockTool: no historical bars yet; MT5 history may still be downloading. Error=",GetLastError());
      return false;
   }
   for(int offset=0; offset<n; offset+=150)
   {
      int chunk = (int)MathMin(150,n-offset);
      if(!SendRates(bars,offset,chunk)) return false;
   }
   g_lastClosed = bars[n-1].time;
   g_initialSyncDone = true;
   Print("StockTool: initial sync complete for ",g_symbol," ",g_tf," (",n," candles).");
   return true;
}

void SyncLatest()
{
   datetime lastClosed = iTime(g_symbol,InpTimeframe,1);
   if(lastClosed==0 || lastClosed==g_lastClosed) return;
   MqlRates bars[];
   ArraySetAsSeries(bars,false);
   // Send last few closed candles for resilience to gaps / reconnections.
   int count = CopyRates(g_symbol,InpTimeframe,1,5,bars);
   if(count < 1) return;
   if(SendRates(bars,0,count)) g_lastClosed = bars[count-1].time;
}

int OnInit()
{
   g_symbol = InpSymbol=="" ? _Symbol : InpSymbol;
   g_tf = TimeframeName(InpTimeframe);

   if(StringLen(InpApiKey)<32 || g_tf=="" || !ValidSymbol(g_symbol) ||
      StringFind(InpApiURL,"https://")!=0 || InpInitialBars<1 || InpInitialBars>5000 ||
      InpEverySeconds<10 || InpEverySeconds>3600)
   {
      Print("StockTool: invalid input parameters. Key >=32 characters, supported timeframe, HTTPS URL and valid symbol required.");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(!SymbolSelect(g_symbol,true))
   {
      Print("StockTool: symbol not available at broker: ",g_symbol);
      return INIT_FAILED;
   }
   EventSetTimer(InpEverySeconds);
   Print("StockTool read-only connector initialized. Symbol=",g_symbol," timeframe=",g_tf);
   // Initial connection uses OnTimer, avoiding network calls during init.
   return INIT_SUCCEEDED;
}

void OnTimer()
{
   if(!g_initialSyncDone)
   {
      SyncHistory();
      return;
   }
   SyncLatest();
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}
// There is deliberately no OnTick/OrderSend/position management.
//+------------------------------------------------------------------+
