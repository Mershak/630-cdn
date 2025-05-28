FROM python:3.9-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY simulator.py .

# Create results directory
RUN mkdir -p /app/results

# Run the simulation
CMD ["python", "simulator.py"] 