import { NextResponse } from "next/server";

export async function GET() {
  const eaContent = `//+------------------------------------------------------------------+
//|                                                      BridgeEA.mq5 |
//|                            ATLAS Trading Platform — MT5 Bridge EA |
//|                                                                  |
//| Native Zero-DLL MT5 Expert Advisor using MQL5 WebRequest().      |
//| Requires NO DLL files or external libraries!                      |
//+------------------------------------------------------------------+
#property strict
#property version   "2.00"
#property copyright "ATLAS Platform"
#property description "ATLAS Bridge EA — Zero-DLL native MQL5 Expert Advisor"

#include <Trade\\Trade.mqh>
#include <Trade\\PositionInfo.mqh>
#include <Trade\\HistoryOrderInfo.mqh>
#include <Trade\\DealInfo.mqh>

//--- inputs
input string   InpBridgeUrl         = "https://backend.vorte.dev";
input string   InpTerminalId        = "mt5-terminal-01";
input string   InpBroker            = "Exness";
input string   InpAuthToken         = "your-bridge-auth-token";
input string   InpSymbolsCSV        = "XAUUSD,EURUSD,GBPUSD,USDJPY";
input int      InpHeartbeatSeconds  = 2;
input int      InpMagic             = 770000;

CTrade              trade;
CPositionInfo       posInfo;
CHistoryOrderInfo   histOrder;
CDealInfo           dealInfo;

ulong  g_lastHeartbeat = 0;
string g_symbols[];

//+------------------------------------------------------------------+
//| Helper: Send HTTP POST request via MQL5 WebRequest               |
//+------------------------------------------------------------------+
int HttpPost(string endpoint, string payloadJson, string &responseStr)
{
   char data[];
   char result[];
   string result_headers;
   StringToCharArray(payloadJson, data, 0, StringLen(payloadJson));

   string fullUrl = InpBridgeUrl + endpoint;
   string headers = "Content-Type: application/json\\r\\nAuthorization: Bearer " + InpAuthToken + "\\r\\n";

   ResetLastError();
   int res = WebRequest("POST", fullUrl, headers, 3000, data, result, result_headers);
   if(res == 200)
   {
      responseStr = CharArrayToString(result);
   }
   else if(res < 0)
   {
      int err = GetLastError();
      if(err == 4060)
      {
         Print("[ATLAS ERROR] WebRequest not allowed! Add '", InpBridgeUrl, "' to Tools -> Options -> Expert Advisors -> Allow WebRequest.");
      }
      else
      {
         Print("[ATLAS ERROR] WebRequest failed. err=", err, " code=", res);
      }
   }
   return res;
}

void PopulateSymbols()
{
   ArrayResize(g_symbols, 0);
   string trimmed = InpSymbolsCSV;
   StringTrimLeft(trimmed);
   StringTrimRight(trimmed);

   if(trimmed == "*" || trimmed == "all" || trimmed == "ALL" || trimmed == "")
   {
      int total = SymbolsTotal(true);
      ArrayResize(g_symbols, total);
      for(int i = 0; i < total; i++)
      {
         g_symbols[i] = SymbolName(i, true);
      }
      Print("[ATLAS] Streaming all ", total, " symbols from Market Watch.");
   }
   else
   {
      SplitCSV(InpSymbolsCSV, g_symbols);
      Print("[ATLAS] Streaming ", ArraySize(g_symbols), " configured symbols.");
   }
}

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   PopulateSymbols();

   Print("[ATLAS] Zero-DLL BridgeEA starting. terminal=", InpTerminalId, " broker=", InpBroker);

   string resp;
   string symbolsJson = ArrayToJson(g_symbols);
   string regMsg = StringFormat(
      "{\\"terminal_id\\":\\"%s\\",\\"broker\\":\\"%s\\",\\"account\\":%I64u,"
      "\\"version\\":\\"%s\\",\\"symbols\\":%s,\\"auth_token\\":\\"%s\\","
      "\\"capabilities\\":{\\"market\\":true,\\"limit\\":true,\\"stop\\":true,\\"close_partial\\":true}}",
      InpTerminalId, InpBroker,
      AccountInfoInteger(ACCOUNT_LOGIN),
      IntegerToString((int)TerminalInfoInteger(TERMINAL_BUILD)),
      symbolsJson, InpAuthToken);

   int code = HttpPost("/api/v1/bridge-http/register", regMsg, resp);
   if(code == 200)
   {
      Print("[ATLAS] Registered successfully with backend over HTTPS!");
   }
   else
   {
      Print("[ATLAS] Initial registration pending; will retry in timer. code=", code);
   }

   EventSetTimer(InpHeartbeatSeconds);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("[ATLAS] BridgeEA stopped. reason=", reason);
}

//+------------------------------------------------------------------+
void OnTimer()
{
   string resp;
   string pollPayload = StringFormat(
      "{\\"terminal_id\\":\\"%s\\",\\"balance\\":%.2f,\\"equity\\":%.2f,"
      "\\"margin\\":%.2f,\\"free_margin\\":%.2f,\\"currency\\":\\"%s\\","
      "\\"leverage\\":%d,\\"auth_token\\":\\"%s\\"}",
      InpTerminalId,
      AccountInfoDouble(ACCOUNT_BALANCE),
      AccountInfoDouble(ACCOUNT_EQUITY),
      AccountInfoDouble(ACCOUNT_MARGIN),
      AccountInfoDouble(ACCOUNT_MARGIN_FREE),
      AccountInfoString(ACCOUNT_CURRENCY),
      (int)AccountInfoInteger(ACCOUNT_LEVERAGE),
      InpAuthToken);

   int code = HttpPost("/api/v1/bridge-http/poll", pollPayload, resp);
   if(code == 200 && StringLen(resp) > 0)
   {
      HandleIncoming(resp);
   }
}

//+------------------------------------------------------------------+
void OnTick()
{
   for(int i = 0; i < ArraySize(g_symbols); i++)
   {
      SymbolInfoTickStream(g_symbols[i]);
   }
}

//+------------------------------------------------------------------+
void SymbolInfoTickStream(string sym)
{
   MqlTick tk;
   if(!SymbolInfoTick(sym, tk)) return;

   static ulong last_time[];
   static double last_bid[];
   int idx = FindSymbolIndex(sym);
   if(idx < 0) return;

   if(ArraySize(last_time) <= idx)
   {
      ArrayResize(last_time, idx + 1);
      ArrayResize(last_bid, idx + 1);
      last_time[idx] = 0;
      last_bid[idx] = 0;
   }

   if(tk.time_msc == last_time[idx] && tk.bid == last_bid[idx]) return;
   last_time[idx] = tk.time_msc;
   last_bid[idx]  = tk.bid;

   string resp;
   string tickMsg = StringFormat(
      "{\\"terminal_id\\":\\"%s\\",\\"symbol\\":\\"%s\\",\\"bid\\":%.5f,\\"ask\\":%.5f,"
      "\\"last\\":%.5f,\\"volume\\":%.2f,\\"ts\\":\\"%s\\"}",
      InpTerminalId, sym, tk.bid, tk.ask, tk.last, tk.volume,
      TimeToString(tk.time, TIME_DATE | TIME_SECONDS));

   HttpPost("/api/v1/bridge-http/tick", tickMsg, resp);
}

//+------------------------------------------------------------------+
void HandleIncoming(string raw)
{
   if(StringFind(raw, "cmd.order.place") > 0)
   {
      HandlePlaceOrder(raw);
   }
   else if(StringFind(raw, "cmd.position.close") > 0)
   {
      HandleClosePosition(raw);
   }
}

//+------------------------------------------------------------------+
void HandlePlaceOrder(string raw)
{
   string clientOrderId = ExtractStringField(raw, "client_order_id");
   string symbol        = ExtractStringField(raw, "symbol");
   string side          = ExtractStringField(raw, "side");
   double volume        = ExtractDoubleField(raw, "volume");
   double price         = ExtractDoubleField(raw, "price");
   double sl            = ExtractDoubleField(raw, "stop_loss");
   double tp            = ExtractDoubleField(raw, "take_profit");

   bool ok = false;
   if(side == "buy")
      ok = trade.Buy(volume, symbol, price, sl, tp, clientOrderId);
   else
      ok = trade.Sell(volume, symbol, price, sl, tp, clientOrderId);

   string status = ok ? "filled" : "rejected";
   string reason = ok ? "" : "trade_request_failed";
   ulong order   = ok ? trade.ResultOrder() : 0;

   string resp;
   string reportPayload = StringFormat(
      "{\\"terminal_id\\":\\"%s\\",\\"event_type\\":\\"evt.order.filled\\","
      "\\"payload\\":{\\"client_order_id\\":\\"%s\\",\\"broker_order_id\\":\\"%I64u\\","
      "\\"status\\":\\"%s\\",\\"filled_volume\\":%.4f,\\"avg_price\\":%.5f,"
      "\\"rejection_reason\\":\\"%s\\"}}",
      InpTerminalId, clientOrderId, order, status,
      ok ? volume : 0.0, ok ? trade.ResultPrice() : 0.0, reason);

   HttpPost("/api/v1/bridge-http/report", reportPayload, resp);
}

//+------------------------------------------------------------------+
void HandleClosePosition(string raw)
{
   ulong posId = (ulong)StringToInteger(ExtractStringField(raw, "broker_position_id"));
   double volume = ExtractDoubleField(raw, "volume");
   bool ok = trade.PositionClosePartial(posId, volume > 0 ? volume : 0);

   string resp;
   string reportPayload = StringFormat(
      "{\\"terminal_id\\":\\"%s\\",\\"event_type\\":\\"evt.position.closed\\","
      "\\"payload\\":{\\"broker_position_id\\":\\"%I64u\\",\\"status\\":\\"%s\\"}}",
      InpTerminalId, posId, ok ? "closed" : "rejected");

   HttpPost("/api/v1/bridge-http/report", reportPayload, resp);
}

//+------------------------------------------------------------------+
//| Helpers                                                          |
//+------------------------------------------------------------------+
void SplitCSV(string csv, string &arr[])
{
   ArrayResize(arr, 0);
   string buf = csv;
   int pos;
   while((pos = StringFind(buf, ",")) >= 0)
   {
      ArrayResize(arr, ArraySize(arr) + 1);
      arr[ArraySize(arr) - 1] = StringSubstr(buf, 0, pos);
      buf = StringSubstr(buf, pos + 1);
   }
   if(StringLen(buf) > 0)
   {
      ArrayResize(arr, ArraySize(arr) + 1);
      arr[ArraySize(arr) - 1] = buf;
   }
}

string ArrayToJson(string &arr[])
{
   string s = "[";
   for(int i = 0; i < ArraySize(arr); i++)
   {
      if(i > 0) s += ",";
      s += "\\"" + arr[i] + "\\"";
   }
   return s + "]";
}

int FindSymbolIndex(string sym)
{
   for(int i = 0; i < ArraySize(g_symbols); i++)
      if(g_symbols[i] == sym) return i;
   return -1;
}

string ExtractStringField(string json, string key)
{
   string needle = "\\"" + key + "\\":\\"";
   int p = StringFind(json, needle);
   if(p < 0) return "";
   int start = p + StringLen(needle);
   int end = StringFind(json, "\\"", start);
   if(end < 0) return "";
   return StringSubstr(json, start, end - start);
}

double ExtractDoubleField(string json, string key)
{
   string needle = "\\"" + key + "\\":";
   int p = StringFind(json, needle);
   if(p < 0) return 0.0;
   int start = p + StringLen(needle);
   string rest = StringSubstr(json, start, 32);
   int end = 0;
   while(end < StringLen(rest))
   {
      ushort c = StringGetCharacter(rest, end);
      if(!(c == '-' || c == '.' || (c >= '0' && c <= '9'))) break;
      end++;
   }
   return StringToDouble(StringSubstr(rest, 0, end));
}
//+------------------------------------------------------------------+
`;

  return new NextResponse(eaContent, {
    status: 200,
    headers: {
      "Content-Type": "text/plain",
      "Content-Disposition": 'attachment; filename="BridgeEA.mq5"',
    },
  });
}
