# Generated migration for adding contact fields to Visitor model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chats', '0019_undo_visitor_and_session_changes'),
    ]

    operations = [
        migrations.AddField(
            model_name='visitor',
            name='name',
            field=models.CharField(blank=True, help_text="Visitor's full name", max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='visitor',
            name='email',
            field=models.EmailField(blank=True, help_text="Visitor's email address", max_length=254, null=True),
        ),
        migrations.AddField(
            model_name='visitor',
            name='phone',
            field=models.CharField(blank=True, help_text="Visitor's phone number", max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='visitor',
            name='questions_asked',
            field=models.IntegerField(default=0, help_text='Number of questions asked by this visitor across all sessions'),
        ),
    ]
