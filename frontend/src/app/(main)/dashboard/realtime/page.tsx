"use client";

import { useEffect, useMemo, useState } from "react";

import { CandlestickChart } from "lucide-react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ErrorState, LoadingState, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { getCandles, listSymbols } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";
import { useTicks } from "@/lib/api/ws";

export default function RealtimePage() {
  const symbols = useAsync(() => listSymbols(), []);
  const [symbol, setSymbol] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState("M15");

  useEffect(() => {
    if (symbols.data && symbols.data.length > 0 && !symbols.data.find((s) => s.name === symbol)) {
      setSymbol(symbols.data[0].name);
    }
  }, [symbols.data, symbol]);

  const candles = useAsync(() => getCandles(symbol, timeframe, 300), [symbol, timeframe]);
  const { latest, buffer } = useTicks([symbol]);

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

  return (
    <div className="space-y-6">
      <PageHeader
        title="Real-time Trading"
        description="Live tick stream and price chart from the ATLAS market-data engine."
        actions={
          <div className="flex gap-2">
            <Input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} className="w-24" />
            <select
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
              className="h-9 rounded-md border bg-background px-2 text-sm"
            >
              {["M1", "M5", "M15", "H1", "H4", "D1"].map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
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
              {tick && (
                <Badge variant={Number(tick.ask) >= Number(tick.bid) ? "default" : "secondary"}>
                  {tick.bid} / {tick.ask}
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {candles.loading ? (
              <LoadingState rows={6} />
            ) : candles.error ? (
              <ErrorState message={candles.error.message} />
            ) : chartData.length === 0 ? (
              <p className="py-12 text-center text-sm text-muted-foreground">No candle data yet.</p>
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
                    stroke="hsl(var(--primary))"
                    dot={false}
                    strokeWidth={2}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Live Tick Stream</CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-72 pr-4">
              {buffer.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">Waiting for ticks on {symbol}…</p>
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
    </div>
  );
}
