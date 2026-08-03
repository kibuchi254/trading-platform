"use client";

import { useState } from "react";

import { ScrollText } from "lucide-react";

import { ErrorState, LoadingState, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { listAuditLogs } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";

export default function AuditPage() {
  const [action, setAction] = useState("");
  const { data, error, loading } = useAsync(() => listAuditLogs(action ? { action } : { limit: 200 }), [action]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audit Log"
        description="Immutable audit trail of actions across the organization."
        actions={
          <Input
            placeholder="Filter by action…"
            value={action}
            onChange={(e) => setAction(e.target.value)}
            className="w-40"
          />
        }
      />
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ScrollText className="size-4" /> Audit Trail
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <LoadingState rows={8} />
          ) : error ? (
            <ErrorState message={error.message} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Actor</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Resource</TableHead>
                  <TableHead>IP</TableHead>
                  <TableHead>Timestamp</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(data ?? []).map((l) => (
                  <TableRow key={l.id}>
                    <TableCell className="text-xs">
                      <Badge variant="outline">{l.actor_type}</Badge> {l.actor_id ? l.actor_id.slice(0, 8) : "—"}
                    </TableCell>
                    <TableCell className="font-medium">{l.action}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {l.resource_type ? `${l.resource_type}:${l.resource_id}` : "—"}
                    </TableCell>
                    <TableCell className="text-xs">{l.ip ?? "—"}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{new Date(l.ts).toLocaleString()}</TableCell>
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
