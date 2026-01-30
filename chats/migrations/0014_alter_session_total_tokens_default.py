# Migration to add default value to total_tokens column

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('chats', '0013_remove_chatmessage_input_tokens_and_more'),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE chats_session MODIFY total_tokens INT NOT NULL DEFAULT 0;",
            reverse_sql="ALTER TABLE chats_session MODIFY total_tokens INT NOT NULL;",
        ),
    ]
