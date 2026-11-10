import uuid
from pathlib import Path
from typing import Any, List
from urllib.parse import quote

import aiofiles
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response

from app.celery_app import celery_app
from app.tasks import transcribe_video

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"

app = FastAPI(title="Video Transcriber")

INDEX_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Транскрибация видео</title>
  <style>
    body { font-family: sans-serif; max-width: 860px; margin: 2rem auto; padding: 0 1rem; }
    form { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 1.5rem; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; border-bottom: 1px solid #ddd; padding: 0.5rem; vertical-align: top; }
    td.transcript { white-space: pre-wrap; }
    .error { color: #a40000; }
    button.download { margin-top: 0.4rem; }
    button.download[hidden] { display: none; }
  </style>
</head>
<body>
  <h1>Транскрибация видео</h1>
  <form id="upload-form">
    <input id="files" type="file" name="files" multiple required>
    <button type="submit">Отправить</button>
  </form>
  <table>
    <thead>
      <tr>
        <th>Файл</th>
        <th>task_id</th>
        <th>Статус</th>
        <th>Результат</th>
      </tr>
    </thead>
    <tbody id="tasks"></tbody>
  </table>
  <script>
    const form = document.getElementById("upload-form");
    const fileInput = document.getElementById("files");
    const tbody = document.getElementById("tasks");
    const rows = new Map();
    let timer = null;

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const names = Array.from(fileInput.files).map((file) => file.name);
      const body = new FormData(form);
      const response = await fetch("/transcribe", { method: "POST", body });
      if (!response.ok) {
        const message = await response.text();
        alert(message || "Не удалось отправить файлы");
        return;
      }
      const taskIds = await response.json();
      taskIds.forEach((taskId, index) => addTask(taskId, names[index] || taskId));
      form.reset();
      ensurePolling();
    });

    function addTask(taskId, filename) {
      if (rows.has(taskId)) return;
      const row = document.createElement("tr");
      const nameCell = document.createElement("td");
      const idCell = document.createElement("td");
      const statusCell = document.createElement("td");
      const resultCell = document.createElement("td");
      const resultText = document.createElement("div");
      const downloadButton = document.createElement("button");
      nameCell.textContent = filename;
      idCell.textContent = taskId;
      statusCell.textContent = "PENDING";
      resultCell.className = "transcript";
      downloadButton.type = "button";
      downloadButton.className = "download";
      downloadButton.textContent = "Скачать";
      downloadButton.hidden = true;
      downloadButton.addEventListener("click", () => {
        window.location.href = "/download/" + encodeURIComponent(taskId);
      });
      resultCell.append(resultText, downloadButton);
      row.append(nameCell, idCell, statusCell, resultCell);
      tbody.prepend(row);
      rows.set(taskId, { row, statusCell, resultText, downloadButton, done: false });
    }

    function ensurePolling() {
      if (timer !== null) return;
      poll();
      timer = setInterval(poll, 3000);
    }

    async function poll() {
      const pending = Array.from(rows.entries()).filter(([, item]) => !item.done);
      await Promise.all(pending.map(([taskId, item]) => refreshTask(taskId, item)));
      if (rows.size > 0 && Array.from(rows.values()).every((item) => item.done)) {
        clearInterval(timer);
        timer = null;
      }
    }

    async function refreshTask(taskId, item) {
      const response = await fetch("/status/" + encodeURIComponent(taskId));
      if (!response.ok) return;
      const data = await response.json();
      item.statusCell.textContent = data.status || "";
      item.resultText.classList.remove("error");
      if (data.error) {
        item.resultText.textContent = data.error;
        item.resultText.classList.add("error");
      } else if (data.result && data.result.transcript) {
        item.resultText.textContent = data.result.transcript;
      } else if (data.result) {
        item.resultText.textContent = JSON.stringify(data.result);
      } else {
        item.resultText.textContent = "";
      }
      const canDownload = data.status === "SUCCESS"
        && data.result
        && typeof data.result.transcript === "string";
      item.downloadButton.hidden = !canDownload;
      const finished = data.status === "SUCCESS" || data.status === "FAILURE" || Boolean(data.error);
      item.done = finished;
    }
  </script>
</body>
</html>
"""


def _safe_filename(filename: str | None) -> str:
    name = Path(filename or "file").name
    return name or "file"


def _attachment_disposition(original_name: str | None) -> str:
    stem = Path(_safe_filename(original_name)).stem.strip() or "transcript"
    download_name = f"{stem}.txt"
    ascii_fallback = download_name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
    if not ascii_fallback.strip("._"):
        ascii_fallback = "transcript.txt"
    encoded = quote(download_name)
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return INDEX_HTML


@app.post("/transcribe")
async def transcribe(files: List[UploadFile] = File(...)) -> List[str]:
    if not files:
        raise HTTPException(status_code=400, detail="Нужен хотя бы один файл")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    task_ids: List[str] = []

    for upload in files:
        original_name = _safe_filename(upload.filename)
        stored_name = f"{uuid.uuid4().hex}_{original_name}"
        destination = UPLOAD_DIR / stored_name

        async with aiofiles.open(destination, "wb") as outfile:
            while chunk := await upload.read(1024 * 1024):
                await outfile.write(chunk)

        task = transcribe_video.delay(str(destination), original_name)
        task_ids.append(task.id)

    return task_ids


@app.get("/status/{task_id}")
def task_status(task_id: str) -> dict[str, Any]:
    async_result = celery_app.AsyncResult(task_id)
    body: dict[str, Any] = {
        "status": async_result.status,
        "result": None,
        "error": None,
    }

    if async_result.successful():
        result = async_result.result
        if isinstance(result, dict) and result.get("status") == "error":
            body["error"] = result.get("error")
        else:
            body["result"] = result
    elif async_result.failed():
        body["error"] = str(async_result.result)

    return body


@app.get("/download/{task_id}")
def download_transcript(task_id: str) -> Response:
    async_result = celery_app.AsyncResult(task_id)
    if not async_result.successful():
        raise HTTPException(status_code=404, detail="Задача не готова или не найдена")

    result = async_result.result
    if not isinstance(result, dict) or not isinstance(result.get("transcript"), str):
        raise HTTPException(status_code=404, detail="Задача не готова или не найдена")

    return Response(
        content=result["transcript"],
        media_type="text/plain",
        headers={"Content-Disposition": _attachment_disposition(result.get("filename"))},
    )
from fastapi.responses import Response

@app.get("/download/{task_id}")
def download_transcript(task_id: str):
    result = AsyncResult(task_id, app=celery_app)
    
    # Если задача не готова или упала с ошибкой
    if not result.ready() or result.status != 'SUCCESS':
        return Response(content="Задача не готова или не найдена", status_code=404)
    
    task_result = result.result
    # Если в результате есть текст транскрипции
    if isinstance(task_result, dict) and 'transcript' in task_result:
        transcript = task_result['transcript']
        filename = task_result.get('filename', 'transcript.txt')
        
        # Меняем расширение на .txt
        if not filename.endswith('.txt'):
            filename = filename.rsplit('.', 1)[0] + '.txt'
            
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"'
        }
        return Response(content=transcript, media_type='text/plain', headers=headers)
    
    return Response(content="Транскрипция не найдена", status_code=404)