import { NextResponse } from "next/server";

export async function GET() {
  const eaContent = `//+------------------------------------------------------------------+
//|                                                      BridgeEA.mq5 |
//|                            ATLAS Trading Platform — MT5 Bridge EA |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property copyright "ATLAS Platform"
#property description "ATLAS Bridge EA — connects MT5 to the ATLAS backend"

#include <Trade\\Trade.mqh>
#include <Trade\\PositionInfo.mqh>
#include <Trade\\HistoryOrderInfo.mqh>
#include <Trade\\DealInfo.mqh>

//--- inputs
input string   InpBridgeUrl         = "wss://your-atlas-domain/bridge/";
input string   InpTerminalId        = "mt5-terminal-01";
input string   InpBroker            = "Exness";
input string   InpAuthToken         = "your-bridge-auth-token";
input string   InpSymbolsCSV        = "XAUUSD,EURUSD,GBPUSD,USDJPY";
input int      InpHeartbeatSeconds  = 10;
input int      InpReconnectMs       = 3000;
input int      InpMagic             = 770000;

#import "atlas_bridge.dll"
   int      ws_connect(string url);
   void     ws_close(int handle);
   int      ws_send(int handle, string msg);
   string   ws_recv(int handle, int timeout_ms);
   bool     ws_is_open(int handle);
#import

// Refer to documentation for full source or compile atlas_bridge.dll
`;

  return new NextResponse(eaContent, {
    status: 200,
    headers: {
      "Content-Type": "text/plain",
      "Content-Disposition": 'attachment; filename="BridgeEA.mq5"',
    },
  });
}
