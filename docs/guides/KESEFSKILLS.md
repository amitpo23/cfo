# KesefSkills — מקור סקילים אופציונלי

KesefSkills ([kesefskills.co.il](https://kesefskills.co.il/), קטלוג
[catalog.json](https://kesefskills.co.il/catalog.json)) הוא מקור **אופציונלי**
לסקילים של מושקו ושל רצף. הוא לא חלק מחוזה היכולות של רצף ולא מחליף את
`docs/bookkeeper_kb/`, את `docs/rezef_capabilities.json` או את השירותים
שמחשבים יתרה, תזרים ותקציב.

גופי הסקילים לא נשמרים בריפו. הקטלוג החי הוא הרשימה. אינדקס מקומי מ־28.10.2026
מנה 375 סקילים ב־12 חבילות; המספר בקטלוג יכול לזוז, והריפו לא מעתיק אותם.

## התקנה

```bash
npx kesef install <pack> --agent cursor
```

בלי שם חבילה, `npx kesef` פותח את ההתקנה האינטראקטיבית. `<pack>` הוא מזהה
החבילה מהטבלה למטה (`atzmai`, `bank`, …). ההתקנה יורדת לסוכן המקומי. היא לא
משנה דגלי סנכרון, לא קוראת ל־SUMIT או ל־Open Finance, ולא מוסיפה קבצים לריפו.

## חבילות

| מזהה | חבילה | סקילים | דף |
| --- | --- | --- | --- |
| `atzmai` | ערכת עצמאי | 14 | https://kesefskills.co.il/packages/atzmai/ |
| `oved` | ערכת עובד | 15 | https://kesefskills.co.il/packages/oved/ |
| `over-dira` | ערכת עובר דירה | 14 | https://kesefskills.co.il/packages/over-dira/ |
| `mashkanta` | ערכת משכנתא ורכישת דירה | 16 | https://kesefskills.co.il/packages/mashkanta/ |
| `horim` | ערכת הורים וילדים | 15 | https://kesefskills.co.il/packages/horim/ |
| `rechev` | ערכת רכב | 16 | https://kesefskills.co.il/packages/rechev/ |
| `pensia` | ערכת פנסיה וחיסכון | 14 | https://kesefskills.co.il/packages/pensia/ |
| `bank` | ערכת בנק וכרטיסי אשראי | 16 | https://kesefskills.co.il/packages/bank/ |
| `tisa` | ערכת נסיעה לחו״ל | 12 | https://kesefskills.co.il/packages/tisa/ |
| `studentim` | ערכת סטודנטים | 13 | https://kesefskills.co.il/packages/studentim/ |
| `prisha` | ערכת פרישה ועזיבת עבודה | 13 | https://kesefskills.co.il/packages/prisha/ |
| `maasik` | ערכת מעסיק קטן | 15 | https://kesefskills.co.il/packages/maasik/ |

המספרים הם ספירת האינדקס מ־28.10.2026. לפני התקנה בודקים את הקטלוג.

## מה קרוב לרצף

החבילות `atzmai`, `bank` ו־`maasik` הן אלה שנוגעות בהנהלת חשבונות, בתזרים
ובבנק. שאר החבילות הן הקשר אישי (דיור, רכב, פנסיה, משפחה) ואפשר להתקין אותן
כשמושקו נשאל על הנושא, בלי להפוך אותן לספרי הארגון.

סקילים שכדאי להכיר בשם, בלי להעתיק את גופם:

| מזהה | כותרת |
| --- | --- |
| `cash-runway` | תחזית תזרים 13 שבועות |
| `weekly-snapshot` | תמונת מצב שבועית |
| `dashboard-cash-position` | דשבורד יתרות בכל החשבונות |
| `dashboard-income-expenses` | דשבורד הכנסות והוצאות חודשי |
| `expense-categorizer` | סיווג הוצאות וסימון חריגים |
| `accountant-monthly-pack` | חבילה חודשית לרואה החשבון |
| `connect-check` | בדיקת חיבור נתונים |
| `year-end-checklist` | בדיקת סוף שנה לעצמאי |
| `allocation-number-fix` | בודק מספרי הקצאה |

מספר שמושקו מוסר על יתרה, תזרים, תקציב או חיבור מגיע מהכלים ב־
`src/cfo/services/ai_chat_tools.py` ומהשורות שכבר במסד. סקיל חיצוני לא ממלא
יתרה חסרה ב־0 ולא מרענן ספק.
