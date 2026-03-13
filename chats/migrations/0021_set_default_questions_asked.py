# Migration to set default questions_asked for existing visitors

from django.db import migrations


def set_default_questions_asked(apps, schema_editor):
    """Set questions_asked to 0 for all existing visitors."""
    Visitor = apps.get_model('chats', 'Visitor')
    # Update all visitors where questions_asked is NULL
    Visitor.objects.filter(questions_asked__isnull=True).update(questions_asked=0)


class Migration(migrations.Migration):

    dependencies = [
        ('chats', '0020_add_visitor_contact_fields'),
    ]

    operations = [
        migrations.RunPython(set_default_questions_asked, reverse_code=migrations.RunPython.noop),
    ]
