FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 appuser
COPY webapp.py storage.py tutor.py knowledge.py questions.py gitea_client.py auth.py vision.py site_builder.py design_commit.py engineering_domains.py engineering_calculators.py engineering_tool_proposals.py ./
COPY engine/ ./engine/
COPY benchmarks/ ./benchmarks/
COPY knowledge/ ./knowledge/
COPY static/ ./static/
USER appuser
EXPOSE 8000
CMD ["uvicorn", "webapp:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
