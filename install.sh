#!/bin/bash

echo "🚀 מתחיל התקנת מערכת CFO..."
echo ""

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Python version: $python_version"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 יוצר סביבה וירטואלית..."
    python3 -m venv venv
    echo "✓ סביבה וירטואלית נוצרה"
else
    echo "✓ סביבה וירטואלית קיימת"
fi

# Activate virtual environment
echo "🔌 מפעיל סביבה וירטואלית..."
source venv/bin/activate

# Upgrade pip
echo "⬆️  משדרג pip..."
pip install --upgrade pip --quiet

# Install requirements
echo "📚 מתקין תלויות..."
pip install -r requirements.txt --quiet

# Install package
echo "📦 מתקין את מערכת CFO..."
pip install -e . --quiet

# Create .env if it doesn't exist
if [ ! -f ".env" ]; then
    echo "⚙️  יוצר קובץ הגדרות..."
    cp .env.example .env
    echo "✓ נוצר קובץ .env - אנא ערוך אותו עם ה-API keys שלך"
else
    echo "✓ קובץ .env קיים"
fi

# Create reports directory
mkdir -p reports

echo ""
echo "✅ ההתקנה הושלמה בהצלחה!"
echo ""
echo "📝 שלבים הבאים:"
echo "1. ודא שהפעלת את הסביבה הוירטואלית: source venv/bin/activate"
echo "2. ערוך את קובץ .env עם ה-API keys שלך (אופציונלי)"
echo "3. אתחל את מסד הנתונים: cfo init"
echo "4. התחל לעבוד: cfo --help"
echo ""
echo "💡 טיפ: נסה 'cfo demo' לראות את המערכת בפעולה עם נתונים מדומים!"
