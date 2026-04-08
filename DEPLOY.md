# Northstar Deployment

This app is set up to deploy as one Python web service on Render.

## What is included

- `render.yaml` for Render service creation
- `backend/main.py` reads `PORT` from the hosting environment
- `backend/supabase_db.py` reads `SUPABASE_URL` and `SUPABASE_ANON_KEY` from environment variables
- `.env.example` shows the required variables

## Render steps

1. Push this project to GitHub.
2. In Render, create a new Blueprint or Web Service from the repo.
3. If using the `render.yaml` blueprint, Render will detect:
   - root directory: `backend`
   - build command: `pip install -r requirements.txt`
   - start command: `python -m uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Set these environment variables in Render:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
5. Deploy the service.
6. After the service is live, add your custom domain in Render.
7. Update your DNS records at your domain registrar to the values Render gives you.

## Notes

- The frontend is served by FastAPI, so one web service handles both the UI and API.
- The app already uses relative `/api/...` calls, so no frontend API URL rewrite is needed.
