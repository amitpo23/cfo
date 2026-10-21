/*
 * ערכת הכלים לתיוק הוצאות בסאמית — books/fileexpenses
 *
 * שימוש: להזריק את כל הקובץ בקריאת javascript_tool אחת אחרי טעינת המסך.
 * צריך הזרקה מחדש אחרי כל ניווט/רענון של הדף.
 *
 * מסך התיוק:  https://app.sumit.co.il/books/fileexpenses/?databaseid=<DB_ID>
 * תצוגת רשימה: תפריט "..." ← "כל הקבצים לתיוק"  (שם נמצאת מחיקה לארכיון)
 */

// ---------- קריאת השדות ----------
// שמות ה-name בטופס. שדות החשבון והמטבע מוסתרים בתצוגה אך קיימים ב-DOM.
window.__F = {
  g: n => { const e = document.querySelector(`[name="${n}"]`); return e ? e.value : null; },
  read: () => ({
    Type:     window.__F.g('Type'),        Ref1:   window.__F.g('Reference1'),
    Ref2:     window.__F.g('Reference2'),  Alloc:  window.__F.g('AssignmentNumber'),
    Date:     window.__F.g('ReferenceDate'), Amount: window.__F.g('AmountILS'),
    VAT:      window.__F.g('VATAmountILS'), Details: window.__F.g('Details'),
    Debit:    window.__F.g('DebitAccount'), Credit: window.__F.g('CreditAccount'),
  }),
  // כפתורים רגילים: הטקסט ב-textContent
  btn: label => [...document.querySelectorAll('a,button,div,span')]
        .filter(e => e.children.length === 0 && e.textContent.trim() === label && e.offsetParent !== null)[0] || null,
  cell: n => { const h = document.querySelector(`[name="${n}"]`); if (!h) return null;
        const td = h.closest('td'); return td ? td.innerText.split('לא נמצאו')[0].replace(/\s+/g,' ').trim() : null; },
  count: () => (document.querySelector('h1,h2') || {}).innerText,
};

// ---------- כתיבה לשדה ----------
// חובה ה-setter הנייטיב + אירועי input/change; השמה ישירה ל-value לא נרשמת ב-Blazor.
window.__setField = async function (name, val) {
  const el = document.querySelector(`[name="${name}"]`);
  const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  el.focus(); s.call(el, val);
  el.dispatchEvent(new Event('input',  { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  el.blur();
  await new Promise(r => setTimeout(r, 1600));
  return document.querySelector(`[name="${name}"]`).value;
};

// ---------- בורר (סוג תנועה / חשבון) ----------
// פתיחה ← הקלדה בשדה החיפוש ← קליק ישיר על התוצאה ב-DOM.
// קליק בקואורדינטות על פריטי הבורר נוחת על השורה שמאחוריהם.
window.__pick = async function (hiddenName, label) {
  const h = document.querySelector(`[name="${hiddenName}"]`), td = h.closest('td');
  (td.querySelector('a') || td).click();
  await new Promise(r => setTimeout(r, 1100));
  const ins = [...document.querySelectorAll('.sumit-selectbox-search-terms-input,.teva-selectbox-search-terms-input')]
                .filter(e => e.offsetParent !== null);
  if (ins.length) {
    const inp = ins[ins.length - 1];
    const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    inp.focus(); s.call(inp, label); inp.dispatchEvent(new Event('input', { bubbles: true }));
  }
  let hit = null;
  for (let k = 0; k < 8; k++) {
    await new Promise(r => setTimeout(r, 700));
    const res = [...document.querySelectorAll('.sumit-selectbox-search-results-result,.teva-selectbox-search-results-result')]
                  .filter(e => e.offsetParent !== null);
    hit = res.find(e => e.textContent.trim() === label) || res.find(e => e.textContent.trim().startsWith(label));
    if (hit) break;
  }
  if (!hit) return 'NORESULT';
  hit.click();
  await new Promise(r => setTimeout(r, 1900));
  return window.__F.g(hiddenName) ? 'OK' : 'EMPTY';
};

// ---------- דיאלוגים ----------
// הכפתורים הם <input>; הטקסט ב-value ולא ב-textContent. חיפוש לפי textContent לא ימצא אותם.
window.__dlg = () => [...document.querySelectorAll('.modal-dialog')].filter(e => e.offsetParent).map(b => ({
  title:   (b.querySelector('.modal-content-title-text') || {}).innerText || '',
  body:   ((b.querySelector('.modal-body') || {}).innerText || '').replace(/\s+/g,' ').trim(),
  buttons: [...b.querySelectorAll('input,button')].map(i => (i.value || i.textContent || '').trim()).filter(Boolean),
}));
window.__dlgClick = label => {
  const b = [...document.querySelectorAll('.modal-dialog')].filter(e => e.offsetParent)[0];
  if (!b) return 'NODIALOG';
  const btn = [...b.querySelectorAll('input,button')].find(i => ((i.value || i.textContent || '').trim()) === label);
  if (!btn) return 'NOBTN';
  btn.click(); return 'CLICKED';
};

// ---------- מע"מ ----------
// 17% עד 31/12/2024 · 18% מ-01/01/2025.  frac: 1 רגיל · 2/3 אחזקת רכב (תקנה 18) · 0 ללא ניכוי.
window.__vatFor = function (amountStr, dateStr, frac) {
  frac = (frac === undefined) ? 1 : frac;
  const a = parseFloat(String(amountStr).replace(/,/g, ''));
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(String(dateStr).trim());
  if (!m) return null;
  const rate = (+m[3] >= 2025) ? 0.18 : 0.17;
  return { rate, frac, vat: Math.round(a * rate / (1 + rate) * frac * 100) / 100 };
};

// ---------- כפילות שסאמית סימנה ----------
window.__dupInfo = () => {
  const t = [...document.querySelectorAll('[title]')].map(e => e.getAttribute('title') || '')
              .find(x => /תנועה כפולה/.test(x));
  const bar = [...document.querySelectorAll('*')].filter(e => /איתרה תנועת יומן דומה/.test(e.innerText || '')).slice(-1)[0];
  if (!t && !bar) return null;
  return { tooltip: (t || '').replace(/<br\s*\/?>/g, ' ').replace(/\s+/g, ' ').trim(),
           banner: bar ? bar.innerText.replace(/\s+/g, ' ').trim() : null,
           row: window.__F.read() };
};
window.__delDup = async function () {
  const info = window.__dupInfo();
  if (!info) return { skipped: 'NO_DUP_BANNER' };
  const del = [...document.querySelectorAll('a.og-button-color-danger')].filter(e => e.offsetParent)[0];
  if (!del) return { error: 'NO_DELETE_BUTTON', info };
  del.click(); await new Promise(r => setTimeout(r, 2200));
  const dl = window.__dlg();
  if (!dl.length || !/מחיקת תנועה/.test(dl[0].title)) return { error: 'UNEXPECTED_DIALOG', dl, info };
  window.__dlgClick('אישור');
  await new Promise(r => setTimeout(r, 3800));
  return { deleted: info, after: window.__F.count() };
};

// ---------- שערים ----------
window.__pages = () => {
  const bar = [...document.querySelectorAll('*')].filter(e => /הצילום מכיל/.test(e.innerText || '')).slice(-1)[0];
  if (!bar) return null;
  const m = bar.innerText.match(/מכיל (\d+) דפים/);
  return m ? +m[1] : null;
};
window.__filed  = window.__filed  || {};   // אסמכתא → מספר תנועה, לאורך כל הריצה
window.__dupLog = window.__dupLog || [];
window.__queue  = window.__queue  || [];   // תור הכרעה
window.__guard = () => {
  const c = window.__F.read();
  const p = window.__pages();
  if (p)                          return { block: 'MULTIPAGE',     pages: p, ref: c.Ref1, amt: c.Amount };
  if (c.Ref1 && window.__filed[c.Ref1]) return { block: 'ALREADY_FILED', ref: c.Ref1, as: window.__filed[c.Ref1], amt: c.Amount };
  if (!c.Amount)                  return { block: 'NO_AMOUNT',     ref: c.Ref1 };
  return null;
};

// ---------- שמירה ----------
window.__saveDoc = async function () {
  window.__F.btn('שמירה').click();
  await new Promise(r => setTimeout(r, 3200));
  const seen = [], acted = [];
  for (let i = 0; i < 4; i++) {
    const dl = window.__dlg();
    if (!dl.length) break;
    seen.push(dl[0]);
    if (/עריכה ידנית של המע/.test(dl[0].title)) acted.push(window.__dlgClick('אישור מע"מ ידני'));
    else break;                                  // כל דיאלוג אחר — לעצור ולדווח
    await new Promise(r => setTimeout(r, 3000));
  }
  const toast = [...document.querySelectorAll('div')].map(e => (e.innerText || '').trim())
      .filter(t => t.length < 90 && /נשמרה למנה|כפול|קיימת ביומן|שגיאה/.test(t)).slice(-1)[0] || null;
  return { after: window.__F.count(), dialogs: seen, acted, toast };
};
window.__skip = async function () {
  window.__F.btn('דילוג').click();
  await new Promise(r => setTimeout(r, 2800));
  return window.__F.read();
};

// ---------- הצעד המלא ----------
// זו הפונקציה היחידה שקוראים לה בלולאה.
window.__goSafe = async function (dateStr, typeLabel, frac) {
  const g = window.__guard();
  if (g) return { blocked: g };

  const before = window.__F.read();
  if (dateStr && dateStr !== before.Date) await window.__setField('ReferenceDate', dateStr);

  const p = await window.__pick('Type', typeLabel);
  if (p !== 'OK') return { error: 'TYPE_NOT_SET:' + p };
  await new Promise(r => setTimeout(r, 800));

  const cur  = window.__F.read();
  const calc = window.__vatFor(cur.Amount, cur.Date, frac);
  const auto = cur.VAT;                                   // מה שסאמית הציעה — לתיעוד
  if (calc && Math.abs(parseFloat(String(cur.VAT || '0').replace(/,/g,'')) - calc.vat) > 0.011)
    await window.__setField('VATAmountILS', calc.vat.toFixed(2));

  const fin = window.__F.read();
  const s   = await window.__saveDoc();
  const m   = (s.toast || '').match(/מספר תנועה במנה: (\d+)/);
  if (m) window.__filed[fin.Ref1] = m[1];

  let dups = 0;                                           // כפילויות שסאמית סימנה אחרי השמירה
  for (let i = 0; i < 10; i++) {
    if (!window.__dupInfo()) break;
    const d = await window.__delDup();
    if (d.error) break;
    window.__dupLog.push({ ref: d.deleted.row.Ref1, amt: d.deleted.row.Amount, date: d.deleted.row.Date,
                           matched: (d.deleted.tooltip.match(/תנועה (\d+) במנה/) || [])[1] });
    dups++;
    await new Promise(r => setTimeout(r, 900));
  }
  return { tx: m ? m[1] : null, toast: s.toast, vat: fin.VAT, sumitProposed: auto,
           debit: window.__F.cell('DebitAccount'), dups, count: window.__F.count() };
};

'toolkit ready';
