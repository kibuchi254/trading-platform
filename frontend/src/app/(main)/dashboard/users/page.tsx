"use client";

import { useState } from "react";

import { UserPlus, Users as UsersIcon } from "lucide-react";
import { toast } from "sonner";

import { ErrorState, LoadingState, PageHeader } from "@/components/atlas/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { activateUser, createUser, deactivateUser, listUsers } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/api/hooks";

export default function UsersPage() {
  const { data, error, loading, reload } = useAsync(() => listUsers(), []);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ email: "", password: "", display_name: "", role: "trader" });
  const [busy, setBusy] = useState(false);

  async function create() {
    setBusy(true);
    try {
      await createUser(form);
      toast.success("User created");
      setOpen(false);
      setForm({ email: "", password: "", display_name: "", role: "trader" });
      reload();
    } catch (e) {
      toast.error("Create failed", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function toggle(id: string, active: boolean) {
    try {
      await (active ? deactivateUser : activateUser)(id);
      toast.success(active ? "Deactivated" : "Activated");
      reload();
    } catch (e) {
      toast.error("Failed", { description: (e as Error).message });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Users"
        description="Organization user management (admin)."
        actions={
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button size="sm">
                <UserPlus className="size-4" /> New User
              </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-md">
              <DialogHeader>
                <DialogTitle>Create User</DialogTitle>
              </DialogHeader>
              <div className="grid grid-cols-2 gap-3 py-2">
                <div className="col-span-2 space-y-1">
                  <Label>Email</Label>
                  <Input
                    type="email"
                    value={form.email}
                    onChange={(e) => setForm({ ...form, email: e.target.value })}
                  />
                </div>
                <div className="col-span-2 space-y-1">
                  <Label>Display Name</Label>
                  <Input
                    value={form.display_name}
                    onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <Label>Password</Label>
                  <Input
                    type="password"
                    value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <Label>Role</Label>
                  <select
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                    value={form.role}
                    onChange={(e) => setForm({ ...form, role: e.target.value })}
                  >
                    {["admin", "trader", "viewer", "bot"].map((r) => (
                      <option key={r}>{r}</option>
                    ))}
                  </select>
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
            <UsersIcon className="size-4" /> Users
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <LoadingState rows={4} />
          ) : error ? (
            <ErrorState message={error.message} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead>Last Login</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(data ?? []).map((u) => (
                  <TableRow key={u.id}>
                    <TableCell className="font-medium">{u.display_name}</TableCell>
                    <TableCell>{u.email}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{u.role}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={u.is_active ? "default" : "secondary"}>
                        {u.is_active ? "active" : "disabled"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="ghost" onClick={() => toggle(u.id, u.is_active)}>
                        {u.is_active ? "Deactivate" : "Activate"}
                      </Button>
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
