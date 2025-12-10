# Frontend Chat Widget - Quick Reference

## 🚀 Quick Start Flow

```
1. Widget Loads → Check localStorage for visitor_id
   ↓
2. If exists → Validate it
   ↓
3. If invalid/missing → Create new visitor
   ↓
4. User clicks "+" → Create session with visitor_id
   ↓
5. User sends message → Chat with visitor_id + session_id
```

---

## 📋 API Endpoints

### 1. Create Visitor
```http
POST /api/chats/visitors/
Content-Type: application/json

{}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "id": "visitor-uuid",
    "created_at": "2025-12-09T12:00:00Z",
    "last_seen_at": "2025-12-09T12:00:00Z"
  }
}
```

---

### 2. Validate Visitor
```http
GET /api/chats/visitors/{visitor_id}/validate/
```

**Success (200):**
```json
{
  "success": true,
  "data": { "id": "visitor-uuid", ... },
  "message": "Visitor ID is valid"
}
```

**Error (404):**
```json
{
  "success": false,
  "message": "Visitor with ID '...' does not exist..."
}
```

---

### 3. Create Session
```http
POST /api/chats/sessions/
Content-Type: application/json

{
  "visitor_id": "visitor-uuid"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "id": "session-uuid",
    "visitor": { "id": "visitor-uuid" },
    "is_active": true
  }
}
```

---

### 4. Send Chat Message
```http
POST /api/chats/messages/chat/
Content-Type: application/json
X-API-Key: your-api-key

{
  "message": "Hello",
  "session_id": "session-uuid",
  "visitor_id": "visitor-uuid"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "response": "Hello! How can I help?",
    "session_id": "session-uuid",
    "message_id": "msg-uuid",
    "response_id": "resp-uuid"
  }
}
```

---

## 💻 JavaScript Code Snippets

### Initialize Visitor (On Widget Load)
```javascript
async function initVisitor() {
  let visitorId = localStorage.getItem('whipsmart_visitor_id');
  
  if (visitorId) {
    const response = await fetch(`${API_URL}/api/chats/visitors/${visitorId}/validate/`);
    if (response.ok) return visitorId;
    localStorage.removeItem('whipsmart_visitor_id');
  }
  
  const response = await fetch(`${API_URL}/api/chats/visitors/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({})
  });
  
  const data = await response.json();
  visitorId = data.data.id;
  localStorage.setItem('whipsmart_visitor_id', visitorId);
  return visitorId;
}
```

### Create Session (New Chat)
```javascript
async function createSession(visitorId) {
  const response = await fetch(`${API_URL}/api/chats/sessions/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ visitor_id: visitorId })
  });
  
  const data = await response.json();
  return data.data.id; // session_id
}
```

### Send Message
```javascript
async function sendMessage(visitorId, sessionId, message) {
  const response = await fetch(`${API_URL}/api/chats/messages/chat/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': API_KEY
    },
    body: JSON.stringify({
      message: message,
      session_id: sessionId,
      visitor_id: visitorId
    })
  });
  
  const data = await response.json();
  return data.data.response;
}
```

---

## ⚠️ Important Notes

1. **visitor_id** is stored in `localStorage` (persists across sessions)
2. **session_id** is stored in component state (new for each chat)
3. **API Key** is required only for `/chat` endpoints
4. **visitor_id** is REQUIRED for all session and chat operations
5. Always validate visitor before creating sessions

---

## 🐛 Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `Visitor with ID '...' does not exist` | Invalid visitor_id | Create new visitor |
| `visitor_id is required` | Missing visitor_id | Initialize visitor first |
| `Visitor ID '...' does not match session's visitor` | Wrong visitor_id | Use correct visitor_id for session |
| `Session not found` | Invalid session_id | Create new session |

---

## 📚 Full Documentation

See `FRONTEND_CHAT_IMPLEMENTATION_GUIDE.md` for complete implementation details.


