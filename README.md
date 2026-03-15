# Firecrawl-Docling RAG System

A RAG (Retrieval-Augmented Generation) system powered by **Firecrawl** for web crawling and **Docling** for PDF/document parsing.

## Features

- **Firecrawl Integration**: Automatically crawls websites and extracts clean markdown content
- **Docling Integration**: AI-powered PDF and document parsing with layout analysis
- **Gemini AI**: Uses Google Gemini for embeddings and chat
- **pgvector**: PostgreSQL with vector similarity search
- **Unified Search**: Query across all indexed web and document content

## Quick Start

### 1. Start Infrastructure

```powershell
cd infrastructure
docker compose up -d
```

### 2. Start Backend

```powershell
cd backend
# Create virtual environment
uv venv
.venv\Scripts\activate
uv pip install -e .

# Run
uvicorn app:app --reload
```

### 3. Start Frontend

```powershell
cd frontend
npm install
npm run dev
```

## Docker Deployment

```powershell
# Start all services
cd infrastructure && docker compose up -d
cd ../backend && docker compose up --build -d
cd ../frontend && docker compose up --build -d
```

## API Endpoints

### Ingestion
- `POST /api/ingestion/add` - Add URL (Firecrawl crawl)
- `POST /api/ingestion/add-document` - Upload PDF/image (Docling)
- `GET /api/ingestion/list` - List sources
- `DELETE /api/ingestion/delete/{id}` - Delete source

### Chat
- `POST /api/chat` - Send message
- `POST /api/stream` - Stream response

## Environment Variables

### Backend (.env)
```
DATABASE_URL=postgresql://user:password@pgvector:5432/firecrawl_docling_db
GOOGLE_API_KEY=your_google_api_key
FIRECRAWL_API_KEY=your_firecrawl_api_key
```

### Frontend (.env.local)
```
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```
