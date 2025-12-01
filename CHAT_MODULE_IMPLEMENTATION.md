# Chat Module Implementation - Complete Guide

## Overview

The Chat Module provides complete chat functionality with session management and message storage. All endpoints work without requiring user_id, making them perfect for landing page integrations.

## Key Features

✅ **No User ID Required** - All endpoints work without authentication or user_id  
✅ **Session Management** - Full CRUD operations for chat sessions  
✅ **Permanent Message Storage** - All messages are permanently stored in database  
✅ **Session ID Always Required** - All message operations require session_id  
✅ **Non-Streaming Chat** - Complete response in one request  
✅ **Streaming Chat (SSE)** - Server-Sent Events for real-time streaming responses  

## API Endpoints

### 1. Session APIs

#### Create Session
**POST** `/api/chats/sessions/`

Create a new chat session. Session ID is auto-generated if not provided.

**Request:**
```json
{
  "session_id": "optional-custom-session-id",  // Optional, auto-generated if not provided
  "external_user_id": "optional-user-id",       // Optional, for third-party integration
  "metadata": {},                                // Optional, device info, etc.
  "expires_at": "2024-01-02T12:00:00Z"         // Optional, defaults to 24h from now
}
```

**Response:**
```json
{
  "id": "uuid",
  "session_id": "generated-or-provided-session-id",
  "external_user_id": "optional-user-id",
  "created_at": "2024-01-01T12:00:00Z",
  "expires_at": "2024-01-02T12:00:00Z",
  "is_active": true,
  "metadata": {}
}
```

#### Read Session
**GET** `/api/chats/sessions/{id}/`

Get session details by ID.

#### List Sessions
**GET** `/api/chats/sessions/`

List all sessions. Supports filtering:
- `?is_active=true` - Filter by active status
- `?external_user_id=user123` - Filter by external user ID
- `?search=session-id` - Search by session_id or external_user_id

#### Delete Session
**DELETE** `/api/chats/sessions/{id}/`

Delete a session and all associated messages.

### 2. Message APIs

#### List Messages
**GET** `/api/chats/messages/?session_id={session_id}`

**Important**: `session_id` query parameter is REQUIRED.

List all messages for a session. Supports filtering:
- `?session_id=xxx` - **REQUIRED** - Filter by session ID
- `?role=user` - Filter by role (user, assistant, system)
- `?search=keyword` - Search in message content

**Response:**
```json
[
  {
    "id": "uuid",
    "session": {...},
    "message": "Hello",
    "role": "user",
    "metadata": {},
    "timestamp": "2024-01-01T12:00:00Z"
  },
  ...
]
```

#### Create Message
**POST** `/api/chats/messages/`

Create a new message. **session_id is REQUIRED**.

**Request:**
```json
{
  "session_id": "session-id-here",  // REQUIRED
  "message": "Hello, how are you?",
  "role": "user",                    // user, assistant, or system
  "metadata": {}                     // Optional, RAG sources, etc.
}
```

**Response:**
```json
{
  "id": "uuid",
  "session": {...},
  "message": "Hello, how are you?",
  "role": "user",
  "metadata": {},
  "timestamp": "2024-01-01T12:00:00Z"
}
```

#### Get Message
**GET** `/api/chats/messages/{id}/`

Get message details by ID.

#### Delete Message (Soft Delete)
**DELETE** `/api/chats/messages/{id}/`

Soft delete a message (sets is_deleted flag).

### 3. Chat APIs

#### Non-Streaming Chat
**POST** `/api/chats/messages/chat/`

Send a message and receive complete response. Both messages are permanently stored.

**Request:**
```json
{
  "message": "Hello, how are you?",
  "session_id": "session-id-here"  // REQUIRED
}
```

**Response:**
```json
{
  "response": "I'm doing well, thank you! How can I help you?",
  "session_id": "session-id-here",
  "message_id": "user-message-uuid",
  "response_id": "assistant-message-uuid"
}
```

**Features:**
- ✅ session_id is REQUIRED
- ✅ User message is permanently stored
- ✅ Assistant response is permanently stored
- ✅ Complete response returned in one request
- ✅ No user_id needed

#### Streaming Chat (SSE)
**POST** `/api/chats/messages/chat/stream/`

Send a message and receive streaming response via Server-Sent Events (SSE).

**Request:**
```json
{
  "message": "Tell me a story",
  "session_id": "session-id-here"  // REQUIRED
}
```

**Response:** (Streaming via SSE)
```
Content-Type: text/event-stream

data: {"chunk": "Once", "done": false, "message_id": "uuid"}

data: {"chunk": "upon", "done": false, "message_id": "uuid"}

data: {"chunk": "a", "done": false, "message_id": "uuid"}

data: {"chunk": "time...", "done": false, "message_id": "uuid"}

data: {"chunk": "", "done": true, "message_id": "uuid", "response_id": "uuid"}

```

**Client Example (JavaScript):**
```javascript
const eventSource = new EventSource('/api/chats/messages/chat/stream/', {
  method: 'POST',
  body: JSON.stringify({
    message: 'Tell me a story',
    session_id: 'session-id-here'
  })
});

eventSource.onmessage = function(event) {
  const data = JSON.parse(event.data);
  if (data.done) {
    console.log('Stream complete. Response ID:', data.response_id);
    eventSource.close();
  } else {
    console.log('Chunk:', data.chunk);
    // Append chunk to UI
  }
};
```

**Features:**
- ✅ session_id is REQUIRED
- ✅ User message is permanently stored
- ✅ Assistant response is permanently stored (after stream completes)
- ✅ Real-time streaming via SSE
- ✅ No user_id needed

## Complete Workflow Example

### 1. Create Session
```bash
POST /api/chats/sessions/
{
  "metadata": {"device": "web", "browser": "Chrome"}
}

Response: {
  "id": "session-uuid",
  "session_id": "auto-generated-session-id",
  ...
}
```

### 2. Send Non-Streaming Message
```bash
POST /api/chats/messages/chat/
{
  "message": "What is AI?",
  "session_id": "auto-generated-session-id"
}

Response: {
  "response": "AI stands for Artificial Intelligence...",
  "session_id": "auto-generated-session-id",
  "message_id": "user-msg-uuid",
  "response_id": "assistant-msg-uuid"
}
```

### 3. Send Streaming Message
```bash
POST /api/chats/messages/chat/stream/
{
  "message": "Tell me a joke",
  "session_id": "auto-generated-session-id"
}

Response: (SSE stream)
data: {"chunk": "Why", "done": false, ...}
data: {"chunk": " did", "done": false, ...}
...
```

### 4. Get All Messages for Session
```bash
GET /api/chats/messages/?session_id=auto-generated-session-id

Response: [
  {
    "id": "user-msg-uuid",
    "message": "What is AI?",
    "role": "user",
    ...
  },
  {
    "id": "assistant-msg-uuid",
    "message": "AI stands for Artificial Intelligence...",
    "role": "assistant",
    ...
  }
]
```

### 5. Delete Session
```bash
DELETE /api/chats/sessions/session-uuid/
```

## Important Notes

### Session ID Requirements
- ✅ **session_id is ALWAYS required** for all message operations
- ✅ Can be provided as UUID or session_id string
- ✅ Session must exist before creating messages

### No User ID Required
- ✅ All endpoints work without authentication
- ✅ No user_id required for any operation
- ✅ Perfect for landing page integrations
- ✅ `external_user_id` is optional for third-party tracking

### Permanent Storage
- ✅ All messages are permanently stored in database
- ✅ Messages are never automatically deleted
- ✅ Soft delete available (sets is_deleted flag)
- ✅ Messages are tied to session via ForeignKey

### Message Roles
- `user` - User messages
- `assistant` - AI/Assistant responses
- `system` - System messages

## Integration Tips

### For Landing Pages
1. Create session on page load (optional, can create on first message)
2. Store session_id in localStorage or sessionStorage
3. Use session_id for all chat operations
4. No need to track user_id

### For Third-Party Integration
1. Use `external_user_id` to track your own user IDs
2. All operations still work without external_user_id
3. Filter sessions by `external_user_id` if needed

### Error Handling
- **400 Bad Request**: Missing required fields (message, session_id)
- **404 Not Found**: Session not found
- **500 Internal Server Error**: Server error

## Next Steps

To integrate with your AI service:

1. **Update Non-Streaming Chat** (`chat` method in `ChatMessageViewSet`):
   - Replace placeholder `assistant_response_text = f"Echo: {message}"`
   - Integrate with your LLM/AI service
   - Return complete response

2. **Update Streaming Chat** (`chat_stream` method in `ChatMessageViewSet`):
   - Replace placeholder streaming logic
   - Integrate with your streaming LLM/AI service
   - Yield chunks as they arrive

3. **Add RAG Integration** (Optional):
   - Use knowledgebase search in chat endpoints
   - Include RAG sources in message metadata
   - Enhance responses with document context

## Database Schema

### Session Model
- `id` (UUID) - Primary key
- `session_id` (String) - Unique session identifier
- `external_user_id` (String, optional) - Third-party user ID
- `created_at` (DateTime) - Creation timestamp
- `expires_at` (DateTime) - Expiration time (default: 24h)
- `is_active` (Boolean) - Active status
- `metadata` (JSON) - Additional data

### ChatMessage Model
- `id` (UUID) - Primary key
- `session` (ForeignKey) - **REQUIRED** - Links to Session
- `message` (Text) - Message content
- `role` (String) - user, assistant, or system
- `metadata` (JSON) - RAG sources, etc.
- `timestamp` (DateTime) - Message timestamp
- `is_deleted` (Boolean) - Soft delete flag

## Security Notes

- All endpoints are public (AllowAny)
- No authentication required
- Perfect for public landing pages
- Consider rate limiting for production
- Session expiration prevents indefinite storage

