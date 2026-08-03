"use client";

import { Terminal as TerminalIcon } from "lucide-react";
import { toast } from "sonner";

import { ErrorState, LoadingState, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { flattenTerminal, listTerminals, syncAccount, syncPositions } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";

export default function TerminalsPage() {
  const { data, error, loading, reload } = useAsync(() => listTerminals(), []);

  async function act(fn: () => Promise<unknown>, ok: string) {
    try {
      await fn();
      toast.success(ok);
      reload();
    } catch (e) {
      toast.error("Action failed", { description: (e as Error).message });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Terminals"
        description="Connected MT5 / adapter terminals and their live state."
        actions={
          <Button variant="outline" size="sm" onClick={reload}>
            Refresh
          </Button>
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
            <p className="py-8 text-center text-sm text-muted-foreground">
              No terminals registered. Attach an MT5 terminal running BridgeEA.mq5.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
