import os
from faster_whisper import WhisperModel
from app.celery_app import celery_app

# Загружаем модель (она скачается один раз при первом запуске, ~140МБ)
model_size = "base"
model = WhisperModel(model_size, device="cpu", compute_type="int8")

@celery_app.task(bind=True, name='transcribe_video')
def transcribe_video(self, file_path: str, original_filename: str):
    try:
        # Локальная транскрибация
        segments, info = model.transcribe(file_path, beam_size=5)
        
        # Собираем текст из сегментов
        transcript = " ".join([segment.text for segment in segments])
        
        return {
            'filename': original_filename,
            'transcript': transcript,
            'status': 'done'
        }
    except Exception as e:
        return {
            'filename': original_filename,
            'status': 'error',
            'error': str(e)
        }