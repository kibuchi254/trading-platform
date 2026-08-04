"use client";

import { useEffect, useMemo, useState } from "react";

import { Gauge } from "lucide-react";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ErrorState, LoadingState, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getCandles, listSymbols, listTerminals } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";

export default function MarketDataPage() {
  const symbols = useAsync(() => listSymbols(), []);
  const terminals = useAsync(() => listTerminals("online"), []);
  const connectedTerminal = terminals.data?.[0] ?? null;
  const [symbol, setSymbol] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState("M15");

  const symbolOptions = useMemo(() => {
    if (connectedTerminal && connectedTerminal.symbols.length > 0) {
      return connectedTerminal.symbols;
    }
    return (symbols.data ?? []).map((s) => s.name);
  }, [connectedTerminal, symbols.data]);

  useEffect(() => {
    if (symbolOptions.length > 0 && !symbolOptions.includes(symbol)) {
      setSymbol(symbolOptions[0]);
    }
  }, [symbolOptions, symbol]);

  const candles = useAsync(() => getCandles(symbol, timeframe, 200), [symbol, timeframe]);
  const chartData = (candles.data ?? []).map((c) => ({
    ts: new Date(c.ts).toLocaleTimeString(),
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
    volume: c.volume,
  }));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Market Data"
        description="Instrument catalog and historical OHLC bars."
        actions={
          <div className="flex gap-2">
            <select
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="h-9 rounded-md border bg-background px-2 text-sm"
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
              className="h-9 rounded-md border bg-background px-2 text-sm"
            >
              {["M1", "M5", "M15", "H1", "H4", "D1"].map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </div>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Gauge className="size-4" /> {symbol} · {timeframe}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {candles.loading ? (
              <LoadingState rows={6} />
            ) : candles.error ? (
              <ErrorState message={candles.error.message} />
            ) : chartData.length === 0 ? (
              <p className="py-12 text-center text-muted-foreground text-sm">No candle data.</p>
            ) : (
              <ResponsiveContainer width="100%" height={340}>
                <ComposedChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis dataKey="ts" tick={{ fontSize: 11 }} minTickGap={32} />
                  <YAxis yAxisId="price" tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
                  <YAxis yAxisId="vol" orientation="right" tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar yAxisId="vol" dataKey="volume" fill="var(--color-muted)" opacity={0.4} />
                  <Line
                    yAxisId="price"
                    type="monotone"
                    dataKey="close"
                    stroke="var(--color-primary)"
                    dot={false}
                    strokeWidth={2}
                    isAnimationActive={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Instrument Catalog</CardTitle>
          </CardHeader>
          <CardContent>
            {symbols.loading ? (
              <LoadingState rows={6} />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Category</TableHead>
                    <TableHead className="text-right">Digits</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(symbols.data ?? []).slice(0, 30).map((s) => (
                    <TableRow key={s.id}>
                      <TableCell className="font-medium">{s.name}</TableCell>
                      <TableCell>{s.category && <Badge variant="outline">{s.category}</Badge>}</TableCell>
                      <TableCell className="text-right tabular-nums">{s.digits}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
