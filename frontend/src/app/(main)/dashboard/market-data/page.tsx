"use client";

import { useEffect, useState } from "react";

import { Gauge } from "lucide-react";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ErrorState, LoadingState, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getCandles, listSymbols } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";

export default function MarketDataPage() {
  const symbols = useAsync(() => listSymbols(), []);
  const [symbol, setSymbol] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState("M15");

  useEffect(() => {
    if (symbols.data && symbols.data.length && !symbols.data.find((s) => s.name === symbol)) {
      setSymbol(symbols.data[0].name);
    }
  }, [symbols.data, symbol]);

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
            <Input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} className="w-24" />
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
              <p className="py-12 text-center text-sm text-muted-foreground">No candle data.</p>
            ) : (
              <ResponsiveContainer width="100%" height={340}>
                <ComposedChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis dataKey="ts" tick={{ fontSize: 11 }} minTickGap={32} />
                  <YAxis yAxisId="price" tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
                  <YAxis yAxisId="vol" orientation="right" tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar yAxisId="vol" dataKey="volume" fill="hsl(var(--muted))" opacity={0.4} />
                  <Line
                    yAxisId="price"
                    type="monotone"
                    dataKey="close"
                    stroke="hsl(var(--primary))"
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
