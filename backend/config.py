"""App configuration — all env vars and constants in one place."""
import os

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://rlvhqtiywcdmlvrpostb.supabase.co")
SUPABASE_ANON_KEY = os.getenv(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJsdmhxdGl5d2NkbWx2cnBvc3RiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU2NzA4MzMsImV4cCI6MjA5MTI0NjgzM30.hbyQ6Na1MbVtcr7--eRhthxSYSGKeEXxcbI4w-Dli94",
)

# SnapTrade (week 3-4)
SNAPTRADE_CLIENT_ID = os.getenv("SNAPTRADE_CLIENT_ID", "")
SNAPTRADE_CONSUMER_KEY = os.getenv("SNAPTRADE_CONSUMER_KEY", "")

# Anthropic (week 9-10)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

PORT = int(os.getenv("PORT", "8000"))
