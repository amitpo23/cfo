/**
 * כפתורי "יצוא לאקסל" ו-"יצוא ל-PDF" משותפים לכל מסכי הנתונים.
 * לא מבצע קריאות API — מייצא רק את הנתונים שכבר טעונים ב-state של המסך הקורא.
 *
 * Excel: SheetJS (xlsx) נטען ב-dynamic import כדי לא לנפח את ה-bundle הראשי.
 * PDF: אין ספרייה — נפתח חלון עם HTML מודפס-יפה ומופעל window.print(), כך
 * שהמשתמש שומר כ-PDF דרך הדפדפן (תומך עברית/RTL מלא, בלי תלות חיצונית).
 */
import { useState } from 'react';
import { FileSpreadsheet, FileText, Loader2 } from 'lucide-react';

export interface ExportColumn {
  key: string;
  label: string;
}

export interface ExportSummaryItem {
  label: string;
  value: string;
}

export interface ExportSheet {
  /** שם הגיליון/הטבלה (בעברית) */
  name: string;
  columns: ExportColumn[];
  rows: Record<string, unknown>[];
  summary?: ExportSummaryItem[];
}

export interface ExportButtonsProps {
  /** שם הדוח בעברית — משמש גם כשם הקובץ וגם ככותרת ב-PDF */
  title: string;
  /** עמודות לטבלה הראשית (מתעלם אם sheets מסופק) */
  columns?: ExportColumn[];
  /** שורות לטבלה הראשית (מתעלם אם sheets מסופק) */
  rows?: Record<string, unknown>[];
  /** שורת סיכום לטבלה הראשית (מתעלם אם sheets מסופק) */
  summary?: ExportSummaryItem[];
  /** טווח תאריכים / ארגון / הקשר נוסף שיוצג מתחת לכותרת */
  meta?: string;
  /** מסכים עם כמה טבלאות: גיליון נפרד לכל טבלה באקסל, וטבלאות ברצף ב-PDF */
  sheets?: ExportSheet[];
  className?: string;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number') return value.toLocaleString('he-IL', { maximumFractionDigits: 2 });
  return String(value);
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function resolveSheets(props: ExportButtonsProps): ExportSheet[] {
  if (props.sheets && props.sheets.length > 0) return props.sheets;
  return [{ name: props.title, columns: props.columns || [], rows: props.rows || [], summary: props.summary }];
}

async function exportToExcel(props: ExportButtonsProps) {
  const XLSX = await import('xlsx');
  const sheets = resolveSheets(props);
  const wb = XLSX.utils.book_new();
  // RTL workbook view
  (wb as any).Workbook = { Views: [{ RTL: true }] };

  sheets.forEach((sheet) => {
    const header = sheet.columns.map((c) => c.label);
    const dataRows = sheet.rows.map((row) => sheet.columns.map((c) => {
      const v = row[c.key];
      return typeof v === 'number' ? v : (v === null || v === undefined ? '' : String(v));
    }));
    const aoa: unknown[][] = [header, ...dataRows];
    if (sheet.summary && sheet.summary.length > 0) {
      aoa.push([]);
      sheet.summary.forEach((s) => aoa.push([s.label, s.value]));
    }
    const ws = XLSX.utils.aoa_to_sheet(aoa);
    ws['!cols'] = sheet.columns.map((c) => ({
      wch: Math.max(c.label.length + 2, 12),
    }));
    const sheetName = sheet.name.slice(0, 31) || 'Sheet1';
    XLSX.utils.book_append_sheet(wb, ws, sheetName);
  });

  XLSX.writeFile(wb, `${props.title}-${todayIso()}.xlsx`);
}

function buildTableHtml(sheet: ExportSheet): string {
  const headRow = sheet.columns.map((c) => `<th>${escapeHtml(c.label)}</th>`).join('');
  const bodyRows = sheet.rows.map((row) => {
    const cells = sheet.columns.map((c) => `<td>${escapeHtml(formatCell(row[c.key]))}</td>`).join('');
    return `<tr>${cells}</tr>`;
  }).join('');
  const summaryHtml = sheet.summary && sheet.summary.length > 0
    ? `<div class="summary">${sheet.summary.map((s) => `<span><strong>${escapeHtml(s.label)}:</strong> ${escapeHtml(s.value)}</span>`).join('')}</div>`
    : '';
  return `
    <h2>${escapeHtml(sheet.name)}</h2>
    <table>
      <thead><tr>${headRow}</tr></thead>
      <tbody>${bodyRows || `<tr><td colspan="${sheet.columns.length}" class="empty">אין נתונים</td></tr>`}</tbody>
    </table>
    ${summaryHtml}
  `;
}

function exportToPdf(props: ExportButtonsProps) {
  const sheets = resolveSheets(props);
  const maxCols = Math.max(1, ...sheets.map((s) => s.columns.length));
  const landscape = maxCols > 6;

  const html = `<!doctype html>
<html dir="rtl" lang="he">
<head>
<meta charset="utf-8" />
<title>${escapeHtml(props.title)}</title>
<style>
  @page { size: A4 ${landscape ? 'landscape' : 'portrait'}; margin: 14mm; }
  * { box-sizing: border-box; }
  body { font-family: Arial, Helvetica, sans-serif; direction: rtl; color: #1e293b; padding: 0; margin: 0; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .meta { font-size: 11px; color: #64748b; margin-bottom: 2px; }
  .generated { font-size: 10px; color: #94a3b8; margin-bottom: 16px; }
  h2 { font-size: 14px; margin: 18px 0 8px; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 8px; font-size: 11px; }
  th, td { border: 1px solid #cbd5e1; padding: 5px 7px; text-align: right; }
  th { background: #f1f5f9; font-weight: 600; }
  tr:nth-child(even) td { background: #f8fafc; }
  td.empty { text-align: center; color: #94a3b8; }
  .summary { display: flex; flex-wrap: wrap; gap: 4px 18px; font-size: 12px; font-weight: 700; margin-bottom: 12px; padding: 6px 0; border-top: 1px solid #cbd5e1; }
  @media print { body { -webkit-print-color-adjust: exact; print-color-adjust: exact; } }
</style>
</head>
<body>
  <h1>${escapeHtml(props.title)}</h1>
  ${props.meta ? `<div class="meta">${escapeHtml(props.meta)}</div>` : ''}
  <div class="generated">הופק בתאריך ${escapeHtml(new Date().toLocaleDateString('he-IL'))}</div>
  ${sheets.map(buildTableHtml).join('\n')}
</body>
</html>`;

  // Blob URL במקום document.write — נמנע מסיכוני XSS ומאפשר לדפדפן לטעון
  // את הדף כמסמך רגיל (עם CSP/סנדבוקס תקינים) לפני הדפסה.
  const blob = new Blob([html], { type: 'text/html' });
  const url = URL.createObjectURL(blob);
  const win = window.open(url, '_blank');
  if (!win) {
    URL.revokeObjectURL(url);
    return;
  }

  const cleanup = () => URL.revokeObjectURL(url);
  win.addEventListener('load', () => {
    win.focus();
    win.print();
  });
  win.addEventListener('afterprint', () => {
    cleanup();
    win.close();
  });
  // רשת ביטחון: אם ההדפסה/סגירה לא הופעלו (חסימת פופ-אפ להדפסה וכד'), שחרר את ה-URL בכל מקרה.
  setTimeout(cleanup, 60000);
}

export default function ExportButtons(props: ExportButtonsProps) {
  const [exportingExcel, setExportingExcel] = useState(false);

  const handleExcel = async () => {
    setExportingExcel(true);
    try {
      await exportToExcel(props);
    } finally {
      setExportingExcel(false);
    }
  };

  return (
    <div className={`flex items-center gap-1.5 ${props.className || ''}`}>
      <button
        type="button"
        onClick={handleExcel}
        disabled={exportingExcel}
        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-slate-200 text-slate-600 text-xs hover:bg-slate-50 disabled:opacity-50 transition-colors"
        title="יצוא לאקסל"
      >
        {exportingExcel ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileSpreadsheet className="w-3.5 h-3.5" />}
        Excel
      </button>
      <button
        type="button"
        onClick={() => exportToPdf(props)}
        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-slate-200 text-slate-600 text-xs hover:bg-slate-50 transition-colors"
        title="יצוא ל-PDF"
      >
        <FileText className="w-3.5 h-3.5" />
        PDF
      </button>
    </div>
  );
}
