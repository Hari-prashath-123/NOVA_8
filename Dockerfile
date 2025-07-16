FROM python:3.9
WORKDIR /app
# Update pip to the latest version
RUN pip install --upgrade pip
# Create and activate a virtual environment
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Copy the application code
COPY . .
# Expose port 5000
EXPOSE 5000
# Run the Flask app
CMD ["python", "app.py"]