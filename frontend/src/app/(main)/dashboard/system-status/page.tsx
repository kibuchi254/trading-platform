"use client";

import { Server } from "lucide-react";

import { ErrorState, LoadingState, MetricCard, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getSystemStatus, listNotifications } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";

export default function SystemStatusPage() {
  const status = useAsync(() => getSystemStatus(), []);
  const notifs = useAsync(() => listNotifications({ limit: 20 }), []);

  return (
    <div className="space-y-6">
      <PageHeader title="System Status" description="Operator view — terminals, command queue, risk, environment." />
      {status.loading ? (
        <LoadingState rows={2} />
      ) : status.error ? (
        <ErrorState message={status.error.message} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard
            title="Terminals Online"
            value={status.data?.terminals_online ?? 0}
            icon={<Server className="size-4" />}
          />
          <MetricCard title="Pending Commands" value={status.data?.pending_commands ?? 0} />
          <MetricCard
            title="Kill Switch"
            value={status.data?.risk_kill_switch ? "ENGAGED" : "ARMED"}
            tone={status.data?.risk_kill_switch ? "negative" : "positive"}
          />
          <MetricCard title="Environment" value={status.data?.env ?? "—"} />
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Recent Notifications</CardTitle>
        </CardHeader>
        <CardContent>
          {notifs.loading ? (
            <LoadingState rows={4} />
          ) : notifs.data && notifs.data.length > 0 ? (
            <ul className="space-y-2">
              {notifs.data.map((n) => (
                <li key={n.id} className="flex items-center justify-between border-b py-2 text-sm">
                  <div>
                    <Badge variant="outline" className="mr-2">
                      {n.channel}
                    </Badge>
                    {n.subject ?? n.body.slice(0, 80)}
                  </div>
                  <Badge
                    variant={n.status === "sent" ? "default" : n.status === "failed" ? "destructive" : "secondary"}
                  >
                    {n.status}
                  </Badge>
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-4 text-center text-sm text-muted-foreground">No notifications.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
