"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart2, BookOpen, LineChart } from "lucide-react";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/suggestions", label: "Signals",   Icon: BookOpen   },
  { href: "/portfolio",   label: "Portfolio",  Icon: LineChart  },
  { href: "/analytics",   label: "Analytics",  Icon: BarChart2  },
] as const;

export function Nav() {
  const pathname = usePathname();

  return (
    <>
      {/* ── Desktop top bar ───────────────────────────────────────────────── */}
      <header className="hidden sm:flex items-center justify-between border-b border-slate-700 px-6 py-3 bg-slate-900">
        <span className="font-bold text-white tracking-tight">SwingTrader</span>
        <nav className="flex gap-1">
          {LINKS.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                pathname.startsWith(href)
                  ? "bg-slate-700 text-white"
                  : "text-slate-400 hover:text-white hover:bg-slate-800",
              )}
            >
              {label}
            </Link>
          ))}
        </nav>
      </header>

      {/* ── Mobile bottom tab bar ─────────────────────────────────────────── */}
      <nav className="sm:hidden fixed bottom-0 inset-x-0 z-50 flex border-t border-slate-700 bg-slate-900">
        {LINKS.map(({ href, label, Icon }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-medium transition-colors",
                active ? "text-blue-400" : "text-slate-500",
              )}
            >
              <Icon className="h-5 w-5" strokeWidth={active ? 2.2 : 1.8} />
              {label}
            </Link>
          );
        })}
      </nav>
    </>
  );
}
