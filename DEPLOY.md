# Northstar Deployment

This app is set up to deploy as one Python web service on Render.

## What is included

- `render.yaml` for Render service creation
- `backend/main.py` reads `PORT` from the hosting environment
- `frontend/src/main.jsx` and `frontend/src/styles.css` are bundled into `frontend/dist/app.js` and `frontend/dist/app.css`
- `backend/supabase_db.py` reads `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `SUPABASE_SERVICE_ROLE_KEY` from environment variables
- `backend/snaptrade_api.py` reads the SnapTrade credentials from environment variables
- A Render cron service can hit `POST /api/internal/snapshot` after market close
- `.env.example` shows the required variables

## Render steps

1. Push this project to GitHub.
2. In Render, create a new Blueprint or Web Service from the repo.
3. If using the `render.yaml` blueprint, Render will detect:
   - root directory: `backend`
   - build command: `pip install -r requirements.txt && npm --prefix ../frontend ci && npm --prefix ../frontend run build`
   - start command: `python -m uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Set these environment variables in Render:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SNAPTRADE_CLIENT_ID`
   - `SNAPTRADE_CONSUMER_KEY`
   - `SNAPTRADE_REDIRECT_URI`
   - `ALPHAVANTAGE_API_KEY`
   - `STOOQ_API_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `INTERNAL_SNAPSHOT_TOKEN`
   - `NORTHSTAR_BASE_URL`
   - `ALLOWED_ORIGINS`
5. Deploy the service.
6. After the service is live, add your custom domain in Render.
7. Update your DNS records at your domain registrar to the values Render gives you.

## Notes

- The frontend is served by FastAPI, so one web service handles both the UI and API.
- The checked-in `frontend/index.html` is a thin shell. The shipped React bundle lives in `frontend/dist/` and is built from `frontend/src/`.
- For local frontend changes, run `npm --prefix frontend install` once, then `npm --prefix frontend run build` before starting the backend.
- The app already uses relative `/api/...` calls, so no frontend API URL rewrite is needed.
- Run the latest `supabase/schema.sql` before using the brokerage sync endpoints. The historical graph needs `price_history` and `transactions`.
- The cron job in `render.yaml` is scheduled for `30 21 * * 1-5`; Render schedules cron in UTC, so this is 4:30pm ET during standard time and 5:30pm ET during daylight time.
- `POST /api/internal/snapshot` accepts only `Authorization: Bearer $INTERNAL_SNAPSHOT_TOKEN` and writes daily portfolio snapshots plus cached daily closes.
- `ALLOWED_ORIGINS` is comma-separated. Include your Render/custom domain if a separate frontend origin ever calls the API.
- SnapTrade sync flow:
  - `POST /api/brokerage/connect` returns the Connection Portal URL.
  - `GET /api/brokerage/connections` lists the user's brokerage connections.
  - `POST /api/brokerage/sync` pulls accounts and holdings into Supabase.
  - The same sync stores SnapTrade account activity in `transactions` when SnapTrade returns it.
  - `GET /api/brokerage/holdings` and `GET /api/brokerage/portfolio` read the synced data.
- `POST /api/brokerage/sync` supports `refresh_remote`, but SnapTrade charges for manual refreshes, so it defaults to `false`.
- Market data is real only: quotes/charts use Alpha Vantage when configured, then Yahoo Finance, then Stooq when available/configured. The API returns an error instead of inventing prices if providers are unavailable.
