"use client";

import { useState } from "react";

import { Bot, Send } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { assistantChat } from "@/lib/api/endpoints";

interface Msg {
  id: number;
  role: "user" | "assistant";
  text: string;
}

let msgSeq = 0;
const nextId = () => ++msgSeq;

export default function AssistantPage() {
  const [messages, setMessages] = useState<Msg[]>([
    {
      id: nextId(),
      role: "assistant",
      text: "I'm your ATLAS trading assistant. Ask me about positions, risk, or recent trades.",
    },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  async function send() {
    if (!input.trim()) return;
    const userMsg: Msg = { id: nextId(), role: "user", text: input };
    setMessages((m) => [...m, userMsg]);
    setInput("");
    setBusy(true);
    try {
      const res = await assistantChat(input, { history: messages.slice(-6) });
      setMessages((m) => [...m, { id: nextId(), role: "assistant", text: res.reply }]);
    } catch (e) {
      toast.error("Assistant error", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="mb-2 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">AI Assistant</h1>
          <p className="text-sm text-muted-foreground">Natural-language chat with the trading assistant.</p>
        </div>
      </div>
      <Card className="h-[70vh]">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bot className="size-4" /> Assistant
          </CardTitle>
        </CardHeader>
        <CardContent className="flex h-full flex-col">
          <ScrollArea className="flex-1 pr-4">
            <div className="space-y-3">
              {messages.map((m) => (
                <div
                  key={m.id}
                  className={`max-w-3/4 rounded-lg px-3 py-2 text-sm ${
                    m.role === "user" ? "ml-auto bg-primary text-primary-foreground" : "bg-muted"
                  }`}
                >
                  {m.text}
                </div>
              ))}
              {busy && <div className="bg-muted w-fit rounded-lg px-3 py-2 text-sm">…</div>}
            </div>
          </ScrollArea>
          <div className="mt-3 flex gap-2">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="Ask about positions, risk state, recent trades…"
            />
            <Button onClick={send} disabled={busy}>
              <Send className="size-4" />
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
