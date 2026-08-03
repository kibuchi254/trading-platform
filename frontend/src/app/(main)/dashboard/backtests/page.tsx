"use client";

import { useState } from "react";

import { LineChart, Play } from "lucide-react";
import { toast } from "sonner";

import { ErrorState, LoadingState, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { listBacktests, listStrategies, runBacktest } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";
import { formatCurrency } from "@/lib/utils";

const STATUS_TONE: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  completed: "default",
  running: "secondary",
  pending: "outline",
  failed: "destructive",
};

export default function BacktestsPage() {
  const backtests = useAsync(() => listBacktests(50), []);
  const strategies = useAsync(() => listStrategies(), []);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    strategy_id: "",
    symbol: "EURUSD",
    timeframe: "M15",
    start: "",
    end: "",
    initial_capital: "10000",
  });
  const [busy, setBusy] = useState(false);

  async function run() {
    if (!form.strategy_id || !form.start || !form.end) {
      toast.error("Fill all fields");
      return;
    }
    setBusy(true);
    try {
      const res = await runBacktest({
        strategy_id: form.strategy_id,
        symbol: form.symbol,
        timeframe: form.timeframe,
        start: new Date(form.start).toISOString(),
        end: new Date(form.end).toISOString(),
        initial_capital: Number(form.initial_capital),
      });
      toast.success("Backtest queued", { description: `id: ${res.backtest_id}` });
      setOpen(false);
      backtests.reload();
    } catch (e) {
      toast.error("Run failed", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Backtests"
        description="Historical strategy simulations run on the Celery backtest worker."
        actions={
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button size="sm">
                <Play className="size-4" /> Run Backtest
              </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-lg">
              <DialogHeader>
                <DialogTitle>Run Backtest</DialogTitle>
              </DialogHeader>
              <div className="grid grid-cols-2 gap-3 py-2">
                <div className="col-span-2 space-y-1">
                  <Label>Strategy</Label>
                  <select
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                    value={form.strategy_id}
                    onChange={(e) => setForm({ ...form, strategy_id: e.target.value })}
                  >
                    <option value="">Select…</option>
                    {(strategies.data ?? []).map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </div>
                <Field label="Symbol" value={form.symbol} onChange={(v) => setForm({ ...form, symbol: v })} />
                <div className="space-y-1">
                  <Label>Timeframe</Label>
                  <select
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                    value={form.timeframe}
                    onChange={(e) => setForm({ ...form, timeframe: e.target.value })}
                  >
                    {["M1", "M5", "M15", "H1", "H4", "D1"].map((t) => (
                      <option key={t}>{t}</option>
                    ))}
                  </select>
                </div>
                <Field
                  label="Start (datetime)"
                  value={form.start}
                  onChange={(v) => setForm({ ...form, start: v })}
                  type="datetime-local"
                />
                <Field
                  label="End (datetime)"
                  value={form.end}
                  onChange={(v) => setForm({ ...form, end: v })}
                  type="datetime-local"
                />
                <Field
                  label="Initial Capital"
                  value={form.initial_capital}
                  onChange={(v) => setForm({ ...form, initial_capital: v })}
                />
              </div>
              <DialogFooter>
                <Button onClick={run} disabled={busy}>
                  {busy ? "Queuing…" : "Queue"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <LineChart className="size-4" /> Backtests
          </CardTitle>
        </CardHeader>
        <CardContent>
          {backtests.loading ? (
            <LoadingState rows={5} />
          ) : backtests.error ? (
            <ErrorState message={backtests.error.message} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Strategy</TableHead>
                  <TableHead>Symbol</TableHead>
                  <TableHead>TF</TableHead>
                  <TableHead className="text-right">Capital</TableHead>
                  <TableHead className="text-right">Final Equity</TableHead>
                  <TableHead className="text-right">Max DD</TableHead>
                  <TableHead className="text-right">Sharpe</TableHead>
                  <TableHead className="text-right">Trades</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(backtests.data ?? []).map((b) => (
                  <TableRow key={b.id}>
                    <TableCell className="font-medium">{b.strategy_id.slice(0, 8)}</TableCell>
                    <TableCell>{b.symbol}</TableCell>
                    <TableCell>{b.timeframe}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatCurrency(b.initial_capital)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {b.final_equity != null ? formatCurrency(b.final_equity) : "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {b.max_drawdown != null ? `${(b.max_drawdown * 100).toFixed(2)}%` : "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {b.sharpe != null ? b.sharpe.toFixed(2) : "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{b.trades_count}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_TONE[b.status] ?? "outline"}>{b.status}</Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
}) {
  return (
    <div className="space-y-1">
      <Label>{label}</Label>
      <Input type={type} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}
