"use client";

import { Activity, Gauge, Radio, ShieldAlert, TrendingUp } from "lucide-react";

import { ErrorState, LoadingState, MetricCard, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getOpenPositions, getPerformance, getSystemStatus } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";
import { useTerminalEvents } from "@/lib/api/ws";
import { formatCurrency } from "@/lib/utils";

export default function OverviewPage() {
  const status = useAsync(() => getSystemStatus(), []);
  const perf = useAsync(() => getPerformance(30), []);
  const positions = useAsync(() => getOpenPositions(), []);
  const events = useTerminalEvents();

  const pnl = perf.data?.total_pnl ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader title="Overview" description="Live snapshot of your trading organization." />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {status.loading ? (
          <LoadingState rows={1} />
        ) : status.error ? (
          <ErrorState message={status.error.message} />
        ) : (
          <>
            <MetricCard
              title="Terminals Online"
              value={status.data?.terminals_online ?? 0}
              icon={<Radio className="size-4" />}
              description="Connected MT5 terminals"
            />
            <MetricCard
              title="Pending Commands"
              value={status.data?.pending_commands ?? 0}
              icon={<Gauge className="size-4" />}
              description="Awaiting terminal acks"
            />
            <MetricCard
              title="Kill Switch"
              value={status.data?.risk_kill_switch ? "ENGAGED" : "ARMED"}
              tone={status.data?.risk_kill_switch ? "negative" : "positive"}
              icon={<ShieldAlert className="size-4" />}
              description={status.data?.env ? `env: ${status.data.env}` : undefined}
            />
            <MetricCard
              title="30d P&L"
              value={formatCurrency(pnl)}
              tone={pnl >= 0 ? "positive" : "negative"}
              icon={<TrendingUp className="size-4" />}
            />
          </>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="size-4" /> Open Positions
            </CardTitle>
          </CardHeader>
          <CardContent>
            {positions.loading ? (
              <LoadingState rows={4} />
            ) : positions.error ? (
              <ErrorState message={positions.error.message} />
            ) : positions.data && positions.data.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Side</TableHead>
                    <TableHead className="text-right">Volume</TableHead>
                    <TableHead className="text-right">Open</TableHead>
                    <TableHead className="text-right">uP&L</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {positions.data.map((p) => (
                    <TableRow key={p.id}>
                      <TableCell className="font-medium">{p.symbol}</TableCell>
                      <TableCell>
                        <Badge variant={p.side === "buy" ? "default" : "secondary"}>{p.side}</Badge>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{p.volume}</TableCell>
                      <TableCell className="text-right tabular-nums">{p.open_price}</TableCell>
                      <TableCell
                        className={`text-right tabular-nums ${p.unrealized_pnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`}
                      >
                        {formatCurrency(p.unrealized_pnl)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="py-8 text-center text-sm text-muted-foreground">No open positions.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Radio className="size-4" /> Live Events
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-72 pr-4">
              {events.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  Waiting for terminal / execution / risk events…
                </p>
              ) : (
                <ul className="space-y-2">
                  {events.map((e, i) => (
                    // biome-ignore lint/suspicious/noArrayIndexKey: live event feed has no stable id; order is append-mostly
                    <li key={i} className="rounded-md border px-3 py-2 text-xs">
                      <span className="font-medium">{String(e.type ?? "event")}</span>
                      {e.terminal_id ? (
                        <span className="ml-2 text-muted-foreground">{String(e.terminal_id)}</span>
                      ) : null}
                      {e.symbol ? <span className="ml-2 text-muted-foreground">{String(e.symbol)}</span> : null}
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
