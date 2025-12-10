# Frontend Chat Widget Implementation Guide

## Overview

This guide explains how to implement the WhipSmart Chat Widget with the visitor-based session management system. The widget uses a 3-step flow: **Visitor → Session → Chat**.

---

## API Flow Summary

```
1. Create/Validate Visitor (on widget load)
   ↓
2. Create Session (when user starts new chat)
   ↓
3. Send Chat Messages (with visitor_id + session_id)
```

---

## Step-by-Step Implementation

### Step 1: Initialize Visitor (Widget Load)

**Goal**: Ensure a valid `visitor_id` exists before allowing any chat functionality.

#### Flow Logic:

```javascript
// On widget load
async function initializeVisitor() {
  // 1. Check if visitor_id exists in localStorage
  let visitorId = localStorage.getItem('whipsmart_visitor_id');
  
  if (visitorId) {
    // 2. Validate existing visitor_id
    const isValid = await validateVisitor(visitorId);
    
    if (isValid) {
      // Visitor is valid, continue with existing visitor_id
      return visitorId;
    } else {
      // Visitor is invalid, remove from localStorage
      localStorage.removeItem('whipsmart_visitor_id');
      visitorId = null;
    }
  }
  
  // 3. Create new visitor if none exists or validation failed
  if (!visitorId) {
    visitorId = await createVisitor();
    localStorage.setItem('whipsmart_visitor_id', visitorId);
  }
  
  return visitorId;
}
```

#### API Endpoints:

**Validate Visitor:**
```http
GET /api/chats/visitors/{visitor_id}/validate/
```

**Response (200 OK):**
```json
{
  "success": true,
  "data": {
    "id": "uuid-here",
    "created_at": "2025-12-09T12:00:00Z",
    "last_seen_at": "2025-12-09T12:00:00Z",
    "metadata": {}
  },
  "message": "Visitor ID is valid"
}
```

**Response (404 Not Found):**
```json
{
  "success": false,
  "message": "Visitor with ID 'uuid-here' does not exist. Please create a visitor first via POST /api/chats/visitors/"
}
```

**Create Visitor:**
```http
POST /api/chats/visitors/
Content-Type: application/json

{}
```

**Response (201 Created):**
```json
{
  "success": true,
  "data": {
    "id": "new-visitor-uuid",
    "created_at": "2025-12-09T12:00:00Z",
    "last_seen_at": "2025-12-09T12:00:00Z",
    "metadata": {}
  },
  "message": "Visitor created successfully. Use this visitor_id to create sessions and send chat messages."
}
```

#### JavaScript Implementation:

```javascript
// API Base URL (from widget config)
const API_BASE_URL = 'http://localhost:8000'; // or your API URL

/**
 * Validate if a visitor ID exists and is valid
 */
async function validateVisitor(visitorId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/chats/visitors/${visitorId}/validate/`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });
    
    if (response.ok) {
      const data = await response.json();
      return data.success === true;
    }
    
    return false;
  } catch (error) {
    console.error('Error validating visitor:', error);
    return false;
  }
}

/**
 * Create a new visitor
 */
async function createVisitor() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/chats/visitors/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({}),
    });
    
    if (!response.ok) {
      throw new Error(`Failed to create visitor: ${response.statusText}`);
    }
    
    const data = await response.json();
    
    if (data.success && data.data && data.data.id) {
      return data.data.id;
    }
    
    throw new Error('Invalid response from create visitor endpoint');
  } catch (error) {
    console.error('Error creating visitor:', error);
    throw error;
  }
}
```

---

### Step 2: Create Session (New Chat)

**Goal**: Create a new chat session when user clicks "+" button or starts a new conversation.

#### Flow Logic:

```javascript
// When user clicks "+" or starts new chat
async function startNewChat(visitorId) {
  // 1. Create session with visitor_id
  const sessionId = await createSession(visitorId);
  
  // 2. Store session_id for this chat
  // (You can store in component state, sessionStorage, or state management)
  return sessionId;
}
```

#### API Endpoint:

**Create Session:**
```http
POST /api/chats/sessions/
Content-Type: application/json

{
  "visitor_id": "visitor-uuid-here"
}
```

**Response (201 Created):**
```json
{
  "success": true,
  "data": {
    "id": "session-uuid-here",
    "visitor": {
      "id": "visitor-uuid-here",
      "created_at": "2025-12-09T12:00:00Z",
      "last_seen_at": "2025-12-09T12:00:00Z"
    },
    "external_user_id": null,
    "created_at": "2025-12-09T12:00:00Z",
    "expires_at": "2025-12-10T12:00:00Z",
    "is_active": true,
    "metadata": {}
  },
  "message": "Created successfully"
}
```

**Error Response (400 Bad Request):**
```json
{
  "success": false,
  "message": "Visitor with ID 'invalid-uuid' does not exist. Please create a visitor first via POST /api/chats/visitors/"
}
```

#### JavaScript Implementation:

```javascript
/**
 * Create a new chat session
 */
async function createSession(visitorId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/chats/sessions/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        visitor_id: visitorId,
      }),
    });
    
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.message || `Failed to create session: ${response.statusText}`);
    }
    
    const data = await response.json();
    
    if (data.success && data.data && data.data.id) {
      return data.data.id;
    }
    
    throw new Error('Invalid response from create session endpoint');
  } catch (error) {
    console.error('Error creating session:', error);
    throw error;
  }
}
```

---

### Step 3: Send Chat Messages

**Goal**: Send user messages and receive assistant responses using both `visitor_id` and `session_id`.

#### Flow Logic:

```javascript
// When user sends a message
async function sendMessage(visitorId, sessionId, message) {
  // Send chat request with visitor_id, session_id, and message
  const response = await sendChatMessage(visitorId, sessionId, message);
  return response;
}
```

#### API Endpoints:

**Non-Streaming Chat:**
```http
POST /api/chats/messages/chat/
Content-Type: application/json
X-API-Key: your-api-key-here

{
  "message": "Hello, how can you help me?",
  "session_id": "session-uuid-here",
  "visitor_id": "visitor-uuid-here"
}
```

**Response (200 OK):**
```json
{
  "success": true,
  "data": {
    "response": "Hello! I'm here to help you. How can I assist you today?",
    "session_id": "session-uuid-here",
    "message_id": "message-uuid-here",
    "response_id": "response-uuid-here"
  }
}
```

**Streaming Chat (SSE):**
```http
POST /api/chats/messages/chat/stream/
Content-Type: application/json
X-API-Key: your-api-key-here

{
  "message": "Hello, how can you help me?",
  "session_id": "session-uuid-here",
  "visitor_id": "visitor-uuid-here"
}
```

**Response (200 OK - Event Stream):**
```
data: {"chunk": "Hello", "done": false}

data: {"chunk": "! I'm", "done": false}

data: {"chunk": " here to help.", "done": true}

```

#### JavaScript Implementation:

```javascript
// API Key from widget config
const API_KEY = 'your-api-key-here';

/**
 * Send non-streaming chat message
 */
async function sendChatMessage(visitorId, sessionId, message) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/chats/messages/chat/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': API_KEY, // or Authorization: Bearer ${API_KEY}
      },
      body: JSON.stringify({
        message: message,
        session_id: sessionId,
        visitor_id: visitorId,
      }),
    });
    
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.message || `Failed to send message: ${response.statusText}`);
    }
    
    const data = await response.json();
    
    if (data.success && data.data) {
      return data.data.response;
    }
    
    throw new Error('Invalid response from chat endpoint');
  } catch (error) {
    console.error('Error sending chat message:', error);
    throw error;
  }
}

/**
 * Send streaming chat message (Server-Sent Events)
 */
async function sendChatMessageStream(visitorId, sessionId, message, onChunk) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/chats/messages/chat/stream/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': API_KEY,
      },
      body: JSON.stringify({
        message: message,
        session_id: sessionId,
        visitor_id: visitorId,
      }),
    });
    
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.message || `Failed to send message: ${response.statusText}`);
    }
    
    // Read SSE stream
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    
    while (true) {
      const { done, value } = await reader.read();
      
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';
      
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const jsonStr = line.slice(6);
          try {
            const chunk = JSON.parse(jsonStr);
            onChunk(chunk);
            
            if (chunk.done) {
              return;
            }
          } catch (e) {
            console.error('Error parsing SSE chunk:', e);
          }
        }
      }
    }
  } catch (error) {
    console.error('Error sending streaming chat message:', error);
    throw error;
  }
}
```

---

## Complete Widget Implementation Example

### React Component Example:

```javascript
import React, { useState, useEffect } from 'react';

const ChatWidget = ({ apiKey, apiUrl }) => {
  const [visitorId, setVisitorId] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [initializing, setInitializing] = useState(true);

  // Step 1: Initialize visitor on component mount
  useEffect(() => {
    initializeVisitor();
  }, []);

  const initializeVisitor = async () => {
    try {
      // Check localStorage
      let storedVisitorId = localStorage.getItem('whipsmart_visitor_id');
      
      if (storedVisitorId) {
        // Validate existing visitor
        const isValid = await validateVisitor(storedVisitorId);
        if (isValid) {
          setVisitorId(storedVisitorId);
          setInitializing(false);
          return;
        } else {
          localStorage.removeItem('whipsmart_visitor_id');
        }
      }
      
      // Create new visitor
      const newVisitorId = await createVisitor();
      localStorage.setItem('whipsmart_visitor_id', newVisitorId);
      setVisitorId(newVisitorId);
    } catch (error) {
      console.error('Failed to initialize visitor:', error);
    } finally {
      setInitializing(false);
    }
  };

  // Step 2: Start new chat (when user clicks "+" button)
  const handleNewChat = async () => {
    if (!visitorId) {
      console.error('Visitor ID not initialized');
      return;
    }
    
    try {
      setLoading(true);
      const newSessionId = await createSession(visitorId);
      setSessionId(newSessionId);
      setMessages([]);
    } catch (error) {
      console.error('Failed to create session:', error);
      alert('Failed to start new chat. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  // Step 3: Send message
  const handleSendMessage = async () => {
    if (!inputMessage.trim() || !visitorId || !sessionId) {
      return;
    }
    
    const userMessage = inputMessage.trim();
    setInputMessage('');
    
    // Add user message to UI
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    
    try {
      setLoading(true);
      
      // Send message and get response
      const response = await sendChatMessage(visitorId, sessionId, userMessage);
      
      // Add assistant response to UI
      setMessages(prev => [...prev, { role: 'assistant', content: response }]);
    } catch (error) {
      console.error('Failed to send message:', error);
      alert('Failed to send message. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  if (initializing) {
    return <div>Initializing chat...</div>;
  }

  return (
    <div className="chat-widget">
      <div className="chat-header">
        <button onClick={handleNewChat} disabled={loading}>
          + New Chat
        </button>
      </div>
      
      <div className="chat-messages">
        {messages.map((msg, idx) => (
          <div key={idx} className={`message ${msg.role}`}>
            {msg.content}
          </div>
        ))}
      </div>
      
      <div className="chat-input">
        <input
          type="text"
          value={inputMessage}
          onChange={(e) => setInputMessage(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
          placeholder="Type your message..."
          disabled={!sessionId || loading}
        />
        <button onClick={handleSendMessage} disabled={!sessionId || loading}>
          Send
        </button>
      </div>
    </div>
  );
};

export default ChatWidget;
```

---

## Error Handling

### Common Errors and Solutions:

1. **Visitor Not Found (404)**
   - **Cause**: Visitor ID doesn't exist
   - **Solution**: Create a new visitor and update localStorage

2. **Session Creation Failed (400)**
   - **Cause**: Invalid visitor_id
   - **Solution**: Re-initialize visitor

3. **Chat Message Failed (403)**
   - **Cause**: Visitor ID doesn't match session's visitor
   - **Solution**: Ensure you're using the correct visitor_id for the session

4. **Chat Message Failed (404)**
   - **Cause**: Session or visitor not found
   - **Solution**: Re-create session with valid visitor_id

### Error Handling Helper:

```javascript
async function handleApiError(response) {
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    const errorMessage = errorData.message || `HTTP ${response.status}: ${response.statusText}`;
    
    // Handle specific error cases
    if (response.status === 404 && errorMessage.includes('Visitor')) {
      // Visitor not found - clear localStorage and reinitialize
      localStorage.removeItem('whipsmart_visitor_id');
      throw new Error('Visitor not found. Please refresh the page.');
    }
    
    throw new Error(errorMessage);
  }
  
  return response;
}
```

---

## API Reference Summary

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/chats/visitors/` | POST | None | Create new visitor |
| `/api/chats/visitors/{id}/validate/` | GET | None | Validate visitor exists |
| `/api/chats/sessions/` | POST | None | Create new session (requires visitor_id) |
| `/api/chats/messages/chat/` | POST | API Key | Send non-streaming chat message |
| `/api/chats/messages/chat/stream/` | POST | API Key | Send streaming chat message (SSE) |

---

## Testing Checklist

- [ ] Widget loads and creates visitor_id automatically
- [ ] Existing visitor_id in localStorage is validated on load
- [ ] Invalid visitor_id is cleared and new one is created
- [ ] New chat creates session with visitor_id
- [ ] Chat messages include both visitor_id and session_id
- [ ] Error handling works for all failure cases
- [ ] Multiple chats can be created with same visitor_id
- [ ] Session persists across page refreshes (if stored)

---

## Notes

1. **Visitor Persistence**: Store `visitor_id` in `localStorage` to persist across page refreshes
2. **Session Management**: Store `session_id` in component state or sessionStorage (not localStorage) for per-chat sessions
3. **API Key**: Required only for chat endpoints (`/chat` and `/chat/stream`), not for visitor/session creation
4. **Error Recovery**: Always validate visitor before creating sessions, and handle errors gracefully

---

## Support

For issues or questions, refer to the Swagger UI documentation at `/api/docs/` for detailed API specifications.


