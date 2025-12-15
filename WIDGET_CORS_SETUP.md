# Widget CORS Configuration Guide

## Problem
When loading `widget-loader.js` from `http://chatbot-widget.novuscode.in/widget-loader.js` in a frontend application (e.g., `http://localhost:5173`), the browser blocks it with:

```
Access to script at 'http://chatbot-widget.novuscode.in/widget-loader.js?v=2'
from origin 'http://localhost:5173' has been blocked by CORS policy:
No 'Access-Control-Allow-Origin' header is present on the requested resource.
```

## Solution

The server hosting `chatbot-widget.novuscode.in` needs to return CORS headers for JavaScript files.

### Option 1: Serve widget-loader.js from this Django backend (Recommended)

This Django backend now includes a view that serves `widget-loader.js` with proper CORS headers.

**URL:** `/api/v1/widget/widget-loader.js`

**Features:**
- ✅ Proper CORS headers (`Access-Control-Allow-Origin: *`)
- ✅ Handles OPTIONS preflight requests
- ✅ Public access (no authentication required)
- ✅ Cache control headers

**To use:**
1. Place your `widget-loader.js` file in one of these locations:
   - `staticfiles/widget-loader.js` (after running `python manage.py collectstatic`)
   - `static/widget/widget-loader.js` (in your project root)

2. Update your embed code to use:
   ```html
   <script src="https://your-django-backend.com/api/v1/widget/widget-loader.js" 
           data-api-key="your-api-key" 
           data-api-url="https://your-api-url.com" 
           data-widget-url="https://your-widget-url.com">
   </script>
   ```

### Option 2: Configure CORS on the widget server (chatbot-widget.novuscode.in)

If you're hosting the widget script on a separate server (`chatbot-widget.novuscode.in`), you need to configure CORS headers on that server.

#### For Django servers:
1. Install `django-cors-headers`:
   ```bash
   pip install django-cors-headers
   ```

2. Add to `settings.py`:
   ```python
   INSTALLED_APPS = [
       ...
       'corsheaders',
   ]
   
   MIDDLEWARE = [
       ...
       'corsheaders.middleware.CorsMiddleware',  # Should be early
       ...
   ]
   
   # Allow all origins (or specify specific ones)
   CORS_ALLOW_ALL_ORIGINS = True
   
   # Or specify allowed origins:
   # CORS_ALLOWED_ORIGINS = [
   #     "http://localhost:5173",
   #     "https://your-production-domain.com",
   # ]
   ```

#### For Nginx:
Add to your nginx configuration:
```nginx
location /widget-loader.js {
    add_header 'Access-Control-Allow-Origin' '*' always;
    add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS' always;
    add_header 'Access-Control-Allow-Headers' 'Content-Type, Origin, Accept' always;
    
    if ($request_method = 'OPTIONS') {
        return 204;
    }
    
    # Your existing proxy_pass or root directive
}
```

#### For Apache:
Add to your `.htaccess` or Apache config:
```apache
<FilesMatch "\.(js|css)$">
    Header set Access-Control-Allow-Origin "*"
    Header set Access-Control-Allow-Methods "GET, POST, OPTIONS"
    Header set Access-Control-Allow-Headers "Content-Type, Origin, Accept"
</FilesMatch>
```

#### For CDN/Static Hosting (Cloudflare, AWS S3, etc.):
- **Cloudflare**: Use Page Rules or Workers to add CORS headers
- **AWS S3**: Configure CORS on the bucket:
  ```json
  [
      {
          "AllowedHeaders": ["*"],
          "AllowedMethods": ["GET", "HEAD"],
          "AllowedOrigins": ["*"],
          "ExposeHeaders": []
      }
  ]
  ```
- **Vercel/Netlify**: Add `_headers` file:
  ```
  /widget-loader.js
    Access-Control-Allow-Origin: *
    Access-Control-Allow-Methods: GET, POST, OPTIONS
    Access-Control-Allow-Headers: Content-Type, Origin, Accept
  ```

### Required CORS Headers

The server must return these headers for GET requests to JavaScript files:

```
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, OPTIONS
Access-Control-Allow-Headers: Content-Type, Origin, Accept
```

**Note:** For production, consider replacing `*` with specific allowed origins for better security:
```
Access-Control-Allow-Origin: http://localhost:5173
Access-Control-Allow-Origin: https://your-production-domain.com
```

### Testing

After configuring CORS, test by:
1. Opening browser DevTools (F12)
2. Going to Network tab
3. Loading a page that includes the widget script
4. Check the `widget-loader.js` request - it should have status 200 and include CORS headers in the response

### Current Django Backend CORS Configuration

This Django backend already has CORS configured:
- `CORS_ALLOW_ALL_ORIGINS = True` (allows all origins)
- `CORS_ALLOW_METHODS` includes GET, POST, OPTIONS
- `CORS_ALLOW_HEADERS` includes necessary headers
- Widget endpoints are publicly accessible

The new `/api/v1/widget/widget-loader.js` endpoint serves the widget script with explicit CORS headers.

