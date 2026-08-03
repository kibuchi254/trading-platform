"use client";

import { useState } from "react";

import { Activity } from "lucide-react";
import { toast } from "sonner";

import { ErrorState, LoadingState, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { closePosition, listPositions, modifyPosition } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";
import { formatCurrency } from "@/lib/utils";

export default function PositionsPage() {
  const [status, setStatus] = useState("all");
  const { data, error, loading, reload } = useAsync(() => listPositions(status), [status]);
  const [modifyId, setModifyId] = useState<string | null>(null);
  const [sl, setSl] = useState("");
  const [tp, setTp] = useState("");

  async function close(id: string) {
    try {
      await closePosition(id);
      toast.success("Position closed");
      reload();
    } catch (e) {
      toast.error("Close failed", { description: (e as Error).message });
    }
  }

  async function doModify() {
    if (!modifyId) return;
    try {
      await modifyPosition(modifyId, {
        stop_loss: sl ? Number(sl) : undefined,
        take_profit: tp ? Number(tp) : undefined,
      });
      toast.success("Position modified");
      setModifyId(null);
      setSl("");
      setTp("");
      reload();
    } catch (e) {
      toast.error("Modify failed", { description: (e as Error).message });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Positions"
        description="Open and closed positions across all terminals."
        actions={
          <select
            className="h-9 rounded-md border bg-background px-2 text-sm"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="all">All</option>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
          </select>
        }
      />
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="size-4" /> Positions
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <LoadingState rows={6} />
          ) : error ? (
            <ErrorState message={error.message} />
          ) : data && data.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Side</TableHead>
                  <TableHead className="text-right">Volume</TableHead>
                  <TableHead className="text-right">Open</TableHead>
                  <TableHead className="text-right">Current</TableHead>
                  <TableHead className="text-right">uP&L</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-medium">{p.symbol}</TableCell>
                    <TableCell>
                      <Badge variant={p.side === "buy" ? "default" : "secondary"}>{p.side}</Badge>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{p.volume}</TableCell>
                    <TableCell className="text-right tabular-nums">{p.open_price}</TableCell>
                    <TableCell className="text-right tabular-nums">{p.current_price}</TableCell>
                    <TableCell
                      className={`text-right tabular-nums ${p.unrealized_pnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`}
                    >
                      {formatCurrency(p.unrealized_pnl)}
                    </TableCell>
                    <TableCell>
                      <Badge variant={p.status === "open" ? "default" : "outline"}>{p.status}</Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      {p.status === "open" && (
                        <div className="flex justify-end gap-1">
                          <Dialog open={modifyId === p.id} onOpenChange={(o) => setModifyId(o ? p.id : null)}>
                            <DialogTrigger asChild>
                              <Button size="sm" variant="ghost">
                                Modify
                              </Button>
                            </DialogTrigger>
                            <DialogContent className="sm:max-w-sm">
                              <DialogHeader>
                                <DialogTitle>Modify {p.symbol}</DialogTitle>
                              </DialogHeader>
                              <div className="grid grid-cols-2 gap-3 py-2">
                                <div className="space-y-1">
                                  <Label>Stop Loss</Label>
                                  <Input value={sl} onChange={(e) => setSl(e.target.value)} />
                                </div>
                                <div className="space-y-1">
                                  <Label>Take Profit</Label>
                                  <Input value={tp} onChange={(e) => setTp(e.target.value)} />
                                </div>
                              </div>
                              <DialogFooter>
                                <Button onClick={doModify}>Save</Button>
                              </DialogFooter>
                            </DialogContent>
                          </Dialog>
                          <Button size="sm" variant="destructive" onClick={() => close(p.id)}>
                            Close
                          </Button>
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="py-8 text-center text-sm text-muted-foreground">No positions.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
