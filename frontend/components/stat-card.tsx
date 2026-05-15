import { cn } from "@/lib/utils";

interface Props {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean;   // green tint
  negative?: boolean;   // red tint
  mono?: boolean;
}

export function StatCard({ label, value, sub, positive, negative, mono }: Props) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
      <p className="text-xs text-slate-400 mb-1">{label}</p>
      <p
        className={cn(
          "text-lg font-semibold leading-tight",
          mono && "font-mono",
          positive && "text-emerald-400",
          negative && "text-red-400",
          !positive && !negative && "text-white",
        )}
      >
        {value}
      </p>
      {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
    </div>
  );
}
