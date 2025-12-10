# Heroku Deployment Guide

This guide will help you deploy the WhipSmart Backend Admin application to Heroku.

## Prerequisites

1. Heroku account (sign up at https://heroku.com)
2. Heroku CLI installed (https://devcenter.heroku.com/articles/heroku-cli)
3. Git repository initialized

## Files Created for Heroku

1. **Procfile** - Defines the web process using gunicorn
2. **runtime.txt** - Specifies Python version (3.12.0)
3. **requirements.txt** - Updated with gunicorn and whitenoise

## Deployment Steps

### 1. Login to Heroku

```bash
heroku login
```

### 2. Create Heroku App

```bash
heroku create your-app-name
```

Or let Heroku generate a name:
```bash
heroku create
```

### 3. Add PostgreSQL Database (Recommended)

```bash
heroku addons:create heroku-postgresql:mini
```

This will automatically set the `DATABASE_URL` environment variable.

### 4. Set Environment Variables

Set all required environment variables:

```bash
# Django Secret Key
heroku config:set SECRET_KEY="your-secret-key-here"

# Debug Mode (set to False for production)
heroku config:set DEBUG=False

# Allowed Hosts (use your Heroku app domain)
heroku config:set ALLOWED_HOSTS="your-app-name.herokuapp.com"

# Database URL (automatically set by PostgreSQL addon, but you can verify)
heroku config:get DATABASE_URL

# Add other environment variables as needed
# For example:
heroku config:set OPENAI_API_KEY="your-openai-key"
heroku config:set PINECONE_API_KEY="your-pinecone-key"
# ... etc
```

### 5. Configure Settings for Production

Update `whipsmart_admin/settings.py` to use Heroku's database:

```python
import dj_database_url

# Database configuration
DATABASES = {
    'default': dj_database_url.config(
        default=config('DATABASE_URL', default=''),
        conn_max_age=600,
        conn_health_checks=True,
    )
}
```

Or if you're using `python-decouple`, it should automatically read from environment variables.

### 6. Run Migrations

```bash
heroku run python manage.py migrate
```

### 7. Create Superuser (Optional)

```bash
heroku run python manage.py createsuperuser
```

### 8. Collect Static Files

```bash
heroku run python manage.py collectstatic --noinput
```

### 9. Deploy to Heroku

```bash
git add .
git commit -m "Prepare for Heroku deployment"
git push heroku main
```

Or if you're using `master` branch:
```bash
git push heroku master
```

### 10. Open Your App

```bash
heroku open
```

## Post-Deployment

### View Logs

```bash
heroku logs --tail
```

### Run Django Commands

```bash
heroku run python manage.py <command>
```

### Access Django Shell

```bash
heroku run python manage.py shell
```

### Restart Dynos

```bash
heroku restart
```

## Important Notes

1. **Database**: Heroku uses PostgreSQL. Make sure your `DATABASE_URL` is set correctly.

2. **Static Files**: WhiteNoise middleware is configured to serve static files. Run `collectstatic` after deployment.

3. **Environment Variables**: Never commit sensitive keys. Use Heroku config vars.

4. **Debug Mode**: Always set `DEBUG=False` in production.

5. **Allowed Hosts**: Update `ALLOWED_HOSTS` to include your Heroku domain.

6. **CORS**: Update CORS settings to allow your frontend domain.

## Troubleshooting

### Application Error

Check logs:
```bash
heroku logs --tail
```

### Database Issues

Check database connection:
```bash
heroku pg:info
heroku pg:psql
```

### Static Files Not Loading

Ensure WhiteNoise is in middleware and run:
```bash
heroku run python manage.py collectstatic --noinput
```

### Port Issues

The Procfile uses `$PORT` which Heroku sets automatically. Don't hardcode port numbers.

## Scaling

### Scale Web Dynos

```bash
heroku ps:scale web=1
```

### View Dyno Status

```bash
heroku ps
```

## Additional Resources

- [Heroku Python Support](https://devcenter.heroku.com/articles/python-support)
- [Django on Heroku](https://devcenter.heroku.com/articles/django-app-configuration)
- [Heroku Postgres](https://devcenter.heroku.com/articles/heroku-postgresql)

