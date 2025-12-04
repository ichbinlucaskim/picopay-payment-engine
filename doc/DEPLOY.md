# Deployment Guide

This guide outlines steps to deploy the PicoPay Payment Engine to a cloud environment.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Deployment Options](#deployment-options)
  - [Option 1: AWS EC2 with Docker](#option-1-aws-ec2-with-docker)
  - [Option 2: AWS ECS (Elastic Container Service)](#option-2-aws-ecs-elastic-container-service)
  - [Option 3: Docker Swarm / Kubernetes](#option-3-docker-swarm--kubernetes)
- [Database Setup](#database-setup)
  - [Using AWS RDS PostgreSQL](#using-aws-rds-postgresql)
  - [Using Containerized PostgreSQL](#using-containerized-postgresql)
- [Environment Configuration](#environment-configuration)
- [Security Considerations](#security-considerations)
- [CI/CD Pipeline](#cicd-pipeline)
- [Health Checks & Monitoring](#health-checks--monitoring)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- Docker and Docker Compose installed
- Cloud provider account (AWS, Azure, GCP, etc.)
- Basic knowledge of container orchestration
- Domain name (optional, for production)

## Deployment Options

### Option 1: AWS EC2 with Docker

**Best for:** Simple deployments, development/staging environments

#### Steps:

1. **Launch EC2 Instance**
   ```bash
   # Use Amazon Linux 2 or Ubuntu 22.04 LTS
   # Instance type: t3.medium or larger (2+ vCPU, 4GB+ RAM)
   # Security Group: Allow inbound on ports 22 (SSH), 80 (HTTP), 443 (HTTPS), 8000 (API)
   ```

2. **Connect and Install Docker**
   ```bash
   ssh -i your-key.pem ec2-user@your-ec2-ip
   
   # Install Docker
   sudo yum update -y
   sudo yum install -y docker
   sudo systemctl start docker
   sudo systemctl enable docker
   sudo usermod -aG docker ec2-user
   
   # Install Docker Compose
   sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
   sudo chmod +x /usr/local/bin/docker-compose
   ```

3. **Clone and Deploy**
   ```bash
   git clone https://github.com/your-org/picopay-payment-engine.git
   cd picopay-payment-engine
   
   # Update docker-compose.yml to use external database (see Database Setup)
   # Set environment variables
   export DATABASE_URL="postgresql://user:pass@rds-endpoint:5432/picopay"
   
   # Build and start
   docker compose up -d --build
   ```

4. **Set Up Reverse Proxy (Nginx)**
   ```bash
   sudo yum install -y nginx
   
   # Create Nginx config: /etc/nginx/conf.d/picopay.conf
   ```
   ```nginx
   server {
       listen 80;
       server_name your-domain.com;
       
       location / {
           proxy_pass http://localhost:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```
   ```bash
   sudo systemctl start nginx
   sudo systemctl enable nginx
   ```

5. **Set Up SSL (Let's Encrypt)**
   ```bash
   sudo yum install -y certbot python3-certbot-nginx
   sudo certbot --nginx -d your-domain.com
   ```

### Option 2: AWS ECS (Elastic Container Service)

**Best for:** Production environments, auto-scaling, managed container orchestration

#### Steps:

1. **Push Docker Image to ECR**
   ```bash
   # Create ECR repository
   aws ecr create-repository --repository-name picopay-payment-engine
   
   # Get login token
   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com
   
   # Build and push
   docker build -t picopay-payment-engine .
   docker tag picopay-payment-engine:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/picopay-payment-engine:latest
   docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/picopay-payment-engine:latest
   ```

2. **Create ECS Task Definition**
   ```json
   {
     "family": "picopay-app",
     "networkMode": "awsvpc",
     "requiresCompatibilities": ["FARGATE"],
     "cpu": "512",
     "memory": "1024",
     "containerDefinitions": [
       {
         "name": "picopay-app",
         "image": "<account-id>.dkr.ecr.us-east-1.amazonaws.com/picopay-payment-engine:latest",
         "portMappings": [
           {
             "containerPort": 8000,
             "protocol": "tcp"
           }
         ],
         "environment": [
           {
             "name": "DATABASE_URL",
             "value": "postgresql://user:pass@rds-endpoint:5432/picopay"
           }
         ],
         "logConfiguration": {
           "logDriver": "awslogs",
           "options": {
             "awslogs-group": "/ecs/picopay-app",
             "awslogs-region": "us-east-1",
             "awslogs-stream-prefix": "ecs"
           }
         }
       }
     ]
   }
   ```

3. **Create ECS Cluster and Service**
   ```bash
   # Create cluster
   aws ecs create-cluster --cluster-name picopay-cluster
   
   # Register task definition
   aws ecs register-task-definition --cli-input-json file://task-definition.json
   
   # Create service
   aws ecs create-service \
     --cluster picopay-cluster \
     --service-name picopay-service \
     --task-definition picopay-app \
     --desired-count 2 \
     --launch-type FARGATE \
     --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=ENABLED}"
   ```

4. **Set Up Application Load Balancer**
   - Create ALB in AWS Console
   - Configure target group pointing to ECS service
   - Set health check path to `/health`

### Option 3: Docker Swarm / Kubernetes

**Best for:** Multi-node deployments, high availability

#### Docker Swarm Quick Start:
```bash
# Initialize swarm
docker swarm init

# Create overlay network
docker network create --driver overlay picopay-network

# Deploy stack
docker stack deploy -c docker-compose.prod.yml picopay
```

#### Kubernetes (Basic):
```bash
# Create namespace
kubectl create namespace picopay

# Create secret for database URL
kubectl create secret generic picopay-secrets \
  --from-literal=database-url="postgresql://user:pass@rds-endpoint:5432/picopay" \
  -n picopay

# Deploy using kubectl or Helm
kubectl apply -f k8s/
```

## Database Setup

### Using AWS RDS PostgreSQL

**Recommended for:** Production environments

#### Steps:

1. **Create RDS Instance**
   ```bash
   aws rds create-db-instance \
     --db-instance-identifier picopay-db \
     --db-instance-class db.t3.micro \
     --engine postgres \
     --engine-version 15.4 \
     --master-username postgres \
     --master-user-password YourSecurePassword123! \
     --allocated-storage 20 \
     --vpc-security-group-ids sg-xxx \
     --db-subnet-group-name default \
     --backup-retention-period 7 \
     --storage-encrypted
   ```

2. **Configure Security Group**
   - Allow inbound PostgreSQL (port 5432) from your application security group only
   - Do NOT expose to 0.0.0.0/0

3. **Update Application Configuration**
   ```bash
   # Get RDS endpoint
   aws rds describe-db-instances --db-instance-identifier picopay-db
   
   # Update DATABASE_URL
   export DATABASE_URL="postgresql://postgres:YourSecurePassword123!@picopay-db.xxxxx.us-east-1.rds.amazonaws.com:5432/picopay"
   ```

4. **Run Migrations**
   ```bash
   # The application auto-creates tables on startup, or run manually:
   docker run --rm \
     -e DATABASE_URL="postgresql://..." \
     picopay-payment-engine \
     python -c "from app.database import Base, engine; Base.metadata.create_all(bind=engine)"
   ```

### Using Containerized PostgreSQL

**Best for:** Development, staging, or when RDS is not available

Update `docker-compose.yml` to use external network or keep local setup for development.

## Environment Configuration

### Required Environment Variables

```bash
# Database connection
DATABASE_URL=postgresql://username:password@host:5432/dbname

# Optional: Application settings
LOG_LEVEL=INFO
API_HOST=0.0.0.0
API_PORT=8000
```

### Production docker-compose.yml

A production-ready configuration is provided in `docker-compose.prod.yml`. Key differences from development:

- Uses multiple workers (`--workers 4`) for better performance
- Includes resource limits and reservations
- Configured logging with rotation
- Health checks enabled
- No hot-reload (production mode)

**Usage:**
```bash
# Set environment variables
export DATABASE_URL="postgresql://user:pass@rds-endpoint:5432/picopay"
export LOG_LEVEL="INFO"

# Deploy
docker compose -f docker-compose.prod.yml up -d --build
```

See `docker-compose.prod.yml` for the complete configuration.

## Security Considerations

### 1. **Database Security**
   - Use strong passwords (16+ characters, mixed case, numbers, symbols)
   - Enable SSL/TLS for database connections
   - Restrict database access to application servers only
   - Use AWS Secrets Manager or similar for credential management

### 2. **Application Security**
   - Never commit secrets to version control
   - Use environment variables or secret management services
   - Enable HTTPS/TLS for all API traffic
   - Implement rate limiting (consider using nginx or API Gateway)
   - Add authentication/authorization for production

### 3. **Network Security**
   - Use security groups/firewalls to restrict access
   - Only expose necessary ports (80, 443)
   - Use VPC for network isolation
   - Enable DDoS protection (AWS Shield, Cloudflare)

### 4. **Container Security**
   - Regularly update base images
   - Scan images for vulnerabilities
   - Run containers as non-root user
   - Use read-only filesystems where possible

## CI/CD Pipeline

### GitHub Actions Example

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy to Production

on:
  push:
    branches:
      - main

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v3
      
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v2
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1
      
      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v1
      
      - name: Build, tag, and push image to Amazon ECR
        env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          ECR_REPOSITORY: picopay-payment-engine
          IMAGE_TAG: ${{ github.sha }}
        run: |
          docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG .
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG
          docker tag $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG $ECR_REGISTRY/$ECR_REPOSITORY:latest
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:latest
      
      - name: Update ECS service
        run: |
          aws ecs update-service \
            --cluster picopay-cluster \
            --service picopay-service \
            --force-new-deployment
```

### GitLab CI Example

Create `.gitlab-ci.yml`:

```yaml
stages:
  - build
  - deploy

build:
  stage: build
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
    - docker tag $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA $CI_REGISTRY_IMAGE:latest
    - docker push $CI_REGISTRY_IMAGE:latest

deploy:
  stage: deploy
  script:
    - aws ecs update-service --cluster picopay-cluster --service picopay-service --force-new-deployment
  only:
    - main
```

## Health Checks & Monitoring

### Application Health Check

The application provides a `/health` endpoint:

```bash
curl http://your-api-url/health
# Returns: {"status":"healthy"}
```

### Monitoring Setup

1. **CloudWatch (AWS)**
   - Enable CloudWatch Logs for ECS tasks
   - Set up CloudWatch Alarms for:
     - High error rates
     - High latency
     - Low request count (service down)

2. **Application Logs**
   - Logs are output to stdout/stderr
   - Use structured logging for better parsing
   - Monitor for:
     - Failed transactions
     - Idempotency hits
     - Insufficient balance errors

3. **Database Monitoring**
   - Monitor RDS CloudWatch metrics:
     - CPU utilization
     - Database connections
     - Storage space
     - Read/Write latency

### Example Monitoring Script

```bash
#!/bin/bash
# health-check.sh

API_URL="https://your-api-url.com/health"
MAX_RETRIES=3
RETRY_DELAY=5

for i in $(seq 1 $MAX_RETRIES); do
  if curl -f -s "$API_URL" > /dev/null; then
    echo "Health check passed"
    exit 0
  fi
  echo "Health check failed, retrying in $RETRY_DELAY seconds..."
  sleep $RETRY_DELAY
done

echo "Health check failed after $MAX_RETRIES attempts"
exit 1
```

## Troubleshooting

### Common Issues

1. **Database Connection Errors**
   ```bash
   # Check database connectivity
   psql -h rds-endpoint -U postgres -d picopay
   
   # Verify security group rules
   # Check DATABASE_URL environment variable
   ```

2. **Container Won't Start**
   ```bash
   # Check logs
   docker logs picopay_app
   
   # Verify environment variables
   docker exec picopay_app env | grep DATABASE_URL
   ```

3. **High Memory Usage**
   ```bash
   # Check container stats
   docker stats picopay_app
   
   # Consider increasing container memory or optimizing queries
   ```

4. **SSL/TLS Issues**
   ```bash
   # Test SSL connection
   openssl s_client -connect your-domain.com:443
   
   # Renew Let's Encrypt certificate
   sudo certbot renew
   ```

### Useful Commands

```bash
# View application logs
docker logs -f picopay_app

# Restart services
docker compose restart app

# Scale application
docker compose up -d --scale app=3

# Database backup (RDS)
aws rds create-db-snapshot --db-instance-identifier picopay-db --db-snapshot-identifier picopay-backup-$(date +%Y%m%d)

# Rollback deployment
aws ecs update-service --cluster picopay-cluster --service picopay-service --task-definition picopay-app:previous
```

## Next Steps

- Set up automated backups for database
- Configure log aggregation (ELK, CloudWatch, etc.)
- Implement API rate limiting
- Add authentication/authorization
- Set up alerting for critical errors
- Configure auto-scaling based on metrics
- Implement blue-green deployments for zero-downtime updates

## Additional Resources

- [FastAPI Deployment Documentation](https://fastapi.tiangolo.com/deployment/)
- [AWS ECS Best Practices](https://docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide/intro.html)
- [PostgreSQL on AWS RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_PostgreSQL.html)
- [Docker Production Best Practices](https://docs.docker.com/develop/dev-best-practices/)

