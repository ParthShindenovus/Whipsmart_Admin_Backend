# Generated manually for adding last_message fields to Session model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chats', '0010_set_default_conversation_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='session',
            name='last_message',
            field=models.TextField(blank=True, help_text='Last message in the session (for frontend preview)', null=True),
        ),
        migrations.AddField(
            model_name='session',
            name='last_message_at',
            field=models.DateTimeField(blank=True, help_text='Timestamp of the last message', null=True),
        ),
    ]

