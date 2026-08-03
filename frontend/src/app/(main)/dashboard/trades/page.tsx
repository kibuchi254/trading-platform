"use client";

import { useState } from "react";

import { ShoppingBag } from "lucide-react";

import { ErrorState, LoadingState, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { listTrades } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";
import { formatCurrency } from "@/lib/utils";

export default function TradesPage() {
  const [symbol, setSymbol] = useState("");
  const { data, error, loading } = useAsync(() => listTrades(symbol ? { symbol } : { limit: 200 }), [symbol]);

  const totalPnl = (data ?? []).reduce((acc, t) => acc + t.pnl, 0);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Trades — the books"
        description="Closed-trade ledger (realized P&L) for the organization."
        actions={
          <Input
            placeholder="Filter by symbol…"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            className="w-40"
          />
        }
      />
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <ShoppingBag className="size-4" /> Trade Ledger
          </CardTitle>
          <div className="text-sm">
            Total realized:{" "}
            <span
              className={`font-semibold tabular-nums ${totalPnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`}
            >
              {formatCurrency(totalPnl)}
            </span>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <LoadingState rows={8} />
          ) : error ? (
            <ErrorState message={error.message} />
          ) : data && data.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Side</TableHead>
                  <TableHead className="text-right">Volume</TableHead>
                  <TableHead className="text-right">Entry</TableHead>
                  <TableHead className="text-right">Exit</TableHead>
                  <TableHead className="text-right">Pips</TableHead>
                  <TableHead className="text-right">P&L</TableHead>
                  <TableHead>Closed</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-medium">{t.symbol}</TableCell>
                    <TableCell>
                      <Badge variant={t.side === "buy" ? "default" : "secondary"}>{t.side}</Badge>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{t.volume}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.entry_price}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.exit_price}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.pips}</TableCell>
                    <TableCell
                      className={`text-right tabular-nums ${t.pnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`}
                    >
                      {formatCurrency(t.pnl)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(t.closed_at).toLocaleString()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="py-8 text-center text-sm text-muted-foreground">No closed trades.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
