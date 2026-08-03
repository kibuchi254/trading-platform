"use client";

import { useState } from "react";

import { ListOrdered, Plus } from "lucide-react";
import { toast } from "sonner";

import { ErrorState, LoadingState, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cancelOrder, listOrders, listTerminals, placeOrder } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";

const STATUS_TONE: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  filled: "default",
  submitted: "secondary",
  pending: "outline",
  partial: "secondary",
  cancelled: "outline",
  rejected: "destructive",
};

function PlaceOrderDialog({ onPlaced }: { onPlaced: () => void }) {
  const [open, setOpen] = useState(false);
  const terminals = useAsync(() => listTerminals(), []);
  const [form, setForm] = useState({
    terminal_id: "",
    symbol: "EURUSD",
    side: "buy" as "buy" | "sell",
    order_type: "market" as "market" | "limit" | "stop" | "stop_limit",
    volume: "0.1",
    price: "",
    stop_loss: "",
    take_profit: "",
  });
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!form.terminal_id) {
      toast.error("Select a terminal");
      return;
    }
    setBusy(true);
    try {
      const res = await placeOrder({
        terminal_id: form.terminal_id,
        symbol: form.symbol,
        side: form.side,
        order_type: form.order_type,
        volume: Number(form.volume),
        price: form.price ? Number(form.price) : null,
        stop_loss: form.stop_loss ? Number(form.stop_loss) : null,
        take_profit: form.take_profit ? Number(form.take_profit) : null,
      });
      toast.success(`Order ${res.status}`, { description: `client_order_id: ${res.client_order_id}` });
      setOpen(false);
      onPlaced();
    } catch (e) {
      toast.error("Place order failed", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  const onlineTerminals = (terminals.data ?? []).filter((t) => t.is_online);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus className="size-4" /> New Order
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Place Order</DialogTitle>
          <DialogDescription>Submit a new order to the selected terminal.</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-3 py-2">
          <div className="col-span-2 space-y-1">
            <Label>Terminal</Label>
            <select
              className="h-9 w-full rounded-md border bg-background px-2 text-sm"
              value={form.terminal_id}
              onChange={(e) => setForm({ ...form, terminal_id: e.target.value })}
            >
              <option value="">Select terminal…</option>
              {onlineTerminals.map((t) => (
                <option key={t.id} value={t.terminal_id}>
                  {t.terminal_id} ({t.broker_account})
                </option>
              ))}
            </select>
          </div>
          <Field label="Symbol" value={form.symbol} onChange={(v) => setForm({ ...form, symbol: v })} />
          <div className="space-y-1">
            <Label>Side</Label>
            <select
              className="h-9 w-full rounded-md border bg-background px-2 text-sm"
              value={form.side}
              onChange={(e) => setForm({ ...form, side: e.target.value as "buy" | "sell" })}
            >
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </select>
          </div>
          <div className="space-y-1">
            <Label>Type</Label>
            <select
              className="h-9 w-full rounded-md border bg-background px-2 text-sm"
              value={form.order_type}
              onChange={(e) => setForm({ ...form, order_type: e.target.value as typeof form.order_type })}
            >
              {["market", "limit", "stop", "stop_limit"].map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <Field label="Volume" value={form.volume} onChange={(v) => setForm({ ...form, volume: v })} />
          {form.order_type !== "market" && (
            <Field label="Price" value={form.price} onChange={(v) => setForm({ ...form, price: v })} />
          )}
          <Field label="Stop Loss" value={form.stop_loss} onChange={(v) => setForm({ ...form, stop_loss: v })} />
          <Field label="Take Profit" value={form.take_profit} onChange={(v) => setForm({ ...form, take_profit: v })} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={busy}>
            {busy ? "Submitting…" : "Place Order"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="space-y-1">
      <Label>{label}</Label>
      <Input value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

export default function OrdersPage() {
  const [filter, setFilter] = useState<string>("");
  const { data, error, loading, reload } = useAsync(() => listOrders(filter || undefined), [filter]);

  async function cancel(id: string, status: string) {
    if (["filled", "cancelled", "rejected"].includes(status)) return;
    try {
      await cancelOrder(id);
      toast.success("Order cancelled");
      reload();
    } catch (e) {
      toast.error("Cancel failed", { description: (e as Error).message });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Orders"
        description="Order blotter — place, track, and cancel orders."
        actions={<PlaceOrderDialog onPlaced={reload} />}
      />
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <ListOrdered className="size-4" /> Orders
          </CardTitle>
          <select
            className="h-9 rounded-md border bg-background px-2 text-sm"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="">All statuses</option>
            {["pending", "submitted", "partial", "filled", "cancelled", "rejected"].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
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
                  <TableHead>Type</TableHead>
                  <TableHead className="text-right">Volume</TableHead>
                  <TableHead className="text-right">Price</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((o) => (
                  <TableRow key={o.id}>
                    <TableCell className="font-medium">{o.symbol}</TableCell>
                    <TableCell>
                      <Badge variant={o.side === "buy" ? "default" : "secondary"}>{o.side}</Badge>
                    </TableCell>
                    <TableCell>{o.order_type}</TableCell>
                    <TableCell className="text-right tabular-nums">{o.volume}</TableCell>
                    <TableCell className="text-right tabular-nums">{o.price ?? "—"}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_TONE[o.status] ?? "outline"}>{o.status}</Badge>
                      {o.rejection_reason && <span className="ml-2 text-xs text-rose-500">{o.rejection_reason}</span>}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(o.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={["filled", "cancelled", "rejected"].includes(o.status)}
                        onClick={() => cancel(o.id, o.status)}
                      >
                        Cancel
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="py-8 text-center text-sm text-muted-foreground">No orders.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
