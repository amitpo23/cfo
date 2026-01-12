#!/bin/bash

# CFO System - Quick Start Script

echo "=================================="
echo "CFO Financial Management System"
echo "=================================="
echo ""

# Check Python version
echo "📋 Checking Python version..."
python --version

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python -m venv venv
fi

# Activate virtual environment
echo "🔌 Activating virtual environment..."
source venv/bin/activate

# Install backend dependencies
echo "📥 Installing backend dependencies..."
pip install -r requirements.txt

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "⚙️  Creating .env file..."
    cat > .env << EOF
# SUMIT API Configuration
SUMIT_API_KEY=your_sumit_api_key_here
SUMIT_COMPANY_ID=your_company_id_here

# Database
DATABASE_URL=sqlite:///./cfo.db

# Application
APP_NAME=CFO Management System
DEBUG=True
LOG_LEVEL=INFO

# Security
SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

# Optional
OPENAI_API_KEY=your_openai_key_here
EOF
    echo "✅ Created .env file. Please update with your actual API keys!"
fi

# Initialize database
echo "🗄️  Initializing database..."
python -c "from src.cfo.database import init_db; init_db()"

# Install frontend dependencies
echo "📥 Installing frontend dependencies..."
cd frontend
if [ ! -d "node_modules" ]; then
    npm install
fi
cd ..

echo ""
echo "✅ Setup complete!"
echo ""
echo "To start the system:"
echo "  1. Backend:  uvicorn src.cfo.api:app --reload --port 8000"
echo "  2. Frontend: cd frontend && npm run dev"
echo ""
echo "Documentation will be available at:"
echo "  - API Docs: http://localhost:8000/api/docs"
echo "  - Frontend:  http://localhost:3000"
echo ""
