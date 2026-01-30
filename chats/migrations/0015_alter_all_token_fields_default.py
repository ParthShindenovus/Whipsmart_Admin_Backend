# Migration to add default value to all token-related columns

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('chats', '0014_alter_session_total_tokens_default'),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE chats_session MODIFY total_prompt_tokens INT NOT NULL DEFAULT 0;",
            reverse_sql="ALTER TABLE chats_session MODIFY total_prompt_tokens INT NOT NULL;",
        ),
        migrations.RunSQL(
            sql="ALTER TABLE chats_session MODIFY total_completion_tokens INT NOT NULL DEFAULT 0;",
            reverse_sql="ALTER TABLE chats_session MODIFY total_completion_tokens INT NOT NULL;",
        ),
        migrations.RunSQL(
            sql="ALTER TABLE chats_chatmessage MODIFY prompt_tokens INT NOT NULL DEFAULT 0;",
            reverse_sql="ALTER TABLE chats_chatmessage MODIFY prompt_tokens INT NOT NULL;",
        ),
        migrations.RunSQL(
            sql="ALTER TABLE chats_chatmessage MODIFY completion_tokens INT NOT NULL DEFAULT 0;",
            reverse_sql="ALTER TABLE chats_chatmessage MODIFY completion_tokens INT NOT NULL;",
        ),
        migrations.RunSQL(
            sql="ALTER TABLE chats_chatmessage MODIFY total_tokens INT NOT NULL DEFAULT 0;",
            reverse_sql="ALTER TABLE chats_chatmessage MODIFY total_tokens INT NOT NULL;",
        ),
    ]
