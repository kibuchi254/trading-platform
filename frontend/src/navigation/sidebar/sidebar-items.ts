import {
  Activity,
  Bot,
  CandlestickChart,
  Gauge,
  LayoutDashboard,
  LineChart,
  ListOrdered,
  type LucideIcon,
  Radio,
  Server,
  ShieldAlert,
  ShoppingBag,
  Terminal,
  Users,
} from "lucide-react";

export type NavBadge = "new" | "soon";

export interface NavSubItem {
  id: string;
  title: string;
  url: string;
  icon?: LucideIcon;
  badge?: NavBadge;
  disabled?: boolean;
  newTab?: boolean;
}

interface NavItemBase {
  id: string;
  title: string;
  icon?: LucideIcon;
  badge?: NavBadge;
  disabled?: boolean;
  newTab?: boolean;
}

export interface NavMainLinkItem extends NavItemBase {
  url: string;
  subItems?: never;
}

export interface NavMainParentItem extends NavItemBase {
  subItems: NavSubItem[];
}

export type NavMainItem = NavMainLinkItem | NavMainParentItem;

export interface NavGroup {
  id: number;
  label?: string;
  items: NavMainItem[];
}

export const sidebarItems: NavGroup[] = [
  {
    id: 1,
    label: "Dashboards",
    items: [
      { id: "overview", title: "Overview", url: "/dashboard/overview", icon: LayoutDashboard },
      { id: "realtime", title: "Real-time Trading", url: "/dashboard/realtime", icon: Radio },
    ],
  },
  {
    id: 2,
    label: "Trading — the books",
    items: [
      { id: "terminals", title: "Terminals", url: "/dashboard/terminals", icon: Terminal },
      { id: "orders", title: "Orders", url: "/dashboard/orders", icon: ListOrdered },
      { id: "positions", title: "Positions", url: "/dashboard/positions", icon: Activity },
      { id: "trades", title: "Trades", url: "/dashboard/trades", icon: ShoppingBag },
      { id: "signals", title: "Signals", url: "/dashboard/signals", icon: CandlestickChart },
      { id: "market-data", title: "Market Data", url: "/dashboard/market-data", icon: Gauge },
    ],
  },
  {
    id: 3,
    label: "Strategy",
    items: [
      { id: "strategies", title: "Strategies", url: "/dashboard/strategies", icon: Bot },
      { id: "backtests", title: "Backtests", url: "/dashboard/backtests", icon: LineChart },
    ],
  },
  {
    id: 4,
    label: "Risk & AI",
    items: [
      { id: "risk", title: "Risk Console", url: "/dashboard/risk", icon: ShieldAlert },
      { id: "ai", title: "AI Analysis", url: "/dashboard/ai", icon: Bot },
      { id: "assistant", title: "AI Assistant", url: "/dashboard/assistant", icon: Bot },
    ],
  },
  {
    id: 5,
    label: "Analytics & Admin",
    items: [
      { id: "performance", title: "Performance", url: "/dashboard/performance", icon: LineChart },
      { id: "system-status", title: "System Status", url: "/dashboard/system-status", icon: Server },
      { id: "users", title: "Users", url: "/dashboard/users", icon: Users },
      { id: "audit", title: "Audit Log", url: "/dashboard/audit", icon: ShieldAlert },
    ],
  },
];
