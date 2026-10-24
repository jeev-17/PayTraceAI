# Render deployment checklist

This checklist deploys the Milestone 0 skeleton from the repository root
`render.yaml`: a FastAPI web service, a Vite static site, and a Render Postgres
database. Only `/api/health` is implemented; no PayPal or LLM calls are made.

Render settings and free-tier notes below were checked against the official
Render documentation on 2026-10-24. Recheck the linked pages before deploying,
because plan availability and limits can change.

## Before opening Render

- Push this repository and `render.yaml` to the public GitHub repository.
- Ensure `.env` is not staged or committed. Only `.env.example` contains
  placeholders; never copy actual secret values into `render.yaml`,
  documentation, frontend variables, or Git.
- The API and Postgres database use the `oregon` region so they can use
  Render's internal database connection. Change both `region` values together
  if another supported Render region is preferable. The static site is served
  globally via Render's CDN and has no service region setting.

## Create and deploy the Blueprint

1. Sign in to the [Render Dashboard](https://dashboard.render.com).
2. Select **New > Blueprint** and connect the GitHub repository containing
   `render.yaml`.
3. Choose the branch to deploy. Render discovers the Blueprint at the
   repository root.
4. Review the proposed resources: `paytrace-ai-api` (Python web service),
   `paytrace-ai-frontend` (global static site), and `paytrace-ai-db`
   (Postgres).
   The Blueprint requests the `free` plan for the API and database; static
   sites are free to deploy.
5. Select **Deploy Blueprint** and wait for the database, API, and static-site
   deploys to complete. Check each resource's **Events** and **Logs** if any
   deploy fails.
6. Open the static site's `onrender.com` URL. Its API base URL is linked to the
   backend service hostname, and the API's CORS allowlist is linked to the
   static-site hostname. The application adds `https://` to a linked hostname
   when needed; the service references avoid guessing URLs if Render adds a
   suffix to resource names.

The Blueprint passes the database's internal connection string to the API as
`DATABASE_URL`. Keep the database and web service in the same region so the
internal connection URL is usable. `backend/app/database.py` keeps SQLite URLs
working locally and normalizes both `postgres://` and `postgresql://` to the
installed `psycopg` driver for SQLAlchemy.

## Environment variables

The Blueprint supplies the service-to-service values below. Do not replace
these linked values with copied connection strings unless you understand that
they may rotate or change when the database/service is changed.

| Variable | Service | Required now? | Value / handling |
| --- | --- | --- | --- |
| `DATABASE_URL` | API | Yes | Linked to the Render Postgres internal `connectionString`. Do not commit or expose it. |
| `FRONTEND_ORIGIN` | API | Yes | Linked to the static site's `host`. The backend normalizes a bare hostname to an HTTPS origin for CORS. |
| `VITE_API_BASE_URL` | Static site build | Yes | Linked to the API web service's `host`. Vite embeds this public URL into the frontend build; it must not contain a secret. |
| `PORT` | API | Render-managed | Do not set manually. The start command binds to `$PORT` on `0.0.0.0`. |
| `PAYPAL_CLIENT_ID` | API | No, not used by this skeleton | If added for a later milestone, use only PayPal Sandbox credentials. Add in the API service's **Environment** page. |
| `PAYPAL_CLIENT_SECRET` | API | No, not used by this skeleton | Future server-only Sandbox secret. Add only in the API service's **Environment** page; never expose to Vite or the static site. |
| `PAYPAL_BASE_URL` | API | No | Defaults to `https://api-m.sandbox.paypal.com`. Do not point this project at live PayPal endpoints. |
| `PAYPAL_WEBHOOK_ID` | API | No, not used by this skeleton | Future Sandbox webhook configuration. Add only in the API service's **Environment** page. |
| `LLM_PROVIDER` | API | No, not used by this skeleton | Future backend-only provider setting; not a secret. |
| `LLM_API_KEY` | API | No, not used by this skeleton | Future server-only hosted LLM key. Add only in the API service's **Environment** page. |
| `LLM_MODEL` | API | No, not used by this skeleton | Future backend-only model setting; not a secret. |
| `PENDING_THRESHOLD_MINUTES` | API | No | Defaults to `10`. |

For future credentials, use the Render Dashboard: open the **API web service**,
select **Environment**, choose **Add Environment Variable**, enter the key and
secret value, and save with **Save, rebuild, and deploy** (or the available
save-and-deploy option). These values are host-managed and must never be added
to Git. Do not use the frontend/static-site environment to store credentials.
Render's Blueprint `sync: false` values are not used here because Render only
prompts for them during initial Blueprint creation; future new secrets should
be entered in the service's Environment page.

## Smoke test

1. **Backend health:** Open
   `https://<API-service-host>/api/health`. Expect HTTP `200`, `"status":"ok"`,
   and `config_present` booleans only. Missing PayPal or LLM keys are expected
   for this milestone. Do not share screenshots containing environment
   variables or database connection details.
2. **Frontend and CORS:** Open `https://<static-site-host>`. Confirm the page
   loads and the Backend health status changes to `ok`, with configuration
   presence booleans displayed. In browser developer tools, the `/api/health`
   request should go to the API host and return successfully. A browser CORS
   error usually means `FRONTEND_ORIGIN` did not resolve to the exact static
   site origin; confirm the service reference and redeploy the API.
3. **Database initialization:** In the API service's deploy logs, confirm
   startup completes without a database/driver error. `Base.metadata.create_all`
   creates the tables in the configured Postgres database. The health route
   itself does not query the database.
4. **Persistence across a redeploy:** From the Postgres service's **Connect**
   menu, use the external connection details with `psql` or a trusted Postgres
   client. Do not paste the external connection URL into Git, a ticket, or a
   chat. Run:

   ```sql
   CREATE TABLE IF NOT EXISTS deployment_smoke_test (
       id text PRIMARY KEY,
       created_at timestamptz NOT NULL DEFAULT now()
   );
   INSERT INTO deployment_smoke_test (id)
   VALUES ('paytrace-ai-deploy-check')
   ON CONFLICT (id) DO NOTHING;
   SELECT id, created_at
   FROM deployment_smoke_test
   WHERE id = 'paytrace-ai-deploy-check';
   ```

   Trigger a **Manual Deploy** of the API web service in Render. Reconnect to
   the same Postgres database and run the `SELECT` again; the row and original
   timestamp should remain. Afterwards, remove the smoke-test table:

   ```sql
   DROP TABLE deployment_smoke_test;
   ```

   This checks persistence in Render Postgres across an API redeploy. The
   skeleton has no write/read API endpoint, so this test uses a temporary
   database-only table rather than claiming the health route checks database
   persistence.

## Free-tier behavior and data-retention warning

Render's current Free instance documentation states:

- A free web service spins down after 15 minutes without inbound traffic; a
  cold start takes about one minute. The first page/health request may be
  noticeably slow while the API wakes.
- Free web services have an ephemeral filesystem. Local SQLite data on the
  service is lost on spin-down, restart, or redeploy. Use the linked Postgres
  database for deployed data; SQLite is for local development only.
- Free web services share 750 included instance hours per workspace per
  calendar month. Free web services and static sites also count against
  workspace included bandwidth and build-pipeline usage. Check **Billing >
  Monthly Included Usage** in Render; exhaustion may suspend services or block
  builds depending on the usage category and billing configuration.
- A free Render Postgres database is limited to 1 GB, has no backups, and
  expires 30 days after creation. After expiration it is inaccessible; Render
  provides a 14-day grace period to upgrade, after which it deletes the
  database and its data. Upgrade before expiry if the data must be retained.
- Render cautions that free instances are for testing/hobby use and not
  production applications. The database may restart or become unavailable
  temporarily.

## Official Render references

- [Blueprints and setup](https://render.com/docs/infrastructure-as-code)
- [Blueprint specification](https://render.com/docs/blueprint-spec)
- [Free instance limitations](https://render.com/docs/free)
- [Static sites](https://render.com/docs/static-sites)
- [Environment variables and secrets](https://render.com/docs/configure-environment-variables)
- [Creating and connecting to Render Postgres](https://render.com/docs/postgresql-creating-connecting)
- [Web service port binding](https://render.com/docs/web-services#port-binding)
