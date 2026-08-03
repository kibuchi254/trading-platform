"use client";

import { useState } from "react";

import { ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import { ErrorState, LoadingState, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { engageKillSwitch, getKillSwitch, listRiskEvents, releaseKillSwitch } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";

const SEVERITY_TONE: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  kill: "destructive",
  critical: "destructive",
  warning: "secondary",
  info: "outline",
};

export default function RiskPage() {
  const ks = useAsync(() => getKillSwitch(), []);
  const events = useAsync(() => listRiskEvents({ limit: 100 }), []);
  const [busy, setBusy] = useState(false);

  async function toggle() {
    setBusy(true);
    try {
      if (ks.data?.engaged) {
        await releaseKillSwitch();
        toast.success("Kill switch released");
      } else {
        await engageKillSwitch();
        toast.warning("Kill switch ENGAGED — new orders blocked");
      }
      ks.reload();
      events.reload();
    } catch (e) {
      toast.error("Action failed", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Risk Console" description="Kill switch and the risk-event audit feed." />
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldAlert className="size-4" /> Kill Switch
          </CardTitle>
        </CardHeader>
        <CardContent className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Badge variant={ks.data?.engaged ? "destructive" : "default"}>
              {ks.loading ? "…" : ks.data?.engaged ? "ENGAGED" : "ARMED"}
            </Badge>
            <p className="text-sm text-muted-foreground">
              {ks.data?.engaged
                ? "All new orders are blocked globally."
                : "Orders flow through the risk engine normally."}
            </p>
          </div>
          <Button variant={ks.data?.engaged ? "default" : "destructive"} onClick={toggle} disabled={busy}>
            {busy ? "…" : ks.data?.engaged ? "Release" : "Engage"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Risk Events</CardTitle>
        </CardHeader>
        <CardContent>
          {events.loading ? (
            <LoadingState rows={6} />
          ) : events.error ? (
            <ErrorState message={events.error.message} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Rule</TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Resolved</TableHead>
                  <TableHead>Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(events.data ?? []).map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="font-medium">{e.rule}</TableCell>
                    <TableCell>
                      <Badge variant={SEVERITY_TONE[e.severity] ?? "outline"}>{e.severity}</Badge>
                    </TableCell>
                    <TableCell>{e.action}</TableCell>
                    <TableCell>{e.resolved ? "yes" : "no"}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(e.created_at).toLocaleString()}
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
