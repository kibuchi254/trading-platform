//+------------------------------------------------------------------+
//|                                                      BridgeEA.mq5 |
//|                            ATLAS Trading Platform — MT5 Bridge EA |
//|                                                                  |
//| This EA runs inside MetaTrader 5 (under Wine on the host). It     |
//| opens a WebSocket connection to the ATLAS Bridge Service,         |
//| registers itself, streams ticks + execution reports, and          |
//| executes commands (place/cancel/modify order, close position).   |
//|                                                                  |
//| The backend NEVER talks to MT5 directly — only through this EA.  |
//| Replacing MT5 with another adapter means writing a new bridge     |
//| client for that venue; the platform core stays unchanged.         |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property copyright "ATLAS Platform"
#property description "ATLAS Bridge EA — connects MT5 to the ATLAS backend"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\HistoryOrderInfo.mqh>
#include <Trade\DealInfo.mqh>

//--- inputs
input string   InpBridgeUrl         = "ws://127.0.0.1:9000";
input string   InpTerminalId        = "mt5-exness-01";
input string   InpBroker            = "Exness";
input string   InpAuthToken         = "change-me-bridge-token";
input string   InpSymbolsCSV        = "XAUUSD,XTIUSD,EURUSD,GBPUSD";
input int      InpHeartbeatSeconds  = 10;
input int      InpReconnectMs       = 3000;
input int      InpMagic             = 770000;

//--- WebSocket is implemented via a DLL (websockets.dll) shipped alongside
//   the EA. See mql5/websocket/README.md for build instructions.
#import "atlas_bridge.dll"
   int      ws_connect(string url);
   void     ws_close(int handle);
   int      ws_send(int handle, string msg);
   string   ws_recv(int handle, int timeout_ms);
   bool     ws_is_open(int handle);
#import

CTrade              trade;
CPositionInfo       posInfo;
CHistoryOrderInfo   histOrder;
CDealInfo           dealInfo;

int    g_wsHandle    = -1;
ulong  g_lastHeartbeat = 0;
string g_symbols[];

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

   Print("[ATLAS] BridgeEA starting. terminal=", InpTerminalId, " broker=", InpBroker);

   if(!ConnectAndRegister())
   {
      Print("[ATLAS] Initial connect failed; will retry in timer.");
   }

   EventSetTimer(1);  // 1-second tick for housekeeping
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(g_wsHandle >= 0)
   {
      ws_close(g_wsHandle);
      g_wsHandle = -1;
   }
   EventKillTimer();
   Print("[ATLAS] BridgeEA stopped. reason=", reason);
}

//+------------------------------------------------------------------+
void OnTimer()
{
   // 1. Maintain connection
   if(g_wsHandle < 0 || !ws_is_open(g_wsHandle))
   {
      Sleep(InpReconnectMs);
      ConnectAndRegister();
      return;
   }

   // 2. Drain incoming messages
   string msg;
   while((msg = ws_recv(g_wsHandle, 0)) != "")
   {
      HandleIncoming(msg);
   }

   // 3. Heartbeat
   if(GetTickCount64() - g_lastHeartbeat > InpHeartbeatSeconds * 1000)
   {
      SendHeartbeat();
   }
}

//+------------------------------------------------------------------+
void OnTick()
{
   // Stream ticks for every configured symbol
   for(int i = 0; i < ArraySize(g_symbols); i++)
   {
      SymbolInfoTickStream(g_symbols[i]);
   }
}

//+------------------------------------------------------------------+
//| Connect & register with the Bridge                               |
//+------------------------------------------------------------------+
bool ConnectAndRegister()
{
   g_wsHandle = ws_connect(InpBridgeUrl);
   if(g_wsHandle < 0)
   {
      Print("[ATLAS] ws_connect failed: ", g_wsHandle);
      return false;
   }

   string symbolsJson = ArrayToJson(g_symbols);
   string regMsg = StringFormat(
      "{\"v\":1,\"t\":\"evt.register\",\"terminal_id\":\"%s\","
      "\"payload\":{\"terminal_id\":\"%s\",\"broker\":\"%s\","
      "\"account\":%I64u,\"version\":\"%s\",\"symbols\":%s,"
      "\"auth_token\":\"%s\",\"capabilities\":{\"market\":true,\"limit\":true,"
      "\"stop\":true,\"close_partial\":true}}}",
      InpTerminalId, InpTerminalId, InpBroker,
      AccountInfoInteger(ACCOUNT_LOGIN),
      TerminalInfoString(TERMINAL_VERSION),
      symbolsJson, InpAuthToken);

   int sent = ws_send(g_wsHandle, regMsg);
   if(sent <= 0)
   {
      Print("[ATLAS] register send failed");
      ws_close(g_wsHandle);
      g_wsHandle = -1;
      return false;
   }
   g_lastHeartbeat = GetTickCount64();
   Print("[ATLAS] Registered with bridge.");
   return true;
}

//+------------------------------------------------------------------+
//| Heartbeat                                                        |
//+------------------------------------------------------------------+
void SendHeartbeat()
{
   if(g_wsHandle < 0) return;
   string hb = StringFormat(
      "{\"v\":1,\"t\":\"evt.heartbeat\",\"terminal_id\":\"%s\","
      "\"payload\":{\"terminal_id\":\"%s\",\"latency_ms\":0}}",
      InpTerminalId, InpTerminalId);
   ws_send(g_wsHandle, hb);
   g_lastHeartbeat = GetTickCount64();
}

//+------------------------------------------------------------------+
//| Stream a tick for a symbol                                       |
//+------------------------------------------------------------------+
void SymbolInfoTickStream(string sym)
{
   MqlTick tk;
   if(!SymbolInfoTick(sym, tk)) return;

   // Throttle: only send if changed
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

   string tickMsg = StringFormat(
      "{\"v\":1,\"t\":\"evt.tick\",\"terminal_id\":\"%s\","
      "\"payload\":{\"symbol\":\"%s\",\"bid\":%.5f,\"ask\":%.5f,"
      "\"last\":%.5f,\"volume\":%.2f,\"ts\":\"%s\"}}",
      InpTerminalId, sym, tk.bid, tk.ask, tk.last, tk.volume,
      TimeToString(tk.time, TIME_DATE | TIME_SECONDS));
   ws_send(g_wsHandle, tickMsg);
}

//+------------------------------------------------------------------+
//| Handle incoming command from Bridge                              |
//+------------------------------------------------------------------+
void HandleIncoming(string raw)
{
   // Parse the command type — production uses a real JSON parser.
   // Skeleton: detect by substring.
   if(StringFind(raw, "cmd.order.place") > 0)
   {
      HandlePlaceOrder(raw);
   }
   else if(StringFind(raw, "cmd.order.cancel") > 0)
   {
      HandleCancelOrder(raw);
   }
   else if(StringFind(raw, "cmd.position.close") > 0)
   {
      HandleClosePosition(raw);
   }
   else if(StringFind(raw, "cmd.position.sync") > 0)
   {
      HandleSyncPositions(raw);
   }
   else if(StringFind(raw, "cmd.account.sync") > 0)
   {
      HandleSyncAccount(raw);
   }
   else if(StringFind(raw, "cmd.ticks.subscribe") > 0)
   {
      // OK — we already stream everything; no-op
   }
   else if(StringFind(raw, "cmd.ping") > 0)
   {
      ws_send(g_wsHandle, "{\"v\":1,\"t\":\"cmd.ping\",\"payload\":{\"pong\":true}}");
   }
}

//+------------------------------------------------------------------+
//| Place order                                                      |
//+------------------------------------------------------------------+
void HandlePlaceOrder(string raw)
{
   // Skeleton: in production, parse JSON properly with a JSON lib.
   // Here we demonstrate the success path.
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

   string reply = StringFormat(
      "{\"v\":1,\"t\":\"evt.order.filled\",\"terminal_id\":\"%s\","
      "\"payload\":{\"client_order_id\":\"%s\",\"broker_order_id\":\"%I64u\","
      "\"status\":\"%s\",\"filled_volume\":%.4f,\"avg_price\":%.5f,"
      "\"rejection_reason\":\"%s\",\"executed_at\":\"%s\"}}",
      InpTerminalId, clientOrderId, order, status,
      ok ? volume : 0.0, ok ? trade.ResultPrice() : 0.0,
      reason, TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS));
   ws_send(g_wsHandle, reply);
}

//+------------------------------------------------------------------+
//| Cancel order                                                     |
//+------------------------------------------------------------------+
void HandleCancelOrder(string raw)
{
   ulong brokerOrderId = (ulong)StringToInteger(ExtractStringField(raw, "broker_order_id"));
   bool ok = trade.OrderDelete(brokerOrderId);
   string reply = StringFormat(
      "{\"v\":1,\"t\":\"evt.order.cancelled\",\"terminal_id\":\"%s\","
      "\"payload\":{\"broker_order_id\":\"%I64u\",\"status\":\"%s\"}}",
      InpTerminalId, brokerOrderId, ok ? "cancelled" : "rejected");
   ws_send(g_wsHandle, reply);
}

//+------------------------------------------------------------------+
//| Close position                                                   |
//+------------------------------------------------------------------+
void HandleClosePosition(string raw)
{
   ulong posId = (ulong)StringToInteger(ExtractStringField(raw, "broker_position_id"));
   double volume = ExtractDoubleField(raw, "volume");
   bool ok = trade.PositionClosePartial(posId, volume > 0 ? volume : 0);
   string reply = StringFormat(
      "{\"v\":1,\"t\":\"evt.position.closed\",\"terminal_id\":\"%s\","
      "\"payload\":{\"broker_position_id\":\"%I64u\",\"status\":\"%s\"}}",
      InpTerminalId, posId, ok ? "closed" : "rejected");
   ws_send(g_wsHandle, reply);
}

//+------------------------------------------------------------------+
//| Sync all positions                                               |
//+------------------------------------------------------------------+
void HandleSyncPositions(string raw)
{
   // Build a JSON array of all open positions
   string positions = "[";
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
   {
      if(posInfo.SelectByIndex(i))
      {
         if(i > 0) positions += ",";
         positions += StringFormat(
            "{\"broker_position_id\":\"%I64u\",\"symbol\":\"%s\","
            "\"side\":\"%s\",\"volume\":%.4f,\"open_price\":%.5f,"
            "\"current_price\":%.5f,\"swap\":%.5f,\"unrealized_pnl\":%.2f,"
            "\"opened_at\":\"%s\"}",
            posInfo.Ticket(), posInfo.Symbol(),
            posInfo.PositionType() == POSITION_TYPE_BUY ? "buy" : "sell",
            posInfo.Volume(), posInfo.PriceOpen(), posInfo.PriceCurrent(),
            posInfo.Swap(), posInfo.Profit(),
            TimeToString((datetime)posInfo.Time(), TIME_DATE | TIME_SECONDS));
      }
   }
   positions += "]";

   string reply = StringFormat(
      "{\"v\":1,\"t\":\"cmd.position.sync\",\"terminal_id\":\"%s\","
      "\"payload\":{\"positions\":%s}}",
      InpTerminalId, positions);
   ws_send(g_wsHandle, reply);
}

//+------------------------------------------------------------------+
//| Sync account                                                     |
//+------------------------------------------------------------------+
void HandleSyncAccount(string raw)
{
   string reply = StringFormat(
      "{\"v\":1,\"t\":\"evt.account.update\",\"terminal_id\":\"%s\","
      "\"payload\":{\"balance\":%.2f,\"equity\":%.2f,\"margin\":%.2f,"
      "\"free_margin\":%.2f,\"currency\":\"%s\",\"leverage\":%d}}",
      InpTerminalId,
      AccountInfoDouble(ACCOUNT_BALANCE),
      AccountInfoDouble(ACCOUNT_EQUITY),
      AccountInfoDouble(ACCOUNT_MARGIN),
      AccountInfoDouble(ACCOUNT_MARGIN_FREE),
      AccountInfoString(ACCOUNT_CURRENCY),
      (int)AccountInfoInteger(ACCOUNT_LEVERAGE));
   ws_send(g_wsHandle, reply);
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
      s += "\"" + arr[i] + "\"";
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
   // Skeleton — use a real JSON parser in production.
   string needle = "\"" + key + "\":\"";
   int p = StringFind(json, needle);
   if(p < 0) return "";
   int start = p + StringLen(needle);
   int end = StringFind(json, "\"", start);
   if(end < 0) return "";
   return StringSubstr(json, start, end - start);
}

double ExtractDoubleField(string json, string key)
{
   string needle = "\"" + key + "\":";
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
