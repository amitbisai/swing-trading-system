import type { PaperTrade } from "@/lib/types";

interface Props {
  positions: PaperTrade[];
}

export function PortfolioTable({ positions }: Props) {
  if (positions.length === 0) {
    return <p className="text-muted-foreground text-sm">No open positions.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="bg-muted">
          <tr className="text-left text-muted-foreground">
            <th className="px-3 py-2">Symbol</th>
            <th className="px-3 py-2">Entry Date</th>
            <th className="px-3 py-2 font-mono">Entry $</th>
            <th className="px-3 py-2">Shares</th>
            <th className="px-3 py-2 font-mono text-red-600">Stop $</th>
            <th className="px-3 py-2 font-mono text-green-600">Target $</th>
            <th className="px-3 py-2 font-mono text-right">Unreal. PnL</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr key={p.id} className="border-t hover:bg-muted/50">
              <td className="px-3 py-2 font-semibold">{p.symbol}</td>
              <td className="px-3 py-2 text-muted-foreground">{p.entry_date}</td>
              <td className="px-3 py-2 font-mono">${p.entry_price}</td>
              <td className="px-3 py-2">{p.shares}</td>
              <td className="px-3 py-2 font-mono text-red-600">${p.stop_loss}</td>
              <td className="px-3 py-2 font-mono text-green-600">${p.target_price}</td>
              <td className="px-3 py-2 font-mono text-right">—</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
