# Generated migration to populate visitors for existing sessions

from django.db import migrations
import uuid


def populate_visitors_for_sessions(apps, schema_editor):
    """
    Create a visitor for each existing session that doesn't have one.
    """
    Session = apps.get_model('chats', 'Session')
    Visitor = apps.get_model('chats', 'Visitor')
    
    # Get all sessions without a visitor
    sessions_without_visitor = Session.objects.filter(visitor__isnull=True)
    
    for session in sessions_without_visitor:
        # Create a new visitor for this session
        visitor = Visitor.objects.create()
        session.visitor = visitor
        session.save(update_fields=['visitor'])


def reverse_populate_visitors(apps, schema_editor):
    """
    Reverse migration - remove visitors (sessions will be deleted due to CASCADE).
    This is a destructive operation, so we'll just pass.
    """
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('chats', '0006_visitor_session_visitor_and_more'),
    ]

    operations = [
        migrations.RunPython(populate_visitors_for_sessions, reverse_populate_visitors),
    ]
