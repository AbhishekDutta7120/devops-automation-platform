#!/bin/bash
# infrastructure/terraform/user-data.sh

set -e

# Log output
exec > >(tee /var/log/user-data.log)
exec 2>&1

echo "Starting user data script execution..."

# Update system
yum update -y

# Install Docker
amazon-linux-extras install docker -y
systemctl start docker
systemctl enable docker

# Add ec2-user to docker group
usermod -a -G docker ec2-user

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Install CloudWatch agent
wget https://s3.amazonaws.com/amazoncloudwatch-agent/amazon_linux/amd64/latest/amazon-cloudwatch-agent.rpm
rpm -U ./amazon-cloudwatch-agent.rpm

# Install Node Exporter for Prometheus
useradd --no-create-home --shell /bin/false node_exporter
cd /tmp
wget https://github.com/prometheus/node_exporter/releases/download/v1.6.1/node_exporter-1.6.1.linux-amd64.tar.gz
tar -xvf node_exporter-1.6.1.linux-amd64.tar.gz
cp node_exporter-1.6.1.linux-amd64/node_exporter /usr/local/bin/
chown node_exporter:node_exporter /usr/local/bin/node_exporter

# Create systemd service for Node Exporter
cat > /etc/systemd/system/node_exporter.service <<EOF
[Unit]
Description=Node Exporter
Wants=network-online.target
After=network-online.target

[Service]
User=node_exporter
Group=node_exporter
Type=simple
ExecStart=/usr/local/bin/node_exporter

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl start node_exporter
systemctl enable node_exporter

# Pull and run Docker image
echo "Pulling Docker image: ${docker_image}"
docker pull ${docker_image}

# Run application container
docker run -d \
  --name app \
  --restart unless-stopped \
  -p ${app_port}:${app_port} \
  -e NODE_ENV=${environment} \
  -e PORT=${app_port} \
  ${docker_image}

# Wait for application to be healthy
echo "Waiting for application to start..."
for i in {1..30}; do
  if curl -f http://localhost:${app_port}/health > /dev/null 2>&1; then
    echo "Application is healthy!"
    break
  fi
  echo "Attempt $i: Application not ready yet..."
  sleep 2
done

echo "User data script completed successfully!"