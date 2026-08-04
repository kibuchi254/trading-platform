"use client";

import { useEffect, useMemo, useState } from "react";

import { CandlestickChart, Radio } from "lucide-react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";

import { ErrorState, LoadingState, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { getCandles, listSymbols, listTerminals, placeOrder } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";
import { useAccount, useTicks } from "@/lib/api/ws";
import { formatCurrency } from "@/lib/utils";

export default function RealtimePage() {
  const terminals = useAsync(() => listTerminals("online"), []);
  const connectedTerminal = terminals.data?.[0] ?? null;

  // Source symbols from the connected terminal; fall back to DB symbols.
  const dbSymbols = useAsync(() => listSymbols(), []);
  const symbolOptions = useMemo(() => {
    if (connectedTerminal && connectedTerminal.symbols.length > 0) {
      return connectedTerminal.symbols;
    }
    return (dbSymbols.data ?? []).map((s) => s.name);
  }, [connectedTerminal, dbSymbols.data]);

  const [symbol, setSymbol] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState("M15");

  useEffect(() => {
    if (symbolOptions.length > 0 && !symbolOptions.includes(symbol)) {
      setSymbol(symbolOptions[0]);
    }
  }, [symbolOptions, symbol]);

  const candles = useAsync(() => getCandles(symbol, timeframe, 300), [symbol, timeframe]);
  const { latest, buffer } = useTicks([symbol]);
  const { account } = useAccount(connectedTerminal?.terminal_id ?? null);

  // ── Order ticket state ───────────────────────────────────────────────────
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [orderType, setOrderType] = useState<"market" | "limit">("market");
  const [volume, setVolume] = useState("0.10");
  const [price, setPrice] = useState("");
  const [stopLoss, setStopLoss] = useState("");
  const [takeProfit, setTakeProfit] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const chartData = useMemo(() => {
    const base = (candles.data ?? []).map((c) => ({
      ts: new Date(c.ts).toLocaleTimeString(),
      price: c.close,
    }));
    const liveTick = latest[symbol];
    if (liveTick?.ask) {
      base.push({ ts: "live", price: Number(liveTick.ask) });
    }
    return base;
  }, [candles.data, latest, symbol]);

  const tick = latest[symbol];
  const ticketDisabled = !connectedTerminal;

  async function submitOrder() {
    if (!connectedTerminal) return;
    setSubmitting(true);
    try {
      const res = await placeOrder({
        terminal_id: connectedTerminal.terminal_id,
        symbol,
        side,
        order_type: orderType,
        volume: Number(volume) || 0.01,
        price: orderType === "limit" && price ? Number(price) : null,
        stop_loss: stopLoss ? Number(stopLoss) : null,
        take_profit: takeProfit ? Number(takeProfit) : null,
      });
      if (res.status === "rejected") {
        toast.error(`Order rejected: ${res.rejection_reason ?? "unknown"}`);
      } else {
        toast.success(`${side.toUpperCase()} ${volume} ${symbol} — ${res.status}`);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Order failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Real-time Trading"
        description="Live tick stream and price chart sourced from your connected MT5 terminal."
        actions={
          <div className="flex items-center gap-2">
            {connectedTerminal ? (
              <Badge variant="default" className="gap-1">
                <Radio className="size-3" /> {connectedTerminal.broker_account}
              </Badge>
            ) : (
              <Badge variant="secondary">No terminal</Badge>
            )}
            {account && (
              <span className="text-muted-foreground text-xs tabular-nums">
                {formatCurrency(account.equity, { currency: account.currency })}
              </span>
            )}
          </div>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span className="flex items-center gap-2">
                <CandlestickChart className="size-4" /> {symbol} · {timeframe}
              </span>
              <div className="flex items-center gap-2">
                <select
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                  className="h-8 rounded-md border bg-background px-2 text-sm"
                >
                  {symbolOptions.length === 0 ? (
                    <option value={symbol}>{symbol}</option>
                  ) : (
                    symbolOptions.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))
                  )}
                </select>
                <select
                  value={timeframe}
                  onChange={(e) => setTimeframe(e.target.value)}
                  className="h-8 rounded-md border bg-background px-2 text-sm"
                >
                  {["M1", "M5", "M15", "H1", "H4", "D1"].map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
                {tick && (
                  <Badge variant={Number(tick.ask) >= Number(tick.bid) ? "default" : "secondary"}>
                    {tick.bid} / {tick.ask}
                  </Badge>
                )}
              </div>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {candles.loading ? (
              <LoadingState rows={6} />
            ) : candles.error ? (
              <ErrorState message={candles.error.message} />
            ) : chartData.length === 0 ? (
              <p className="py-12 text-center text-muted-foreground text-sm">No candle data yet.</p>
            ) : (
              <ResponsiveContainer width="100%" height={320}>
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis dataKey="ts" tick={{ fontSize: 11 }} minTickGap={32} />
                  <YAxis tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
                  <Tooltip />
                  <Line
                    type="monotone"
                    dataKey="price"
                    stroke="var(--color-primary)"
                    dot={false}
                    strokeWidth={2}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        {/* ── Order ticket ─────────────────────────────────────────────────── */}
        <Card>
          <CardHeader>
            <CardTitle>Order Ticket</CardTitle>
            <CardDescription>
              {connectedTerminal
                ? `Routed to ${connectedTerminal.terminal_id}`
                : "Connect a terminal to enable trading"}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <Button
                type="button"
                variant={side === "buy" ? "default" : "secondary"}
                onClick={() => setSide("buy")}
                disabled={ticketDisabled}
              >
                BUY
              </Button>
              <Button
                type="button"
                variant={side === "sell" ? "destructive" : "secondary"}
                onClick={() => setSide("sell")}
                disabled={ticketDisabled}
              >
                SELL
              </Button>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label className="text-muted-foreground text-xs">Volume</Label>
                <Input
                  value={volume}
                  onChange={(e) => setVolume(e.target.value)}
                  className="h-8 tabular-nums"
                  inputMode="decimal"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-muted-foreground text-xs">Type</Label>
                <select
                  value={orderType}
                  onChange={(e) => setOrderType(e.target.value as "market" | "limit")}
                  className="h-8 w-full rounded-md border bg-background px-2 text-sm"
                >
                  <option value="market">Market</option>
                  <option value="limit">Limit</option>
                </select>
              </div>
            </div>

            {orderType === "limit" && (
              <div className="space-y-1">
                <Label className="text-muted-foreground text-xs">Limit Price</Label>
                <Input
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  className="h-8 tabular-nums"
                  inputMode="decimal"
                />
              </div>
            )}

            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label className="text-muted-foreground text-xs">Stop Loss</Label>
                <Input
                  value={stopLoss}
                  onChange={(e) => setStopLoss(e.target.value)}
                  className="h-8 tabular-nums"
                  inputMode="decimal"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-muted-foreground text-xs">Take Profit</Label>
                <Input
                  value={takeProfit}
                  onChange={(e) => setTakeProfit(e.target.value)}
                  className="h-8 tabular-nums"
                  inputMode="decimal"
                />
              </div>
            </div>

            <Button
              type="button"
              className="w-full"
              variant={side === "buy" ? "default" : "destructive"}
              onClick={submitOrder}
              disabled={ticketDisabled || submitting}
            >
              {submitting ? "Submitting…" : `${side.toUpperCase()} ${volume} ${symbol}`}
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* ── Live tick stream ───────────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Live Tick Stream</CardTitle>
        </CardHeader>
        <CardContent>
          <ScrollArea className="h-72 pr-4">
            {buffer.length === 0 ? (
              <p className="py-8 text-center text-muted-foreground text-sm">Waiting for ticks on {symbol}…</p>
            ) : (
              <ul className="space-y-1 text-xs">
                {buffer
                  .slice()
                  .reverse()
                  .map((t, i) => (
                    // biome-ignore lint/suspicious/noArrayIndexKey: append-only tick buffer, index is acceptable
                    <li key={i} className="flex justify-between border-b py-1 tabular-nums">
                      <span className="text-muted-foreground">{t.ts ? new Date(t.ts).toLocaleTimeString() : ""}</span>
                      <span>
                        {t.symbol} {t.bid}/{t.ask}
                      </span>
                    </li>
                  ))}
              </ul>
            )}
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
}
