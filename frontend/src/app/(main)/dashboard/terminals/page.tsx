"use client";

import { useState } from "react";
import { Download, Plus, Terminal as TerminalIcon } from "lucide-react";
import { toast } from "sonner";

import { ErrorState, LoadingState, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { flattenTerminal, listTerminals, syncAccount, syncPositions } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";

export default function TerminalsPage() {
  const { data, error, loading, reload } = useAsync(() => listTerminals(), []);
  const [dialogOpen, setDialogOpen] = useState(false);

  async function act(fn: () => Promise<unknown>, ok: string) {
    try {
      await fn();
      toast.success(ok);
      reload();
    } catch (e) {
      toast.error("Action failed", { description: (e as Error).message });
    }
  }

  const handleDownloadEA = () => {
    window.open("/api/downloads/bridge-ea", "_blank");
    toast.success("Downloading BridgeEA.mq5");
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Terminals"
        description="Connected MT5 / adapter terminals and their live state."
        actions={
          <div className="flex gap-2">
            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
              <DialogTrigger asChild>
                <Button size="sm" className="gap-2">
                  <Plus className="size-4" /> Connect Terminal
                </Button>
              </DialogTrigger>
              <DialogContent className="sm:max-w-md">
                <DialogHeader>
                  <DialogTitle>Connect Your MetaTrader 5 Terminal</DialogTitle>
                  <DialogDescription>
                    Follow these steps to connect MT5 running on your PC or Windows VPS to ATLAS.
                  </DialogDescription>
                </DialogHeader>
                <div className="space-y-4 text-sm">
                  <div className="rounded-lg border bg-muted/40 p-3 space-y-2">
                    <p className="font-semibold text-foreground">Step 1: Download BridgeEA</p>
                    <Button size="sm" variant="secondary" onClick={handleDownloadEA} className="w-full gap-2">
                      <Download className="size-4" /> Download BridgeEA.mq5
                    </Button>
                  </div>
                  <div className="rounded-lg border bg-muted/40 p-3 space-y-2">
                    <p className="font-semibold text-foreground">Step 2: Copy Files in MT5</p>
                    <p className="text-xs text-muted-foreground">
                      Place <code className="bg-muted px-1 py-0.5 rounded">BridgeEA.mq5</code> inside your MT5{" "}
                      <code className="bg-muted px-1 py-0.5 rounded">MQL5/Experts/</code> folder and compile it (or
                      press F7 in MetaEditor).
                    </p>
                  </div>
                  <div className="rounded-lg border bg-muted/40 p-3 space-y-2">
                    <p className="font-semibold text-foreground">Step 3: Attach EA & Set Inputs</p>
                    <div className="text-xs space-y-1 font-mono bg-background p-2 rounded border">
                      <p>
                        <span className="text-muted-foreground">InpBridgeUrl:</span> wss://your-domain/bridge/
                      </p>
                      <p>
                        <span className="text-muted-foreground">InpTerminalId:</span> mt5-tenant-01
                      </p>
                      <p>
                        <span className="text-muted-foreground">InpAuthToken:</span> (your bridge auth token)
                      </p>
                    </div>
                  </div>
                  <div className="rounded-lg border bg-muted/40 p-3 space-y-1">
                    <p className="font-semibold text-foreground">Step 4: Enable Algo Trading</p>
                    <p className="text-xs text-muted-foreground">
                      Click the green <strong>Algo Trading</strong> button in MT5 toolbar. Your terminal will connect
                      automatically!
                    </p>
                  </div>
                </div>
              </DialogContent>
            </Dialog>
            <Button variant="outline" size="sm" onClick={reload}>
              Refresh
            </Button>
          </div>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TerminalIcon className="size-4" /> Terminals
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <LoadingState rows={5} />
          ) : error ? (
            <ErrorState message={error.message} />
          ) : data && data.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Terminal ID</TableHead>
                  <TableHead>Account</TableHead>
                  <TableHead>Adapter</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Symbols</TableHead>
                  <TableHead>Last Heartbeat</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-medium">{t.terminal_id}</TableCell>
                    <TableCell>{t.broker_account}</TableCell>
                    <TableCell>{t.adapter_kind}</TableCell>
                    <TableCell>
                      <Badge variant={t.is_online ? "default" : t.status === "degraded" ? "secondary" : "outline"}>
                        {t.is_online ? "online" : t.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-32 truncate text-xs text-muted-foreground">
                      {t.symbols.length} symbols
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {t.last_heartbeat_at ? new Date(t.last_heartbeat_at).toLocaleTimeString() : "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => act(() => syncPositions(t.terminal_id), "Positions synced")}
                        >
                          Sync Pos
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => act(() => syncAccount(t.terminal_id), "Account synced")}
                        >
                          Sync Acct
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => act(() => flattenTerminal(t.terminal_id), "Terminal flattened")}
                        >
                          Flatten
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="py-12 text-center space-y-4">
              <p className="text-sm text-muted-foreground">
                No terminals registered yet. Connect your MetaTrader 5 terminal running BridgeEA.mq5.
              </p>
              <Button size="sm" onClick={() => setDialogOpen(true)} className="gap-2">
                <Plus className="size-4" /> Connect MT5 Terminal
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
