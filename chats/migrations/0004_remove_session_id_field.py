# Generated manually - Remove session_id field and use id as session identifier
from django.db import migrations, models


def update_foreign_key_constraint(apps, schema_editor):
    """
    Update ChatMessage foreign key to reference Session.id instead of Session.session_id.
    Also handle dropping the session_id column if it exists.
    """
    with schema_editor.connection.cursor() as cursor:
        # Step 1: Drop the existing foreign key constraint
        constraint_found = False
        try:
            cursor.execute("ALTER TABLE chats_chatmessage DROP FOREIGN KEY chats_chatmessage_session_id_ff055b28_fk_chats_ses;")
            constraint_found = True
        except Exception:
            pass
        
        if not constraint_found:
            cursor.execute("""
                SELECT CONSTRAINT_NAME 
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE 
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'chats_chatmessage'
                AND COLUMN_NAME = 'session_id'
                AND REFERENCED_TABLE_NAME = 'chats_session'
                LIMIT 1;
            """)
            result = cursor.fetchone()
            if result:
                constraint_name = result[0]
                cursor.execute(f"ALTER TABLE chats_chatmessage DROP FOREIGN KEY {constraint_name};")
        
        # Step 2: Recreate foreign key constraint pointing to Session.id
        try:
            cursor.execute("""
                ALTER TABLE chats_chatmessage 
                ADD CONSTRAINT chats_chatmessage_session_id_fk_session_id 
                FOREIGN KEY (session_id) REFERENCES chats_session(id) ON DELETE CASCADE;
            """)
        except Exception:
            pass  # Constraint might already exist
        
        # Step 3: Drop index on session_id if it exists
        try:
            cursor.execute("DROP INDEX chats_sessi_session_0440a7_idx ON chats_session;")
        except Exception:
            pass
        
        # Step 4: Check if session_id column exists and drop it if it does
        cursor.execute("""
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'chats_session'
            AND COLUMN_NAME = 'session_id';
        """)
        result = cursor.fetchone()
        if result and result[0] > 0:
            cursor.execute("ALTER TABLE chats_session DROP COLUMN session_id;")


def reverse_migration(apps, schema_editor):
    """Reverse migration is not supported"""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('chats', '0003_alter_session_session_id'),
    ]

    operations = [
        # Update foreign key and drop column in database
        migrations.RunPython(
            update_foreign_key_constraint,
            reverse_migration,
        ),
        
        # Update model state only (don't try to drop column in database since we did it in RunPython)
        migrations.SeparateDatabaseAndState(
            database_operations=[
                # Database operations already done in RunPython above
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name='session',
                    name='session_id',
                ),
            ],
        ),
    ]
