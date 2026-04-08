#!/bin/bash
echo "Installing dependencies..."
pip install -r backend/requirements.txt

echo ""
echo "Starting StockApp server..."
echo "Open http://localhost:8000 in your browser"
echo "Press Ctrl+C to stop"
echo ""
cd backend && python main.py
