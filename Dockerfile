# Use Debian Buster and update repository to archive
FROM debian:10-slim

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive

# Update the apt sources list to use archived repositories
RUN sed -i 's/http:\/\/deb.debian.org/http:\/\/archive.debian.org/g' /etc/apt/sources.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Optionally, add your app's code or other commands here
