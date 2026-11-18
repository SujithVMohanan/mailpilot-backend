# MailPilot Backend

Django REST API for Gmail integration, email synchronization, and rule-based email automation. PostgreSQL stores application data, while Redis and Celery run background synchronization and rule-execution tasks.

## Requirements

- Python 3.11 or newer
- PostgreSQL 14 or newer
- Redis 7 or newer
- Docker Desktop and Docker Compose (Docker setup only)
- Google Cloud project with the Gmail API enabled (for Gmail OAuth and sync)

## Clone the repository

```powershell
git clone https://github.com/SujithVMohanan/mailpilot-backend.git
cd mailpilot-backend
```

## Configure environment

Create the backend environment file:

```powershell
Copy-Item .env.example .env
notepad .env
```

Set a secure `SECRET_KEY`, database credentials, and Google OAuth client ID and secret. For the manual setup, use `DB_HOST=localhost` and `CELERY_BROKER_URL=redis://localhost:6379/0`. Docker Compose sets the database host and Celery broker for its containers.

## Run manually

Start PostgreSQL and Redis, then install and start the API:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Keep the API terminal running. In two additional terminals, activate the virtual environment and start Celery:

```powershell
.\venv\Scripts\Activate.ps1
celery -A config worker --pool=solo --loglevel=info
```

```powershell
.\venv\Scripts\Activate.ps1
celery -A config beat --loglevel=info
```

The `solo` worker pool is suitable for local development on Windows.

## Run with Docker

After configuring `.env`, build and start the API, PostgreSQL, Redis, Celery worker, and Celery Beat:

```powershell
docker compose up --build -d
docker compose ps
```

The API container applies database migrations during startup. Create an admin user if needed:

```powershell
docker compose exec api python manage.py createsuperuser
```

View service logs and stop the stack:

```powershell
docker compose logs -f api celery-worker celery-beat
docker compose down
```

## URLs

- API base URL: `http://localhost:8000/api/`
- Swagger API documentation: `http://localhost:8000/api/docs/`
- ReDoc API documentation: `http://localhost:8000/api/docs/redoc/`
- OpenAPI JSON: `http://localhost:8000/api/docs/json/`
- Django admin: `http://localhost:8000/admin/`

### Using Swagger

1. Start the API and open `http://localhost:8000/api/docs/`.
2. Expand an endpoint to review its parameters, request body, and response format.
3. Use `POST /api/users/register/` or `POST /api/users/login/` to get an access token.
4. Select **Authorize**, enter `Bearer <access-token>`, and select **Authorize** again. This adds the token to protected API requests.
5. Select **Try it out**, enter any required values, then select **Execute** to send the request and view its response and status code.

Registration, login, and token refresh do not require authorization. Other endpoints may require an access token.

## API endpoints

Protected endpoints require a JWT access token in the `Authorization` header. Request and response schemas are available in Swagger.

### Users — `/api/users/`

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/register/` | Register a user |
| POST | `/login/` | Log in and obtain tokens |
| POST | `/refresh/` | Refresh an access token |
| POST | `/logout/` | Log out and blacklist a refresh token |
| GET | `/me/` | Get the current user's profile |
| GET | `/get-users/` | List users |
| DELETE | `/delete-users/` | Delete users |

### Gmail and email — `/api/mail/`

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/oauth/initiate/` | Start Gmail OAuth authorization |
| POST | `/oauth/callback/` | Complete Gmail OAuth authorization |
| POST | `/disconnect/` | Disconnect the Gmail account |
| GET | `/labels/` | List Gmail labels |
| GET | `/` | List and search synchronized emails |
| GET | `/<email-id>/` | Get email details |
| GET | `/stats/` | Get dashboard statistics |

### Email synchronization — `/api/v1/mail/`

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/sync/` | Queue a manual email sync |
| GET | `/sync/` | Get sync status and timestamps |

Automatic Gmail synchronization is scheduled every five minutes. Manual and automatic sync requests use the same queue and per-account lock.

### Rules — `/api/rules/`

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/` | List rules |
| POST | `/` | Create a rule |
| GET | `/<rule-id>/` | Get a rule |
| PUT/PATCH | `/<rule-id>/` | Update a rule |
| DELETE | `/<rule-id>/` | Delete a rule |
| POST | `/<rule-id>/toggle/` | Enable or disable a rule |
| POST | `/<rule-id>/execute/` | Queue a rule execution |
| POST | `/execute-all/` | Queue all active rules |
| GET | `/executions/` | List execution history |

## Main packages

Dependencies and pinned versions are maintained in [`requirements.txt`](requirements.txt).

- Django and Django REST Framework
- Simple JWT for API authentication
- Psycopg for PostgreSQL
- Celery and Redis for background tasks
- Google Auth and Google API Client for Gmail OAuth/API access
- drf-yasg for Swagger and ReDoc documentation
- django-cors-headers for CORS support
- pytest and pytest-django for tests
