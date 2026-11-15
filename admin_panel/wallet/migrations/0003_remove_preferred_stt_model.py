# Удаление выбора STT-модели: whisper-1 у провайдера нет, модель одна.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('wallet', '0002_user_last_chat_id'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='user',
            name='preferred_stt_model',
        ),
    ]