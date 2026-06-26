/*
 * אוטומציה יומית לתיוק טיוטות הוצאה ב-SUMIT — מריצים בקונסול של הדפדפן
 * בעמוד "תיוק קבצי הוצאות" (app.sumit.co.il/expenses/fileexpenses/?showallpendingexpenses=true),
 * כשאתה מחובר. מתייק אוטומטית טיוטות שה-OCR שלהן ברור, ועוצר בבטחה על כל חריגה.
 *
 * רקע: צילומי הקבלה נגישים רק בסשן המחובר של app.sumit (לא ב-API). הדף מציג
 * בועות OCR (.og-expenses-quick-ocr) לכל שדה. הסקריפט בוחר בועה לכל שדה לפי
 * היוריסטיקה, מאמת, ולוחץ "שמירה כמסמך סופי".
 *
 * בטיחות (תיוק לספרים בלתי-הפיך):
 *  - אימות ע"י מונה-טיוטות (ground truth): נחשב "תויק" רק אם המונה ירד בדיוק 1.
 *    אם ירד 0 או יותר מ-1 — עצירה מיידית (מונע כפילויות/דליפות).
 *  - מדלג/עוצר אם נפתח חלון "יצירת ספק", אם הסכום אינו עשרוני, אם חסר ח.פ/תאריך,
 *    או אם אותו (ספק|סכום|תאריך) חוזר באותה ריצה.
 *  - אינו מסתמך על תגובת ה-XHR (לא אמינה) אלא רק על מונה-הטיוטות.
 *
 * שימוש יומי: פתח את העמוד, פתח קונסול (F12), הדבק את כל הקובץ, הרץ.
 * בסוף יודפס סיכום: כמה תויקו, ומה עצר. מה שלא תויק אוטומטית — לטיפול ידני.
 *
 * הערה על קטגוריה: הפריט (קטגוריה) מתמלא מ-SUMIT. לנסיעות זה תקין ("הוצאות נסיעה");
 * לקבלות מזון/אחר — לסמן לרו"ח לבדיקה. אפשר להריץ אח"כ את expense_classifier
 * לתיקון סיווג על ההוצאות שתויקו.
 */
(async () => {
  const SAVE = /שמירה כמסמך סופי/;
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const txt = e => e.textContent.trim();
  const pendingCount = () => [...document.querySelectorAll('*')]
    .filter(el => /^#\d+\s*$/.test((el.textContent || '').trim()) && el.children.length === 0).length;
  const hasSave = el => [...el.querySelectorAll('input,button,a')]
    .some(b => SAVE.test(b.value || '') || SAVE.test(b.textContent || ''));
  const dateOK = s => /^\d{1,2}\/\d{1,2}\/\d{4}$/.test(s || '');

  const filed = [];
  const seen = new Set();
  let stopReason = null;
  const MAX = 500; // backstop

  for (let i = 0; i < MAX; i++) {
    // אתר את הטיוטה הפתוחה (מכלי הבועות הגלויים)
    let conts = [...document.querySelectorAll('.og-expenses-quick-ocr-container')].filter(c => c.offsetParent !== null);
    let t = 0;
    while (!conts.length && t < 8) { await wait(700); conts = [...document.querySelectorAll('.og-expenses-quick-ocr-container')].filter(c => c.offsetParent !== null); t++; }
    if (!conts.length) { stopReason = 'אין טיוטה פתוחה — כנראה סיימנו'; break; }

    // root = כרטיס הטיוטה (האב הקרוב שמכיל כפתור שמירה יחיד)
    let root = conts[0];
    while (root && !hasSave(root)) root = root.parentElement;
    if (!root) { stopReason = 'לא נמצא root'; break; }
    const saves = [...root.querySelectorAll('input,button,a')].filter(b => SAVE.test(b.value || '') || SAVE.test(b.textContent || ''));
    if (saves.length !== 1) { stopReason = 'root עמום (כמה כפתורי שמירה)'; break; }
    conts = conts.filter(c => root.contains(c));

    const fieldOf = c => { let p = c, h = 0; while (p && h < 5) { const inp = p.querySelector('input,select,textarea'); if (inp) return inp.name || inp.id || ''; p = p.parentElement; h++; } return ''; };
    const picks = {}; let stid = null, sname = null;
    for (const c of conts) {
      const nm = fieldOf(c);
      const chips = [...c.querySelectorAll('.og-expenses-quick-ocr')];
      if (!chips.length) continue;
      let pick = null;
      if (/Supplier/i.test(nm)) {
        pick = chips.find(ch => /\(\d{8,9}\)/.test(txt(ch)) && /[א-ת]/.test(txt(ch)));
        if (pick) { const m = txt(pick).match(/^(.*)\((\d{8,9})\)/); sname = m ? m[1].trim() : null; stid = m ? m[2] : null; }
      } else if (/^Date$/i.test(nm)) {
        pick = chips.find(ch => /^\d{1,2}\/\d{1,2}\/\d{4}$/.test(txt(ch)));
      } else if (/Total/i.test(nm)) {
        const dec = chips.filter(ch => /^\d{1,3}(,\d{3})*\.\d{1,2}$/.test(txt(ch)));
        if (dec.length) pick = dec.sort((a, b) => parseFloat(txt(b).replace(/,/g, '')) - parseFloat(txt(a).replace(/,/g, '')))[0];
      } else if (/InvoiceNumber/i.test(nm)) {
        const cand = chips.filter(ch => /^\d+$/.test(txt(ch)) && txt(ch) !== stid);
        pick = cand.sort((a, b) => txt(b).length - txt(a).length)[0];
      }
      if (pick) { pick.click(); picks[nm] = txt(pick); }
    }
    await wait(500);

    const modal = !!document.querySelector('.modal.show,[class*="modal"][style*="display: block"],.og-dialog');
    const get = n => { const e = root.querySelector(`[name="${n}"]`); return e ? ('' + e.value).trim() : null; };
    const tot = get('Total'), dt = get('Date');

    if (modal) { stopReason = 'נפתח חלון יצירת ספק — דורש טיפול ידני'; break; }
    if (!stid) { stopReason = 'חסר ח.פ ספק'; break; }
    if (!(parseFloat((tot || '0').replace(/,/g, '')) > 0)) { stopReason = 'אין סכום עשרוני ברור'; break; }
    if (!dateOK(dt)) { stopReason = 'אין תאריך'; break; }
    if (picks['Total'] && tot !== picks['Total']) { stopReason = 'אי-התאמת סכום (scoping)'; break; }

    const key = sname + '|' + tot + '|' + dt;
    if (seen.has(key)) { stopReason = 'חזרה על אותה הוצאה (' + key + ') — עצירה למניעת כפילות'; break; }

    const before = pendingCount();
    saves[0].click();
    let w = 0; while (pendingCount() >= before && w < 30) { await wait(400); w++; }
    const delta = before - pendingCount();
    if (delta !== 1) { stopReason = 'מונה ירד ' + delta + ' (צפוי 1) אחרי ' + key + ' — עצירה'; break; }

    seen.add(key);
    filed.push(key);
    console.log('✓ תויק:', key);
    await wait(1400);
  }

  console.log('=== סיכום ===');
  console.log('תויקו:', filed.length);
  filed.forEach(f => console.log('  ', f));
  console.log('עצירה:', stopReason);
  return { filedCount: filed.length, filed, stopReason };
})();
