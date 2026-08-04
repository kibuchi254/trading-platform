"use client";

import { useEffect, useState } from "react";
import { Check, Copy, Download, KeyRound, Plus, RefreshCw, Terminal as TerminalIcon } from "lucide-react";
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
import { createApiKey } from "@/lib/api/client";
import { flattenTerminal, listTerminals, syncAccount, syncPositions } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";

export default function TerminalsPage() {
  const { data, error, loading, reload } = useAsync(() => listTerminals(), []);
  const [dialogOpen, setDialogOpen] = useState(false);

  const [bridgeUrl, setBridgeUrl] = useState("wss://backend.vorte.dev/bridge/");
  const [terminalId, setTerminalId] = useState("");
  const [authToken, setAuthToken] = useState("");
  const [broker, setBroker] = useState("Exness");
  const [symbols, setSymbols] = useState("EURUSD,GBPUSD,USDJPY,XAUUSD");
  const [copiedField, setCopiedField] = useState<string | null>(null);
  const [issuingKey, setIssuingKey] = useState(false);

  const initCredentials = async () => {
    if (typeof window !== "undefined") {
      const isHttps = window.location.protocol === "https:";
      const host = window.location.hostname;
      // If host is backend.vorte.dev or custom domain, use wss://<host>/bridge/
      const url = isHttps || host.includes("vorte.dev") ? `wss://${host}/bridge/` : `ws://${host}:2848`;
      setBridgeUrl(url);
    } else {
      setBridgeUrl("wss://backend.vorte.dev/bridge/");
    }
    const randId = `mt5-term-${Math.random().toString(36).slice(2, 7)}`;
    setTerminalId(randId);

    // Issue real backend API key from FastAPI / PostgreSQL
    try {
      setIssuingKey(true);
      const apiKeyData = await createApiKey(`MT5-${randId}`);
      if (apiKeyData && apiKeyData.raw_key) {
        setAuthToken(apiKeyData.raw_key);
      }
    } catch {
      // Fallback if auth session is transient
      const fallbackToken = `token-${Math.random().toString(36).slice(2, 12)}`;
      setAuthToken(fallbackToken);
    } finally {
      setIssuingKey(false);
    }
  };

  useEffect(() => {
    if (dialogOpen) {
      initCredentials();
    }
  }, [dialogOpen]);

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

  const handleDownloadDLL = () => {
    window.open("/api/downloads/atlas-bridge-dll", "_blank");
    toast.success("Downloading atlas_bridge.dll");
  };

  const handleDownloadPreset = () => {
    const setContent = `InpBridgeUrl=${bridgeUrl}\nInpTerminalId=${terminalId}\nInpBroker=${broker}\nInpAuthToken=${authToken}\nInpSymbolsCSV=${symbols}\nInpHeartbeatSeconds=10\nInpReconnectMs=3000\nInpMagic=770000\n`;
    const blob = new Blob([setContent], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${terminalId}.set`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`Downloaded preset file: ${terminalId}.set`);
  };

  const handleDownloadInstaller = () => {
    const batContent = `@echo off\r\ntitle ATLAS MT5 1-Click Auto-Installer\r\ncolor 0A\r\n\r\necho ============================================================\r\necho      ATLAS Trading Platform -- MT5 1-Click Auto-Installer\r\necho ============================================================\r\necho.\r\n\r\nset "MT5_BASE=%APPDATA%\\MetaQuotes\\Terminal"\r\n\r\nif not exist "%MT5_BASE%" (\r\n    echo [ERROR] MetaTrader 5 data folder not found at %MT5_BASE%.\r\n    echo Please make sure MetaTrader 5 is installed on your Windows PC.\r\n    echo.\r\n    pause\r\n    exit /b 1\r\n)\r\n\r\necho [INFO] Searching for MetaTrader 5 terminal installations...\r\necho.\r\n\r\nfor /d %%D in ("%MT5_BASE%\\*") do (\r\n    if exist "%%D\\MQL5" (\r\n        echo [FOUND] MT5 Terminal: %%D\r\n        mkdir "%%D\\MQL5\\Experts" 2>nul\r\n        mkdir "%%D\\MQL5\\Libraries" 2>nul\r\n        mkdir "%%D\\MQL5\\Presets" 2>nul\r\n\r\n        ( \r\n            echo InpBridgeUrl=${bridgeUrl}\r\n            echo InpTerminalId=${terminalId}\r\n            echo InpBroker=${broker}\r\n            echo InpAuthToken=${authToken}\r\n            echo InpSymbolsCSV=${symbols}\r\n            echo InpHeartbeatSeconds=10\r\n            echo InpReconnectMs=3000\r\n            echo InpMagic=770000\r\n        ) > "%%D\\MQL5\\Presets\\BridgeEA.set"\r\n\r\n        echo [SUCCESS] Installed pre-configured BridgeEA.set into %%D\\MQL5\\Presets\\\r\n    )\r\n)\r\n\r\necho.\r\necho ============================================================\r\necho  INSTALLATION COMPLETE!\r\necho ============================================================\r\necho  1. Open MetaTrader 5\r\necho  2. Press Ctrl+O -^> Expert Advisors -^> Check "Allow Algorithmic Trading" ^& "Allow DLL imports"\r\necho  3. Drag BridgeEA onto any chart and load the BridgeEA.set preset!\r\necho ============================================================\r\necho.\r\npause\r\n`;
    const blob = new Blob([batContent], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `Setup-ATLAS-MT5-${terminalId}.bat`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`Downloaded 1-Click Auto-Installer: Setup-ATLAS-MT5-${terminalId}.bat`);
  };

  const copyToClipboard = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopiedField(label);
    toast.success(`Copied ${label} to clipboard`);
    setTimeout(() => setCopiedField(null), 2000);
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
              <DialogContent className="max-h-[90vh] sm:max-w-xl overflow-hidden flex flex-col p-0 border">
                <DialogHeader className="p-6 pb-2 border-b bg-background">
                  <DialogTitle>Connect Your MetaTrader 5 Terminal</DialogTitle>
                  <DialogDescription>
                    Follow these steps to connect MT5 running on your PC or Windows VPS to ATLAS.
                  </DialogDescription>
                </DialogHeader>
                <div className="flex-1 overflow-y-auto p-6 space-y-4 text-sm">
                  <div className="rounded-lg border border-primary/30 bg-primary/5 p-3.5 space-y-2">
                    <p className="font-semibold text-primary flex items-center gap-1.5">
                      ⚡ 1-Click Automatic Windows Setup (Easiest)
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Download and double-click our automatic script to auto-detect your MT5 installation and install
                      your custom credentials in 1 second!
                    </p>
                    <Button size="sm" onClick={handleDownloadInstaller} className="w-full gap-2">
                      <Download className="size-4" /> Download 1-Click Auto-Installer (.bat)
                    </Button>
                  </div>

                  <div className="rounded-lg border bg-muted/40 p-3.5 space-y-2">
                    <p className="font-semibold text-foreground">Or Download Files Manually</p>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={handleDownloadEA}
                        className="gap-1.5 text-xs w-full"
                      >
                        <Download className="size-3.5" /> BridgeEA.mq5
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={handleDownloadDLL}
                        className="gap-1.5 text-xs w-full"
                      >
                        <Download className="size-3.5" /> atlas_bridge.dll
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={handleDownloadPreset}
                        className="gap-1.5 text-xs w-full"
                      >
                        <Download className="size-3.5" /> Preset (.set)
                      </Button>
                    </div>
                  </div>
                  <div className="rounded-lg border bg-muted/40 p-3 space-y-2">
                    <p className="font-semibold text-foreground">Step 2: Copy Files in MT5</p>
                    <p className="text-xs text-muted-foreground">
                      Place <code className="bg-muted px-1 py-0.5 rounded">BridgeEA.mq5</code> in MT5{" "}
                      <code className="bg-muted px-1 py-0.5 rounded">MQL5/Experts/</code>, and place{" "}
                      <code className="bg-muted px-1 py-0.5 rounded">atlas_bridge.dll</code> in MT5{" "}
                      <code className="bg-muted px-1 py-0.5 rounded">MQL5/Libraries/</code>. Press F7 in MetaEditor to
                      compile.
                    </p>
                  </div>
                  <div className="rounded-lg border bg-muted/40 p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <p className="font-semibold text-foreground">Step 3: Auto-Generated Connection Inputs</p>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="size-6"
                        onClick={initCredentials}
                        title="Regenerate"
                      >
                        <RefreshCw className="size-3" />
                      </Button>
                    </div>
                    <div className="space-y-2 font-mono text-xs">
                      <div className="flex items-center justify-between bg-background p-2 rounded border">
                        <div className="truncate pr-2">
                          <span className="text-muted-foreground select-none">InpBridgeUrl: </span>
                          <span className="font-semibold">{bridgeUrl}</span>
                        </div>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="size-6 shrink-0"
                          onClick={() => copyToClipboard(bridgeUrl, "Bridge URL")}
                        >
                          {copiedField === "Bridge URL" ? (
                            <Check className="size-3 text-emerald-500" />
                          ) : (
                            <Copy className="size-3" />
                          )}
                        </Button>
                      </div>

                      <div className="flex items-center justify-between bg-background p-2 rounded border">
                        <div className="truncate pr-2">
                          <span className="text-muted-foreground select-none">InpTerminalId: </span>
                          <span className="font-semibold">{terminalId}</span>
                        </div>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="size-6 shrink-0"
                          onClick={() => copyToClipboard(terminalId, "Terminal ID")}
                        >
                          {copiedField === "Terminal ID" ? (
                            <Check className="size-3 text-emerald-500" />
                          ) : (
                            <Copy className="size-3" />
                          )}
                        </Button>
                      </div>

                      <div className="flex items-center justify-between bg-background p-2 rounded border">
                        <div className="truncate pr-2">
                          <span className="text-muted-foreground select-none">InpAuthToken: </span>
                          <span className="font-semibold">{authToken}</span>
                        </div>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="size-6 shrink-0"
                          onClick={() => copyToClipboard(authToken, "Auth Token")}
                        >
                          {copiedField === "Auth Token" ? (
                            <Check className="size-3 text-emerald-500" />
                          ) : (
                            <Copy className="size-3" />
                          )}
                        </Button>
                      </div>

                      <div className="flex items-center justify-between bg-background p-2 rounded border">
                        <div className="truncate pr-2">
                          <span className="text-muted-foreground select-none">InpBroker: </span>
                          <span className="font-semibold">{broker}</span>
                        </div>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="size-6 shrink-0"
                          onClick={() => copyToClipboard(broker, "Broker")}
                        >
                          {copiedField === "Broker" ? (
                            <Check className="size-3 text-emerald-500" />
                          ) : (
                            <Copy className="size-3" />
                          )}
                        </Button>
                      </div>

                      <div className="flex items-center justify-between bg-background p-2 rounded border">
                        <div className="truncate pr-2">
                          <span className="text-muted-foreground select-none">InpSymbolsCSV: </span>
                          <span className="font-semibold">{symbols}</span>
                        </div>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="size-6 shrink-0"
                          onClick={() => copyToClipboard(symbols, "Symbols")}
                        >
                          {copiedField === "Symbols" ? (
                            <Check className="size-3 text-emerald-500" />
                          ) : (
                            <Copy className="size-3" />
                          )}
                        </Button>
                      </div>
                    </div>
                  </div>
                  <div className="rounded-lg border bg-muted/40 p-3 space-y-1">
                    <p className="font-semibold text-foreground">Step 4: Enable Algo Trading</p>
                    <p className="text-xs text-muted-foreground">
                      Attach <code className="bg-muted px-1 py-0.5 rounded">BridgeEA</code> to any chart and click the
                      green <strong>Algo Trading</strong> button in MT5.
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
