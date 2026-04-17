// Format large numbers with K, M, B suffixes
export function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined) return "-";
  const num = Number(n);
  if (Number.isNaN(num)) return String(n);
  
  const abs = Math.abs(num);
  if (abs >= 1_000_000_000) return (num / 1_000_000_000).toFixed(2) + "B";
  if (abs >= 1_000_000) return (num / 1_000_000).toFixed(2) + "M";
  if (abs >= 1_000) return (num / 1_000).toFixed(1) + "K";
  return num.toLocaleString();
}

// Format with sign prefix (+/-)
export function fmtSigned(n: number | null | undefined): string {
  if (n === null || n === undefined) return "-";
  const num = Number(n);
  if (Number.isNaN(num)) return String(n);
  
  const prefix = num >= 0 ? "+" : "";
  return prefix + fmt(num);
}

// Full number with thousands separators
export function fmtFull(n: number | null | undefined): string {
  if (n === null || n === undefined) return "-";
  const num = Number(n);
  if (Number.isNaN(num)) return String(n);
  return num.toLocaleString();
}

// Format as percentage
export function fmtPercent(n: number | null | undefined, decimals = 1): string {
  if (n === null || n === undefined) return "-";
  const num = Number(n);
  if (Number.isNaN(num)) return String(n);
  return num.toFixed(decimals) + "%";
}

// Get color class based on value (positive/negative)
export function getNumClass(n: number | null | undefined, inverse = false): string {
  if (n === null || n === undefined) return "num-neutral";
  const num = Number(n);
  if (Number.isNaN(num)) return "num-neutral";
  
  if (inverse) {
    return num > 0 ? "num-negative" : num < 0 ? "num-positive" : "num-neutral";
  }
  return num > 0 ? "num-positive" : num < 0 ? "num-negative" : "num-neutral";
}

// Format date relative to now
export function fmtRelativeTime(dateStr: string | null | undefined): string {
  if (!dateStr) return "-";
  
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);
  
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  if (hours < 24) return `${hours}h ago`;
  if (days < 7) return `${days}d ago`;
  
  return date.toLocaleDateString();
}

// Format date nicely
export function fmtDate(dateStr: string | null | undefined, includeTime = false): string {
  if (!dateStr) return "-";
  
  const date = new Date(dateStr);
  if (includeTime) {
    return date.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

// Get rank badge class
export function getRankClass(rank: number): string {
  if (rank === 1) return "rank-gold";
  if (rank === 2) return "rank-silver";
  if (rank === 3) return "rank-bronze";
  return "";
}
