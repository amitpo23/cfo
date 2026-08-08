/**
 * מדיניות פרטיות — דף ציבורי.
 *
 * נדרש ע"י Meta לפרסום אפליקציית WhatsApp Business, ולכן חייב להיות נגיש
 * **ללא התחברות**: App.tsx מרנדר אותו לפני שער האימות (ראו הבדיקה על
 * window.location.pathname שם). Meta סורקת את הכתובת הזו, ומשתמש שלא
 * מחובר חייב להגיע לתוכן ולא למסך ההתחברות.
 *
 * התוכן מתאר את מה שהמערכת עושה **בפועל** — כל שורה כאן ניתנת להצלבה מול
 * הקוד. אין להוסיף כאן הצהרה שאין לה כיסוי במימוש.
 */
import React from 'react';

const UPDATED = '28 ביולי 2026';
const CONTACT = 'amitporat1981@gmail.com';

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <section className="mb-8">
    <h2 className="text-xl font-bold mb-3 text-gray-900">{title}</h2>
    <div className="space-y-2 text-gray-700 leading-relaxed">{children}</div>
  </section>
);

const PrivacyPolicy: React.FC = () => (
  <div dir="rtl" className="min-h-screen bg-gray-50 py-12 px-4">
    <div className="max-w-3xl mx-auto bg-white rounded-2xl shadow-sm p-8 md:p-12">
      <h1 className="text-3xl font-bold mb-2 text-gray-900">מדיניות פרטיות — רצף</h1>
      <p className="text-sm text-gray-500 mb-8">עודכן לאחרונה: {UPDATED}</p>

      <p className="text-gray-700 leading-relaxed mb-8">
        רצף היא מערכת לניהול כספים והנהלת חשבונות לעסקים בישראל. המסמך מתאר אילו
        נתונים המערכת אוספת, לאיזו מטרה, עם מי הם משותפים, וכיצד ניתן לממש זכויות
        לגביהם. הוא חל גם על השימוש בעוזר השיחה <strong>מושקו</strong> בערוצי
        WhatsApp ו-Telegram.
      </p>

      <Section title="1. מי אנחנו">
        <p>
          המערכת מופעלת עבור בעל העסק שהתקשר עמנו. כל ארגון רואה אך ורק את הנתונים
          שלו; הפרדת הארגונים נאכפת בכל שכבות המערכת.
        </p>
        <p>לפניות בנושא פרטיות: <a className="text-blue-600 underline" href={`mailto:${CONTACT}`}>{CONTACT}</a></p>
      </Section>

      <Section title="2. אילו נתונים נאספים">
        <ul className="list-disc pr-6 space-y-1">
          <li><strong>נתוני הנהלת חשבונות</strong> — חשבוניות, קבלות, הוצאות, לקוחות וספקים, המסונכרנים ממערכת SUMIT בהרשאת בעל העסק.</li>
          <li><strong>נתונים בנקאיים</strong> — יתרות, תנועות ומסגרות אשראי, המתקבלים דרך בנקאות פתוחה (Open Finance) לאחר מסע הסכמה מפורש שהלקוח משלים מול הבנק.</li>
          <li><strong>פרטי משתמש</strong> — שם, כתובת דוא"ל, מספר טלפון ותפקיד בארגון.</li>
          <li><strong>תוכן שיחות עם מושקו</strong> — ההודעות שנשלחות ומתקבלות, וכן העדפות והקשר שהמשתמש ביקש במפורש שייזכרו.</li>
          <li><strong>מסמכים שנשלחים למושקו</strong> — צילומי קבלות וחשבוניות שהמשתמש שולח לצורך קליטתם.</li>
          <li><strong>זהות ערוץ</strong> — מספר הטלפון ב-WhatsApp או מזהה השיחה ב-Telegram, לאחר אימות, לצורך קישור בין הערוץ לחשבון.</li>
          <li><strong>רישומי פעולה</strong> — תיעוד פעולות מהותיות במערכת לצורכי ביקורת ואבטחה.</li>
        </ul>
        <p className="pt-2">
          איננו אוספים נתונים ממשתמשים שלא אומתו. הודעה שמגיעה ממספר שאינו מקושר
          לחשבון מקבלת מענה קבוע והסבר כיצד להתחבר, ואינה מעובדת מעבר לכך.
        </p>
      </Section>

      <Section title="3. למה הנתונים משמשים">
        <ul className="list-disc pr-6 space-y-1">
          <li>הצגת מצב פיננסי: תזרים, רווח והפסד, גבייה, מצב מע"מ ומוכנות דיווח.</li>
          <li>קליטה וסיווג של הוצאות, ואיתור מסמכים חסרים או כפילויות.</li>
          <li>התרעות על אירועים מהותיים, כגון חריגת מסגרת אשראי או פער בין תנועות בנק למסמכים.</li>
          <li>מענה לשאלות בשיחה, על בסיס נתוני המערכת בלבד.</li>
        </ul>
        <p className="pt-2">
          <strong>איננו מוכרים נתונים ואיננו משתמשים בהם לפרסום.</strong> נתוני
          הלקוחות אינם משמשים לאימון מודלים.
        </p>
      </Section>

      <Section title="4. עם מי הנתונים משותפים">
        <p>נעשה שימוש בספקי תשתית ושירות, כל אחד למטרה מוגדרת:</p>
        <ul className="list-disc pr-6 space-y-1">
          <li><strong>SUMIT</strong> — מערכת הנהלת החשבונות שממנה מסונכרנים המסמכים ואליה מתויקות הוצאות.</li>
          <li><strong>ספק בנקאות פתוחה</strong> — קבלת נתוני חשבונות בהסכמת הלקוח.</li>
          <li><strong>Anthropic</strong> — עיבוד שפה לצורך השיחה וקריאת מסמכים שנשלחו. תוכן ההודעות והמסמכים נשלח לעיבוד ואינו משמש לאימון.</li>
          <li><strong>Meta (WhatsApp) ו-Telegram</strong> — העברת ההודעות בערוצים עצמם.</li>
          <li><strong>Vercel ו-Neon</strong> — אירוח המערכת ואחסון מסד הנתונים.</li>
          <li><strong>שירות דואר יוצא</strong> — משלוח דוחות והתראות לכתובת שהמשתמש הגדיר.</li>
        </ul>
        <p className="pt-2">
          מעבר לאלה, נתונים נמסרים לצד שלישי רק בהוראת בעל העסק או כנדרש על פי דין.
        </p>
      </Section>

      <Section title="5. אבטחת מידע">
        <ul className="list-disc pr-6 space-y-1">
          <li>פרטי ההתחברות לאינטגרציות נשמרים מוצפנים ואינם נחשפים בממשק.</li>
          <li>הגישה מחייבת הזדהות; כל שאילתה מוגבלת לארגון של המשתמש.</li>
          <li>חיבור ערוץ שיחה מחייב אימות דו-שלבי: שליטה במכשיר וגם בתיבת הדואר הרשומה.</li>
          <li>פעולות בעלות השפעה בלתי-הפיכה — תשלום, שידור דיווח, סגירת תקופה — מחייבות אישור מפורש ואינן מבוצעות אוטומטית.</li>
        </ul>
      </Section>

      <Section title="6. שמירת נתונים">
        <p>
          נתוני הנהלת החשבונות נשמרים כל עוד ההתקשרות בתוקף, ובכפוף לחובות שמירת
          מסמכים על פי דיני המס בישראל. היסטוריית שיחה וזיכרון העדפות נשמרים עד
          שהמשתמש מבקש למחוק אותם או עד סיום ההתקשרות.
        </p>
      </Section>

      <Section title="7. זכויותיך">
        <ul className="list-disc pr-6 space-y-1">
          <li><strong>עיון</strong> — לקבל את הנתונים המוחזקים עליך.</li>
          <li><strong>תיקון</strong> — לתקן נתון שגוי.</li>
          <li><strong>מחיקה</strong> — לבקש מחיקת נתונים, בכפוף לחובות שמירה על פי דין.</li>
          <li><strong>מחיקת זיכרון</strong> — לומר למושקו בשיחה "תשכח את זה", והרשומה תימחק.</li>
          <li><strong>ניתוק ערוץ</strong> — לבטל את קישור מספר הטלפון או שיחת ה-Telegram בכל עת.</li>
          <li><strong>ביטול הסכמה</strong> — לבטל את ההסכמה לבנקאות פתוחה מול הבנק, ואיסוף הנתונים ייפסק.</li>
        </ul>
        <p className="pt-2">למימוש זכות: <a className="text-blue-600 underline" href={`mailto:${CONTACT}`}>{CONTACT}</a></p>
      </Section>

      <Section title="8. שינויים במדיניות">
        <p>
          מדיניות זו עשויה להתעדכן. תאריך העדכון האחרון מופיע בראש העמוד, ושינוי
          מהותי יימסר למשתמשים.
        </p>
      </Section>

      <hr className="my-8 border-gray-200" />

      <div dir="ltr" className="text-left">
        <h2 className="text-lg font-bold mb-2 text-gray-900">Privacy Policy — English summary</h2>
        <p className="text-gray-700 leading-relaxed text-sm">
          Rezef is a financial management and bookkeeping system for Israeli businesses.
          We collect accounting data synced from SUMIT, bank account data obtained through
          Open Finance with the customer&apos;s explicit consent, user account details,
          conversations with our assistant &quot;Moshko&quot;, and receipt images the user
          sends for processing. Data is used solely to operate the service for that business.
          We share data only with the infrastructure providers required to deliver it:
          SUMIT, our Open Finance provider, Anthropic (language processing), Meta and
          Telegram (message delivery), Vercel and Neon (hosting and database), and an email
          provider. <strong>We do not sell data, do not use it for advertising, and do not
          use customer data to train models.</strong> Messages from unverified phone numbers
          are not processed. Users may request access, correction or deletion of their data,
          erase stored preferences, unlink a messaging channel, or withdraw Open Finance
          consent at any time. Contact:{' '}
          <a className="text-blue-600 underline" href={`mailto:${CONTACT}`}>{CONTACT}</a>
        </p>
      </div>
    </div>
  </div>
);

export default PrivacyPolicy;
