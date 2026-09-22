# Personal Knowledge Assistant

A FastAPI application that ingests data from multiple platforms (Gmail, Slack, Discord, Telegram, PDFs), processes it through a RAG pipeline, and provides an agentic chat interface for semantic search over your personal knowledge base.

## Features

- **Multi-platform ingestion** — Gmail, Slack, Discord, Telegram, and PDF uploads
- **RAG pipeline** — cleaning, chunking, embedding, and vector storage
- **Agentic chat** — conversational interface powered by LLM with tool-use capabilities
- **OAuth integration** — secure authentication flows for each platform

## Architecture

```
Loader → CleanerDispatcher → LangChainChunker → SentenceTransformerEmbedder → ChromaVectorStore
```

| Component | Description |
|-----------|-------------|
| **Loaders** | Fetch raw data from Gmail, Slack, Discord, Telegram, and PDFs |
| **Cleaners** | Normalize and sanitize content (HTML stripping, whitespace, emoji handling) |
| **Chunker** | Splits text into overlapping chunks (1000 chars, 200 overlap) |
| **Embedder** | Generates 768-dim vectors using `all-mpnet-base-v2` |
| **Vector Store** | Persists embeddings in ChromaDB with `source_type` filtering |
| **Agent** | Multi-turn tool-use loop against LLM for conversational search |

## Prerequisites

- Python 3.12+
- PostgreSQL
- Platform API credentials (see [Configuration](#configuration))

## Setup

1. **Clone the repository**

   ```bash
   git clone <your-repo-url>
   cd Personal-Knowledge-Assistant
   ```

2. **Create a virtual environment**

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/Mac
   .venv\Scripts\activate     # Windows
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**

   Create a `.env` file in the project root:

   ```env
   # PostgreSQL
   POSTGRES_HOST=localhost
   POSTGRES_PORT=5432
   POSTGRES_DB=knowledge_assistant
   POSTGRES_USER=your_user
   POSTGRES_PASSWORD=your_password

   # App Auth
   SECRET_KEY=your_secret_key
   ALGORITHM=HS256
   ACCESS_TOKEN_EXPIRE_MINUTES=30

   # Groq LLM
   GROQ_API_KEY=your_groq_api_key
   GROQ_MODEL=qwen/qwen3.6-27b

   # Google (Gmail)
   GOOGLE_CLIENT_ID=your_client_id
   GOOGLE_CLIENT_SECRET=your_client_secret
   GOOGLE_REDIRECT_URI=http://localhost:5000/api/v1/auth/google/callback

   # Slack
   SLACK_CLIENT_ID=your_client_id
   SLACK_CLIENT_SECRET=your_client_secret
   SLACK_REDIRECT_URI=http://localhost:5000/api/v1/auth/slack/callback
   SLACK_BOT_TOKEN=your_bot_token

   # Discord
   DISCORD_CLIENT_ID=your_client_id
   DISCORD_CLIENT_SECRET=your_client_secret
   DISCORD_REDIRECT_URI=http://localhost:5000/api/v1/auth/discord/callback
   DISCORD_BOT_TOKEN=your_bot_token

   # Telegram
   TELEGRAM_API_ID=your_api_id
   TELEGRAM_API_HASH=your_api_hash
   ```

5. **Run the server**

   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 5000
   ```

   The app will be available at `http://localhost:5000`.

## API Endpoints

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/register` | Register a new user |
| POST | `/api/v1/auth/login` | Login and receive JWT token |

### Platform Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/auth/google` | Start Google OAuth flow |
| GET | `/api/v1/auth/slack` | Start Slack OAuth flow |
| GET | `/api/v1/auth/discord` | Start Discord OAuth flow |
| POST | `/api/v1/auth/telegram` | Start Telegram auth (phone + code) |

### Ingestion

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/ingest/gmail` | Ingest emails from Gmail |
| POST | `/api/v1/ingest/slack` | Ingest messages from Slack |
| POST | `/api/v1/ingest/discord` | Ingest messages from Discord |
| POST | `/api/v1/ingest/telegram` | Ingest messages from Telegram |
| POST | `/api/v1/ingest/pdf` | Upload and ingest PDF files |

### Chat

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/chat` | Send a message to the assistant |
| POST | `/api/v1/chat/reset` | Reset a chat session |

## Project Structure

```
├── agent/                  # Agentic chat layer
│   ├── controller.py       # Multi-turn tool-use loop
│   ├── llm_client.py       # Groq API client
│   ├── tools.py            # Tool implementations (search)
│   ├── tool_executer.py    # Tool registry and execution
│   ├── state.py            # Conversation state management
│   └── system_prompt.py    # System prompt composition
├── database/               # Data persistence
│   ├── models.py           # SQLAlchemy ORM models
│   ├── postgresql.py       # PostgreSQL CRUD operations
│   └── base_database.py    # Database ABC
├── loaders/                # Platform data loaders
│   ├── gmail_loader.py     # Google API client
│   ├── slack_loader.py     # Slack Web API via httpx
│   ├── discord_loader.py   # Discord REST API via httpx
│   ├── telegram_loader.py  # Telethon (MTProto)
│   └── pdf_loader.py       # PyMuPDF extraction
├── rag/                    # RAG pipeline
│   ├── pipeline.py         # Orchestrates clean → chunk → embed → store
│   ├── chunker.py          # LangChain text splitter
│   ├── embedder.py         # SentenceTransformer embeddings
│   ├── preprocessing/      # Platform-specific cleaners
│   └── vector_store/       # ChromaDB vector store
├── routers/                # FastAPI route handlers
├── schemas/                # Request/response models
├── services/               # Auth services per platform
├── static/                 # Frontend (single-page app)
├── config.py               # Settings via pydantic-settings
├── initializer.py          # Shared singletons
├── main.py                 # App entrypoint
├── models.py               # Pydantic data models
└── requirements.txt        # Python dependencies
```

## Tech Stack

- **Framework**: FastAPI + Uvicorn
- **Database**: PostgreSQL + SQLAlchemy
- **Vector Store**: ChromaDB
- **Embeddings**: SentenceTransformers (`all-mpnet-base-v2`)
- **LLM**: Groq API
- **Auth**: JWT (PyJWT) + Argon2 password hashing (pwdlib)
