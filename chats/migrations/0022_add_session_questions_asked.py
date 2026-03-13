# Migration to add questions_asked field to Session model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chats', '0021_set_default_questions_asked'),
    ]

    operations = [
        migrations.AddField(
            model_name='session',
            name='questions_asked',
            field=models.IntegerField(default=0, help_text='Number of questions asked in this session'),
        ),
    ]
