# מצב רצף

צילום לסוכן ולעמית, נכון ל-24/10/2026. `origin/main` הוא `71ad45c`. מאומת: נבדק בריפו או ב-GitHub באותו יום. נמסר: עמית אמר את זה, בלי בדיקה מול המערכת החיה.

`docs/PROJECT_STATUS.md` הוא ארכיון, לפי `docs/README.md`. לוח השערים נשאר `docs/MASTER_EXECUTION_PLAN.md`.

## מיזוגים מ-#47

לפי זמן המיזוג. השעה היא שעון ישראל, UTC+3, מומרת מ-`mergedAt` של GitHub.

| מוזג | PR | שורה |
| --- | --- | --- |
| 21/10/2026 22:08 | [#47](https://github.com/amitpo23/cfo/pull/47) | תקציב מול ביצוע ב-`/d/` |
| 22/10/2026 08:05 | [#52](https://github.com/amitpo23/cfo/pull/52) | תקרת SUMIT של 50 קריאות בחודש לחשבון, והסרת עבודות SUMIT מהלוח |
| 22/10/2026 08:05 | [#53](https://github.com/amitpo23/cfo/pull/53) | אזהרה על זוגות כפולים, ובדיקת חיוב כרטיס |
| 22/10/2026 08:05 | [#49](https://github.com/amitpo23/cfo/pull/49) | עורך תקציב וסקירת תיוק על המנוע הקיים |
| 22/10/2026 08:07 | [#54](https://github.com/amitpo23/cfo/pull/54) | מכניס ל-main את #53 ואת #49 |
| 22/10/2026 09:19 | [#50](https://github.com/amitpo23/cfo/pull/50) | יבוא תוכנית אליהב ותצוגה של כמה ישויות |
| 22/10/2026 12:27 | [#55](https://github.com/amitpo23/cfo/pull/55) | חמש הלשוניות של כלי אליהב בתוך `/d/`, כולל מאוחד |
| 22/10/2026 14:07 | [#56](https://github.com/amitpo23/cfo/pull/56) | תיקונים אחרי בדיקת עמית של `/d/eliav` |
| 22/10/2026 17:13 | [#57](https://github.com/amitpo23/cfo/pull/57) | סבב UI שני: עורך תקציב, `/budget`, תוויות בעברית, עוגה, יתרת פתיחה |
| 22/10/2026 20:01 | [#58](https://github.com/amitpo23/cfo/pull/58) | שישה פערי P1: G-27, G-26, G-22, G-21, G-11, G-20. הפירוט ב-`docs/DASHBOARD_SOURCE_RULES.md` |
| 22/10/2026 20:16 | [#59](https://github.com/amitpo23/cfo/pull/59) | 34 סקילים של Quegenx ל-Claude Code ול-Cursor |
| 23/10/2026 09:23 | [#60](https://github.com/amitpo23/cfo/pull/60) | ביצועי `/d/`, חודשים מאוחדים עם תווית, observability, עיצוב Koach |
| 23/10/2026 11:51 | [#61](https://github.com/amitpo23/cfo/pull/61) | הכרעות 23/10/2026: רענון Open Finance לילי כבוי, התרעות וואטסאפ כבויות, משיכת SUMIT שבועית, runbooks, רעננות |

בטווח #47 עד #61 לא מוזגו #46, #48 ו-#51. #46 ו-#51 בסעיף "ממתין לעמית". [#48](https://github.com/amitpo23/cfo/pull/48) פתוח כ-draft (התקנת סקילים של Quegenx). #59 כבר מיזג התקנה מאוחרת יותר. עמית לא סימן את #48 כממתין לו.

## פרוד

האתר המתועד הוא `cfo-2.vercel.app` (`AGENTS.md`, `CLAUDE.md`). מאומת: deployment של Production לפרויקט `cfo-2` על `71ad45c` הסתיים בהצלחה ב-GitHub, ב-23/10/2026 11:58 שעון ישראל. לא נשלחה בקשה אל האליאס עצמו. אותו קומיט נרשם גם כ-Production של `cfo-financial-system`.

`origin/main` הוא `71ad45c` (`71ad45c7e6c316c85492d69d8a23568c4b079cac`), מיזוג #61. מאומת ב-git אחרי `git fetch origin main`.

Alembic. מאומת בקוד: head יחיד, `g15b7d43e9f0`, מתוך 71 קבצי מיגרציה. אף `down_revision` לא מצביע אליו. `alembic/versions/g15b7d43e9f0_dashboard_rate_limits.py` יוצר את `dashboard_rate_limits`. ההערה בראש הקובץ עדיין אומרת `Not applied to production`. אותו משפט עומד גם ב-`f14a6c32d8e5`, `h26c8e54f1b2`, `i27c9e65a3d4` ו-`e03f5b21c7d4`. זו הערה בקובץ, לא קריאה של `alembic_version` ב-Neon. עמית מסר שהפרוד על `g15b7d43e9f0`. החותמת לא נשאלה.

Crons. מאומת: ב-`vercel.json` יש ארבעה, ורק הם.

| נתיב | ביטוי | מתי |
| --- | --- | --- |
| `/api/cron/bank-gap-scan` | `15 3 * * *` | 03:15 UTC, כל יום |
| `/api/cron/bookkeeper-morning` | `45 3 * * *` | 03:45 UTC, כל יום |
| `/api/cron/roster-health` | `30 5 * * *` | 05:30 UTC, כל יום |
| `/api/cron/sumit-weekly-pull` | `0 3 * * 0` | יום ראשון, 03:00 UTC |

`SUMIT_WEEKLY_PULL_ENABLED`: ברירת המחדל בקוד היא `false` (`src/cfo/config.py`). כשהדגל כבוי, `/api/cron/sumit-weekly-pull` מחזיר `skipped: sumit_weekly_pull_disabled` בלי לבנות לקוח SUMIT. עמית מסר שהדגל דולק בפרוד. ערך ה-env ב-Vercel לא נקרא, כדי לא לשלוף סודות.

## הכרעות עומדות של עמית

הכרעות 23/10/2026 נבדקו מול `AGENTS.md`, `vercel.json` ו-`src/cfo/config.py`. מה שנמסר בלי עיגון בקוד מסומן נמסר.

- **Open Finance.** הרענון הלילי כבוי. `/api/cron/sync-open-finance` לא ב-`vercel.json`, והנתיב מסרב לריצה בלתי-מאוישת כל עוד `OPEN_FINANCE_SCHEDULED_SYNC_ENABLED` כבוי (ברירת מחדל `false`). רענון רק באישור עמית: נמסר. נתיב ידני לא עובר ב-cron הזה.
- **וואטסאפ.** התרעת 06:00 ירדה מהלוח. `/api/cron/channel-alerts` לא ב-`vercel.json`. `WHATSAPP_PUSH_ENABLED` ברירת מחדל `false`, וכל push יזום לוואטסאפ מדולג כל עוד הדגל כבוי. מענה לשיחה שהמשתמש פתח אינו push. Telegram וההתרעות בתוך המערכת לא תלויים בדגל.
- **SUMIT.** קריאה מתוזמנת לכל היותר פעם בשבוע, או כשעמית מבקש. בקוד: משיכה אחת לשבוע ISO, כל הארגונים יחד, קריאה בלבד, בתוך תקרה של 50 קריאות בחודש לחשבון (`LIVE_ACCOUNT_REQUEST_HARD_CAP`). לפחות 10 נשמרות לבקשות ידניות (`MIN_ON_DEMAND_RESERVE` ב-`sumit_weekly_pull.py`). "לפי בקשה של עמית" נמסר. הדגל השבועי בפרוד לא נקרא, כמפורט למעלה.
- **Runbooks בפורטל SUMIT.** סוכן ה-CFO רשאי להריץ, בתוך תקרת ה-API, את `cfo:close-batch`, `cfo:export-to-hashavshevet`, `cfo:find-duplicate-transactions`, `cfo:month-end-review` ו-`sumit-file-expenses`. שמירה כמסמך סופי דורשת GO מפורש של עמית בכל פעם. התנאים המלאים ב-`AGENTS.md`.
- **שירות בתשלום ותשלום.** אין שירות בתשלום ואין תשלום בלי GO של עמית. נמסר ב-24/10/2026. משפט כזה לא נמצא בריפו. בקוד, תשלום, שידור וסגירה עוברים בקרת פעולה בלתי-הפיכה (`docs/IRREVERSIBLE_ACTION_CONTROL.md`). הנפקת מסמכי SUMIT ב-live כבויה עד `sumit_document_issuance_enabled`. תקרת הפעולות בתשלום ב-live היא 0 כברירת מחדל. בקוד אין שער שחוסם כל שירות בתשלום.
- **GitHub CI וחיוב.** אינם חוסמים עבודה. נמסר ב-24/10/2026. לא נמצא ניסוח כזה בריפו, ולא נבדק חשבון GitHub.

## בעבודה

- **`feat/rezef-parity-phase9`.** נמסר: לוח שיקים בדשבורד, נבנה ב-Claude Code, עדיין לא ב-git. מאומת: הענף לא קיים ב-`origin`. עץ העבודה של Claude Code לא נראה מכאן.
- **`feat/rezef-db-hygiene`.** עמית: סוכן ענן, האצת קיזוז בין-חברתי והיגיינת מיגרציות. מאומת: סוכן ענן בשם `Rezef: DB hygiene + intercompany speedup (AUDIT8 deferred)` רץ מאז 24/10/2026 19:00 UTC, ובלי שם ענף רשום. `feat/rezef-db-hygiene` לא נמצא ב-`origin`.

## ממתין לעמית

- **יתרת פתיחה של פוד גרופ (Food Group), חשבון 1662.** הטופס "יתרת פתיחה ידנית" קיים, וה-placeholder מזכיר "דף בנק 1662" (`frontend/src/components/dashboardTabs.tsx`). הסכום לא בריפו. המסד בפרוד לא נשאל.
- **דוחות Z.** המנגנון `plan.zReports` נכנס ב-#58. הקבצים או הסכומים לא בריפו.
- **סכומי תקציב.** עורך התקציב נכנס ב-#47 וב-#49. הסכומים לא בריפו.
- **החלטת `public-snapshot` / `last_used_at`.** בקוד, `DashboardShareLink.last_used_at` נכתב ב-`mark_link_used`, וה-scope ההתחלתי הוא `snapshot_read`. רשימת הקישורים לבעלים מחזירה `use_count` ולא את `last_used_at` (`src/cfo/services/dashboards/service.py`). תוכן ההחלטה הפתוחה לא רשום בריפו.
- **[#46](https://github.com/amitpo23/cfo/pull/46).** פתוח, draft. פורט auth של Medici: Google OIDC, RBAC, והרשאות אימייל ל-org ולדשבורד.
- **[#51](https://github.com/amitpo23/cfo/pull/51).** פתוח, draft. תוכנית דשבורד v3, מסמך קשיח שמוטל ל-`budgets`.
- **קובץ בנק לדוגמה של אילנה.** נמסר. הקובץ לא נמצא בריפו, וגם לא נבדק מחוץ לריפו.

## סדר בניית הפאריטי

`PARITY_SPEC.md` לא נמצא ב-main, לא בשמות הקבצים ב-git log, ולא בחיפוש הקוד ב-GitHub. סדר הבנייה שנמסר הוא `0`, `1`, `2`, `3`, `4`, `5`, `9`, `6`, `7`, `8`.

כל מספר נשאר בלי תיאור, ואין סימון מה כבר נסגר. `feat/rezef-parity-phase9` הוא מספר הפאזה היחיד על עבודה פתוחה. השיוך של 9 ללוח השיקים נמסר עם שם הענף. הוא לא נקרא מהמסמך.

## מה לא נבדק מול מערכת חיה

- שורת `alembic_version` ב-Neon.
- ערכי env ב-Vercel, כולל `SUMIT_WEEKLY_PULL_ENABLED`.
- בקשת HTTP אל `cfo-2.vercel.app`.
- עץ העבודה של Claude Code ל-`feat/rezef-parity-phase9`.
- תוכן `PARITY_SPEC.md`.
- הסכום של יתרת 1662, דוחות ה-Z, סכומי התקציב, וקובץ הבנק של אילנה.
