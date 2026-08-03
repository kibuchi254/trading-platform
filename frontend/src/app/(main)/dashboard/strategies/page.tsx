"use client";

import { useState } from "react";

import { Bot, Plus } from "lucide-react";
import { toast } from "sonner";

import { ErrorState, LoadingState, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  activateStrategy,
  createStrategy,
  deactivateStrategy,
  listAvailableStrategies,
  listStrategies,
} from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";

export default function StrategiesPage() {
  const strategies = useAsync(() => listStrategies(), []);
  const available = useAsync(() => listAvailableStrategies(), []);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", slug: "", kind: "ema_cross", config: "{}", description: "" });
  const [busy, setBusy] = useState(false);

  async function create() {
    setBusy(true);
    try {
      await createStrategy({
        name: form.name,
        slug: form.slug,
        kind: form.kind,
        config: JSON.parse(form.config || "{}"),
        description: form.description || undefined,
      });
      toast.success("Strategy created");
      setOpen(false);
      strategies.reload();
    } catch (e) {
      toast.error("Create failed", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function toggle(id: string, active: boolean) {
    try {
      await (active ? deactivateStrategy : activateStrategy)(id);
      toast.success(active ? "Deactivated" : "Activated");
      strategies.reload();
    } catch (e) {
      toast.error("Toggle failed", { description: (e as Error).message });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Strategies"
        description="Registered trading strategies and their activation state."
        actions={
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button size="sm">
                <Plus className="size-4" /> New Strategy
              </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-lg">
              <DialogHeader>
                <DialogTitle>Create Strategy</DialogTitle>
              </DialogHeader>
              <div className="grid grid-cols-2 gap-3 py-2">
                <div className="col-span-2 space-y-1">
                  <Label>Name</Label>
                  <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                </div>
                <div className="space-y-1">
                  <Label>Slug</Label>
                  <Input value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} />
                </div>
                <div className="space-y-1">
                  <Label>Kind</Label>
                  <select
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                    value={form.kind}
                    onChange={(e) => setForm({ ...form, kind: e.target.value })}
                  >
                    {(available.data ?? []).map((s) => (
                      <option key={s.name} value={s.name}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="col-span-2 space-y-1">
                  <Label>Config (JSON)</Label>
                  <Input value={form.config} onChange={(e) => setForm({ ...form, config: e.target.value })} />
                </div>
                <div className="col-span-2 space-y-1">
                  <Label>Description</Label>
                  <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
                </div>
              </div>
              <DialogFooter>
                <Button onClick={create} disabled={busy}>
                  {busy ? "Creating…" : "Create"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bot className="size-4" /> Strategies
          </CardTitle>
        </CardHeader>
        <CardContent>
          {strategies.loading ? (
            <LoadingState rows={4} />
          ) : strategies.error ? (
            <ErrorState message={strategies.error.message} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Slug</TableHead>
                  <TableHead>Kind</TableHead>
                  <TableHead>Version</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(strategies.data ?? []).map((s) => (
                  <TableRow key={s.id}>
                    <TableCell className="font-medium">{s.name}</TableCell>
                    <TableCell>{s.slug}</TableCell>
                    <TableCell>{s.kind}</TableCell>
                    <TableCell>{s.version}</TableCell>
                    <TableCell>
                      <Badge variant={s.is_active ? "default" : "outline"}>{s.is_active ? "active" : "inactive"}</Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="ghost" onClick={() => toggle(s.id, s.is_active)}>
                        {s.is_active ? "Deactivate" : "Activate"}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Available Strategy SDK kinds</CardTitle>
        </CardHeader>
        <CardContent>
          {available.data ? (
            <div className="flex flex-wrap gap-2">
              {available.data.map((s) => (
                <Badge key={s.name} variant="outline">
                  {s.name} (v{s.version})
                </Badge>
              ))}
            </div>
          ) : (
            <LoadingState rows={1} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
