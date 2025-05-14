FROM python:3.11-slim
WORKDIR /app
COPY ./requirements.txt ./
RUN pip install -r requirements.txt
COPY edge_node.py .
CMD ["uvicorn", "edge_node:app", "--host", "0.0.0.0", "--port", "8000"]