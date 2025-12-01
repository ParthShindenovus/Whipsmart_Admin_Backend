# Document Module Implementation - Complete Guide

## Overview

The Document Module has been fully implemented with state management, chunk storage in database, and proper integration with Pinecone vector database. The module follows a clear lifecycle with proper state transitions and validation.

## Document Lifecycle States

1. **Uploaded** - Document file uploaded and stored in media folder
2. **Chunked** - Document text extracted and chunked, chunks stored in database
3. **Processing** - Document is being vectorized (embedding generation and Pinecone upload)
4. **Live** - All chunks are vectorized and stored in Pinecone, ready for queries
5. **RemovedFromVectorDB** - Chunks removed from Pinecone but document and chunks still in database
6. **Deleted** - Document and chunks deleted from database (only allowed when not live in vector DB)

## Database Schema

### Document Model
- `id` (UUID) - Primary key
- `title` - Document title
- `file_url` - URL to document file (media folder)
- `file_type` - Type of file (pdf, txt, docx, html)
- `state` - Current lifecycle state
- `vector_status` - Status of vectorization process (not_started, chunking, embedding, uploading, completed, failed)
- `chunk_count` - Number of chunks created
- `is_vectorized` - Whether document is vectorized
- `vectorized_at` - Timestamp when vectorized
- `vector_id` - Comma-separated list of Pinecone vector IDs
- `upload_idempotency_key` - Idempotency key for upload operations
- `vectorization_idempotency_key` - Idempotency key for vectorization operations
- `uploaded_by` - Foreign key to AdminUser
- `is_active` - Whether document is active
- `created_at`, `updated_at` - Timestamps

### DocumentChunk Model
- `id` (UUID) - Primary key
- `document` - Foreign key to Document
- `chunk_id` - Unique chunk identifier (format: {document_id}-chunk-{index})
- `chunk_index` - Index of chunk in document
- `text` - Text content of chunk
- `text_length` - Length of chunk text
- `is_vectorized` - Whether chunk is vectorized
- `vector_id` - Pinecone vector ID for this chunk
- `vectorized_at` - Timestamp when vectorized
- `metadata` - JSON metadata (document_id, title, file_type, etc.)
- `created_at`, `updated_at` - Timestamps

## API Endpoints

### 1. Upload Document
**POST** `/api/knowledgebase/documents/`

Upload a new document file. Document state is set to `uploaded`.

**Request (multipart/form-data):**
- `file` (required) - Document file
- `title` (optional) - Document title (auto-detected from filename if not provided)
- `file_type` (optional) - File type (auto-detected from extension if not provided)
- `upload_idempotency_key` (optional) - Idempotency key to prevent duplicate uploads

**Response:**
```json
{
  "id": "uuid",
  "title": "Document Title",
  "file_url": "http://...",
  "file_type": "pdf",
  "state": "uploaded",
  "vector_status": "not_started",
  "chunk_count": 0,
  ...
}
```

### 2. Chunk Document
**POST** `/api/knowledgebase/documents/{id}/chunk/`

Process document and create chunks stored in database. Document state changes to `chunked`.

**Request:**
```json
{
  "vectorization_idempotency_key": "optional-key"
}
```

**Response:**
```json
{
  "success": true,
  "chunks_created": 15,
  "message": "Document chunked successfully. 15 chunks created."
}
```

### 3. Vectorize Document
**POST** `/api/knowledgebase/documents/{id}/vectorize/`

Vectorize document chunks and upload to Pinecone. Document must be in `chunked` state. Uses chunks from database. Document state changes to `processing` → `live`.

**Request:**
```json
{
  "vectorization_idempotency_key": "optional-key"
}
```

**Response:**
```json
{
  "success": true,
  "chunks_created": 15,
  "vectors_uploaded": 15,
  "message": "Document vectorized successfully. 15 vectors uploaded to Pinecone."
}
```

### 4. Remove from Vector DB
**POST** `/api/knowledgebase/documents/{id}/remove-from-vectordb/`

Remove all chunks of a document from Pinecone. Document must be in `live` state. Document state changes to `removed_from_vectordb`.

**Response:**
```json
{
  "success": true,
  "message": "Document removed from vector database successfully"
}
```

### 5. Delete Document
**DELETE** `/api/knowledgebase/documents/{id}/`

Delete document. Only allowed when document is NOT live in vector DB (state must be `removed_from_vectordb`, `uploaded`, `chunked`, or `processing`).

**Response:**
- 204 No Content (success)
- 403 Forbidden (if document is live in vector DB)

### 6. Download Document
**GET** `/api/knowledgebase/documents/{id}/download/`

Download document file. Returns file with appropriate content type for download.

**Response:**
- File download with `Content-Disposition: attachment`

### 7. View Document
**GET** `/api/knowledgebase/documents/{id}/view/`

View document file in browser. Returns file with appropriate content type for inline viewing.

**Response:**
- File view with `Content-Disposition: inline`

### 8. List Documents
**GET** `/api/knowledgebase/documents/`

List all documents. Supports filtering and pagination.

**Query Parameters:**
- `include_chunks=true` - Include chunks in response
- `file_type` - Filter by file type
- `is_active` - Filter by active status
- `state` - Filter by state
- `search` - Search in title and file_type

### 9. Get Document Details
**GET** `/api/knowledgebase/documents/{id}/`

Get document details. Include chunks with `?include_chunks=true`.

### 10. Search Documents (RAG)
**POST** `/api/knowledgebase/documents/search/`

Search documents using vector similarity search.

**Request:**
```json
{
  "query": "search query",
  "top_k": 5,
  "document_id": "optional-document-id"
}
```

**Response:**
```json
{
  "success": true,
  "query": "search query",
  "results": [
    {
      "text": "chunk text",
      "url": "document url",
      "score": 0.95,
      "document_id": "uuid",
      "document_title": "Document Title"
    }
  ]
}
```

## Workflow Examples

### Complete Workflow
1. **Upload** → `POST /api/knowledgebase/documents/` → state: `uploaded`
2. **Chunk** → `POST /api/knowledgebase/documents/{id}/chunk/` → state: `chunked`
3. **Vectorize** → `POST /api/knowledgebase/documents/{id}/vectorize/` → state: `live`
4. **Remove from Vector DB** → `POST /api/knowledgebase/documents/{id}/remove-from-vectordb/` → state: `removed_from_vectordb`
5. **Delete** → `DELETE /api/knowledgebase/documents/{id}/` → document deleted

### Direct Vectorization (Auto-chunking)
If you call `vectorize` on an `uploaded` document, it will automatically chunk the document first, then vectorize.

## Important Rules

1. **Deletion Rule**: Document can only be deleted when state is `removed_from_vectordb`, `uploaded`, `chunked`, or `processing` (not when `live`).

2. **Idempotency**: Use `upload_idempotency_key` and `vectorization_idempotency_key` to prevent duplicate operations.

3. **Chunk IDs**: Each chunk has a unique ID format: `{document_id}-chunk-{index}`. All chunks of a document share the same `document_id` in metadata.

4. **State Transitions**:
   - `uploaded` → `chunked` (via chunk endpoint)
   - `chunked` → `processing` → `live` (via vectorize endpoint)
   - `live` → `removed_from_vectordb` (via remove-from-vectordb endpoint)
   - Any state → `deleted` (via delete endpoint, if allowed)

5. **Vector Status**: Tracks the progress of vectorization:
   - `not_started` → `embedding` → `uploading` → `completed`
   - Or `failed` if error occurs

## File Storage

- Files are stored in `media/documents/{year}/{month}/{day}/{filename}`
- Files are accessible via `file_url` field
- Download endpoint returns file with proper content type
- View endpoint returns file for inline browser viewing

## Pinecone Integration

- Chunks are uploaded to Pinecone with metadata containing `document_id`
- All chunks of a document can be deleted by `document_id` pattern
- Vector IDs follow pattern: `{document_id}-chunk-{index}`
- Chunk metadata includes: `document_id`, `document_title`, `chunk_index`, `file_type`, `file_name`, `url`, `text` (first 2000 chars)

## Error Handling

- All endpoints return appropriate HTTP status codes
- Error responses include descriptive messages
- State validation prevents invalid operations
- Idempotency keys prevent duplicate operations

## Testing

To test the implementation:

1. Upload a document
2. Check state is `uploaded`
3. Chunk the document
4. Check state is `chunked` and chunks are in database
5. Vectorize the document
6. Check state is `live` and chunks are vectorized
7. Test search functionality
8. Remove from vector DB
9. Check state is `removed_from_vectordb`
10. Delete document
11. Verify document is deleted

## Migration

The migration has been created and applied:
- `0010_documentchunk_document_chunk_count_document_state_and_more.py`

This migration:
- Creates `DocumentChunk` model
- Adds state management fields to `Document`
- Adds chunk tracking fields
- Adds idempotency key fields
- Creates necessary indexes

