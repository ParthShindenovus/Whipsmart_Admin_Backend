# Whipsmart Admin Panel - Django Backend

Complete Django backend for Whipsmart Admin Panel with admin authentication, knowledgebase management, and agentic chatbot sessions.

## Features

- ✅ **Admin Authentication** - Token + Session based authentication
- ✅ **Document CRUD** - Upload/View/Delete/Vectorize PDFs, Docs, TXT files
- ✅ **Chat Sessions** - Session-wise chat message management
- ✅ **Django Admin** - Full admin interface
- ✅ **REST APIs** - DRF ViewSets with pagination, filtering, and search
- ✅ **Pinecone RAG** - Document vector storage integration ready
- ✅ **Production Ready** - PostgreSQL + environment-based configuration

## Project Structure

```
whipsmart_admin/
├── manage.py
├── requirements.txt
├── core/              # Auth & Base models (AdminUser, Session, Document)
├── knowledgebase/     # Document management utilities
├── chats/            # Chat sessions and messages
└── agents/           # LangGraph agent integration
```

## Setup Instructions

### 1. Create Virtual Environment

```bash
python -m venv venv
```

### 2. Activate Virtual Environment

**Windows:**
```bash
venv\Scripts\Activate.ps1
```

**Linux/Mac:**
```bash
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root. See `DATABASE_SETUP.md` for detailed instructions.

**For MySQL (Recommended for production):**
```env
DB_ENGINE=django.db.backends.mysql
DB_NAME=whipsmart_db
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_HOST=localhost
DB_PORT=3306
```

**For SQLite (Default - no setup needed):**
```env
DB_ENGINE=django.db.backends.sqlite3
```

**For PostgreSQL:**
```env
DB_ENGINE=django.db.backends.postgresql
DB_NAME=whipsmart_db
DB_USER=postgres
DB_PASSWORD=your_postgres_password
DB_HOST=localhost
DB_PORT=5432
```

### 5. Create MySQL Database (if using MySQL)

```sql
CREATE DATABASE whipsmart_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 6. Run Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### 7. Create Superuser

```bash
python manage.py createsuperuser
```

### 8. Install Redis (Required for WebSocket support)

**Windows:**
- Download Redis from: https://github.com/microsoftarchive/redis/releases
- Or use WSL: `wsl redis-server`
- Or use Docker: `docker run -d -p 6379:6379 redis:alpine`

**Linux/Mac:**
```bash
# Install Redis
sudo apt-get install redis-server  # Ubuntu/Debian
brew install redis                  # Mac

# Start Redis
redis-server
```

### 9. Verify WebSocket Setup

Before starting the server, verify the setup:

```bash
python test_websocket_setup.py
```

### 10. Run Development Server

**Important:** Django's `runserver` uses WSGI and doesn't support WebSockets. Use uvicorn instead:

**Windows:**
```bash
.\run_server.bat
```

**Linux/Mac:**
```bash
chmod +x run_server.sh
./run_server.sh
```

**Or manually:**
```bash
python -m uvicorn whipsmart_admin.asgi:application --host 0.0.0.0 --port 8000 --reload
```

**Important Notes:**
- Redis must be running for WebSocket support (or it will fallback to InMemoryChannelLayer)
- Use uvicorn (ASGI server) instead of `runserver` for WebSocket support
- The `--reload` flag enables auto-reload on code changes

The API will be available at `http://127.0.0.1:8000/`
WebSocket endpoint: `ws://127.0.0.1:8000/ws/chat/`

## API Endpoints

### Authentication
- `POST /api/users/login/` - Admin user login
- `GET /api/users/me/` - Get current user info

### Users
- `GET /api/users/` - List admin users
- `GET /api/users/{id}/` - Get user details
- `POST /api/users/` - Create user (admin only)
- `PUT /api/users/{id}/` - Update user
- `DELETE /api/users/{id}/` - Delete user

### Sessions
- `GET /api/sessions/` - List sessions
- `GET /api/sessions/{id}/` - Get session details
- `POST /api/sessions/` - Create session
- `PUT /api/sessions/{id}/` - Update session
- `DELETE /api/sessions/{id}/` - Delete session

### Documents
- `GET /api/documents/` - List documents
- `GET /api/documents/{id}/` - Get document details
- `POST /api/documents/` - Upload document
- `PUT /api/documents/{id}/` - Update document
- `DELETE /api/documents/{id}/` - Delete document

### Chat Messages
- `GET /api/chats/messages/` - List chat messages
- `GET /api/chats/messages/{id}/` - Get message details
- `POST /api/chats/messages/` - Create message
- `PUT /api/chats/messages/{id}/` - Update message
- `DELETE /api/chats/messages/{id}/` - Soft delete message

### Knowledgebase
- `GET /api/knowledgebase/stats/` - Get knowledgebase statistics

## Database Schema

### AdminUser
- Extends Django's AbstractUser
- `is_active_admin`: Boolean flag for admin status
- `created_at`: Timestamp

### Session
- `session_id`: Unique session identifier
- `admin_user`: Foreign key to AdminUser (nullable)
- `expires_at`: Session expiration time
- `metadata`: JSON field for additional data

### Document
- `title`: Document title
- `file`: FileField for document storage
- `file_type`: Choice field (pdf/txt/docx)
- `vector_id`: Pinecone vector ID
- `uploaded_by`: Foreign key to AdminUser

### ChatMessage
- `session`: Foreign key to Session
- `message`: Text content
- `role`: Choice field (user/assistant/system)
- `metadata`: JSON field for RAG sources
- `is_deleted`: Soft delete flag

## Technology Stack

- **Django 5.1.2** - Web framework
- **Django REST Framework 3.15.2** - API framework
- **PostgreSQL** - Production database (SQLite for development)
- **Pinecone** - Vector database for RAG
- **LangGraph** - Agent framework
- **Azure OpenAI** - LLM integration

## Development

### Running Tests

```bash
python manage.py test
```

### Creating Migrations

```bash
python manage.py makemigrations
```

### Applying Migrations

```bash
python manage.py migrate
```

### Accessing Django Admin

Navigate to `http://127.0.0.1:8000/admin/` and login with your superuser credentials.

## Production Deployment

1. Set `DEBUG=False` in `.env`
2. Configure PostgreSQL database
3. Set proper `SECRET_KEY`
4. Configure `ALLOWED_HOSTS`
5. Set up static file serving
6. Configure CORS for your frontend domain
7. Set up environment variables for Pinecone and Azure OpenAI

## License

Copyright © 2025 Whipsmart Admin Panel

