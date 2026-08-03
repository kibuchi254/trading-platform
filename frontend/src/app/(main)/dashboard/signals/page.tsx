"use client";

import { CandlestickChart } from "lucide-react";

import { ErrorState, LoadingState, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { listSignals } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";

export default function SignalsPage() {
  const { data, error, loading } = useAsync(() => listSignals({ limit: 200 }), []);

  return (
    <div className="space-y-6">
      <PageHeader title="Signals" description="Recent strategy / AI trading signals." />
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CandlestickChart className="size-4" /> Signal Feed
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <LoadingState rows={8} />
          ) : error ? (
            <ErrorState message={error.message} />
          ) : data && data.length > 0 ? (
            <ScrollArea className="h-[70vh] pr-4">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Side</TableHead>
                    <TableHead>Strength</TableHead>
                    <TableHead>TF</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead>Created</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.map((s) => (
                    <TableRow key={s.id}>
                      <TableCell className="font-medium">{s.symbol}</TableCell>
                      <TableCell>
                        <Badge variant={s.side === "buy" ? "default" : "secondary"}>{s.side}</Badge>
                      </TableCell>
                      <TableCell className="tabular-nums">{(s.strength * 100).toFixed(0)}%</TableCell>
                      <TableCell>{s.timeframe}</TableCell>
                      <TableCell className="text-right tabular-nums">{s.price}</TableCell>
                      <TableCell>
                        <Badge variant="outline">{s.source}</Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {new Date(s.created_at).toLocaleString()}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </ScrollArea>
          ) : (
            <p className="py-8 text-center text-sm text-muted-foreground">No signals emitted.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
