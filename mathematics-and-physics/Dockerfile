FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 appuser
COPY bot.py storage.py tutor.py knowledge.py questions.py ./
COPY engine/ ./engine/
COPY knowledge/ ./knowledge/
USER appuser
CMD ["python", "bot.py"]
