#!/bin/bash

# Quick start script for CFO system
# הרצת התחלה מהירה למערכת CFO

echo "🚀 מערכת CFO - התחלה מהירה"
echo "================================"
echo ""

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  הסביבה הוירטואלית לא פעילה"
    echo "מפעיל סביבה וירטואלית..."
    source venv/bin/activate
fi

# Check if database exists
if [ ! -f "cfo.db" ]; then
    echo "📊 מאתחל מסד נתונים..."
    cfo init
    echo ""
fi

# Show menu
while true; do
    echo ""
    echo "בחר פעולה:"
    echo "1. הצג סיכום פיננסי"
    echo "2. הצג חשבונות"
    echo "3. הצג עסקאות אחרונות"
    echo "4. הוסף חשבון חדש"
    echo "5. הוסף עסקה"
    echo "6. צור דוח"
    echo "7. הדגמה עם נתונים מדומים"
    echo "8. עזרה"
    echo "9. יציאה"
    echo ""
    read -p "בחירה (1-9): " choice

    case $choice in
        1)
            cfo summary
            ;;
        2)
            cfo list-accounts
            ;;
        3)
            cfo list-transactions
            ;;
        4)
            cfo add-account
            ;;
        5)
            cfo add-transaction
            ;;
        6)
            cfo report
            ;;
        7)
            cfo demo
            ;;
        8)
            cfo --help
            ;;
        9)
            echo "להתראות! 👋"
            exit 0
            ;;
        *)
            echo "בחירה לא תקינה"
            ;;
    esac
done
