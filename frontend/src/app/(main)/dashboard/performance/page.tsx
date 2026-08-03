"use client";

import { LineChart, TrendingUp } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ErrorState, LoadingState, MetricCard, PageHeader } from "@/components/atlas/ui";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getPerformance, listTrades } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";
import { formatCurrency } from "@/lib/utils";

export default function PerformancePage() {
  const perf = useAsync(() => getPerformance(30), []);
  const trades = useAsync(() => listTrades({ limit: 200 }), []);

  // Bucket trades per day for a realized-PnL bar chart.
  const daily = (trades.data ?? []).reduce<Record<string, number>>((acc, t) => {
    const day = new Date(t.closed_at).toLocaleDateString();
    acc[day] = (acc[day] ?? 0) + t.pnl;
    return acc;
  }, {});
  const chartData = Object.entries(daily)
    .map(([day, pnl]) => ({ day, pnl }))
    .slice(-30);

  const p = perf.data;

  return (
    <div className="space-y-6">
      <PageHeader title="Performance" description="Realized P&L and trade-quality summary." />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {perf.loading ? (
          <LoadingState rows={1} />
        ) : perf.error ? (
          <ErrorState message={perf.error.message} />
        ) : (
          <>
            <MetricCard title="Total Trades (30d)" value={p?.total_trades ?? 0} />
            <MetricCard title="Win Rate" value={`${((p?.win_rate ?? 0) * 100).toFixed(1)}%`} tone="positive" />
            <MetricCard
              title="Net P&L"
              value={formatCurrency(p?.total_pnl ?? 0)}
              tone={(p?.total_pnl ?? 0) >= 0 ? "positive" : "negative"}
              icon={<TrendingUp className="size-4" />}
            />
            <MetricCard title="Avg P&L / Trade" value={formatCurrency(p?.avg_pnl ?? 0)} />
          </>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <LineChart className="size-4" /> Daily Realized P&L
          </CardTitle>
        </CardHeader>
        <CardContent>
          {chartData.length === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">No closed trades in range.</p>
          ) : (
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v: unknown) => formatCurrency(Number(v))} />
                <Bar dataKey="pnl" fill="hsl(var(--primary))" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-3">
        <MetricCard title="Best Trade" value={formatCurrency(p?.best_trade ?? 0)} tone="positive" />
        <MetricCard title="Worst Trade" value={formatCurrency(p?.worst_trade ?? 0)} tone="negative" />
        <MetricCard title="Avg Duration" value={`${Math.round((p?.avg_duration_seconds ?? 0) / 60)}m`} />
      </div>
    </div>
  );
}
