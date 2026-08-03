"use client";

import { useState } from "react";

import { Bot } from "lucide-react";
import { toast } from "sonner";

import { ErrorState, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { analyze } from "@/lib/api/endpoints";
import type { AnalysisOut } from "@/lib/api/types";

export default function AiPage() {
  const [symbol, setSymbol] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState("M15");
  const [result, setResult] = useState<AnalysisOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setLoading(true);
    setError(null);
    try {
      const r = await analyze({ symbol, timeframe });
      setResult(r);
    } catch (e) {
      setError((e as Error).message);
      toast.error("Analysis failed", { description: (e as Error).message });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="AI Analysis" description="Fan-in of ATLAS AI analyst modules into a composite signal." />
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bot className="size-4" /> Analyze
          </CardTitle>
        </CardHeader>
        <CardContent className="flex items-end gap-3">
          <div className="space-y-1">
            <Label htmlFor="ai-symbol">Symbol</Label>
            <Input
              id="ai-symbol"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              className="w-32"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ai-timeframe">Timeframe</Label>
            <select
              id="ai-timeframe"
              className="h-9 rounded-md border bg-background px-2 text-sm"
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
            >
              {["M5", "M15", "H1", "H4", "D1"].map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </div>
          <Button onClick={run} disabled={loading}>
            {loading ? "Analyzing…" : "Analyze"}
          </Button>
        </CardContent>
      </Card>

      {error && <ErrorState message={error} />}

      {result && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card>
            <CardHeader>
              <CardTitle>Composite Score</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-4xl font-bold tabular-nums">{(result.composite_score * 100).toFixed(0)}</div>
              <p className="text-xs text-muted-foreground">Aggregated confidence across modules for {result.symbol}.</p>
            </CardContent>
          </Card>

          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Module Outputs</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {Object.entries(result.modules).map(([name, out]) => (
                  <div key={name} className="flex items-center justify-between border-b py-2">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">{name}</Badge>
                      <span className="text-sm">
                        {String(out.direction ?? "neutral")} · conf {(Number(out.confidence ?? 0) * 100).toFixed(0)}%
                      </span>
                    </div>
                    <span className="text-xs text-muted-foreground">{String(out.horizon ?? "")}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
