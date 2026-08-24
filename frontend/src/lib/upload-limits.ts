/** Keep in sync with backend MAX_UPLOAD_SIZE_MB / MAX_PAGES_PER_FILE. */
export const MAX_UPLOAD_SIZE_MB = Number(
  process.env.NEXT_PUBLIC_MAX_UPLOAD_SIZE_MB ?? 10,
);

export const MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024;

export const MAX_FILES_PER_UPLOAD = 10;

/** Keep in sync with backend MAX_PAGES_PER_FILE (default 10). */
export const MAX_PAGES_PER_FILE = Number(
  process.env.NEXT_PUBLIC_MAX_PAGES_PER_FILE ?? 10,
);

export function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Best-effort PDF page count from raw bytes (no pdf.js).
 * Returns null when Count cannot be inferred — server still enforces.
 */
export async function countPdfPages(file: File): Promise<number | null> {
  const name = file.name.toLowerCase();
  if (!name.endsWith(".pdf")) {
    return 1;
  }

  const buf = await file.arrayBuffer();
  const text = new TextDecoder("latin1").decode(buf);
  const pagesObj = text.match(/\/Type\s*\/Pages\b[^]*?\/Count\s+(\d+)/);
  if (pagesObj) {
    const n = Number(pagesObj[1]);
    return Number.isFinite(n) && n > 0 ? n : null;
  }

  const counts: number[] = [];
  const countRe = /\/Count\s+(\d+)/g;
  let match: RegExpExecArray | null;
  while ((match = countRe.exec(text)) !== null) {
    counts.push(Number(match[1]));
  }
  const positive = counts.filter((n) => Number.isFinite(n) && n > 0);
  if (!positive.length) return null;
  return Math.max(...positive);
}
