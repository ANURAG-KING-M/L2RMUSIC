# Use the Python + Node.js base image
FROM nikolaik/python-nodejs:python3.10-nodejs19

# Replace debian repositories with the archived ones (for buster)
RUN sed -i 's|http://deb.debian.org/debian|http://archive.debian.org/debian|g' /etc/apt/sources.list && \
    sed -i '/security.debian.org/d' /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy the application code to the container
COPY . /app/

# Set working directory
WORKDIR /app/

# Install Python dependencies
RUN pip3 install --no-cache-dir -U -r requirements.txt

# Install Node.js dependencies (if applicable)
RUN npm install

# Expose necessary port (adjust as needed for your app)
EXPOSE 8080

# Start the application
# Adjust the CMD depending on your app (either Python or Node.js app)
CMD ["bash", "start"]
