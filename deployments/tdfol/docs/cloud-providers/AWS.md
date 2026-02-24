# AWS Deployment Guide for TDFOL

This guide covers deploying TDFOL on Amazon Web Services (AWS) using ECS and EKS.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Deployment Options](#deployment-options)
- [Option 1: AWS ECS (Fargate)](#option-1-aws-ecs-fargate)
- [Option 2: AWS EKS (Kubernetes)](#option-2-aws-eks-kubernetes)
- [Configuration](#configuration)
- [Monitoring](#monitoring)
- [Security Best Practices](#security-best-practices)
- [Cost Optimization](#cost-optimization)
- [Troubleshooting](#troubleshooting)

## Prerequisites

### Required Tools

```bash
# Install AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Install eksctl (for EKS)
curl --silent --location "https://github.com/weaveworks/eksctl/releases/latest/download/eksctl_$(uname -s)_amd64.tar.gz" | tar xz -C /tmp
sudo mv /tmp/eksctl /usr/local/bin

# Install kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# Install Helm
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Configure AWS credentials
aws configure
```

### AWS Account Requirements

- Active AWS account with billing enabled
- IAM user with appropriate permissions:
  - EC2 full access
  - ECS full access
  - EKS full access
  - ECR full access
  - IAM role creation
  - VPC management
  - CloudWatch access

## Deployment Options

### Option Comparison

| Feature | ECS Fargate | EKS |
|---------|-------------|-----|
| Management | Fully managed | Managed control plane |
| Kubernetes | No | Yes |
| Cost | Pay per task | Pay for nodes + control plane |
| Scaling | Simple | Advanced (HPA, CA) |
| Best For | Simple workloads | Complex applications |
| Learning Curve | Low | Medium-High |

## Option 1: AWS ECS (Fargate)

### Step 1: Create ECR Repository

```bash
# Create ECR repository
aws ecr create-repository \
  --repository-name tdfol \
  --region us-east-1

# Get repository URI
REPO_URI=$(aws ecr describe-repositories \
  --repository-names tdfol \
  --query 'repositories[0].repositoryUri' \
  --output text)

echo "Repository URI: $REPO_URI"
```

### Step 2: Build and Push Docker Image

```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin $REPO_URI

# Build image
docker build -t tdfol:latest -f deployment/tdfol/Dockerfile .

# Tag image
docker tag tdfol:latest $REPO_URI:latest
docker tag tdfol:latest $REPO_URI:$(git rev-parse --short HEAD)

# Push image
docker push $REPO_URI:latest
docker push $REPO_URI:$(git rev-parse --short HEAD)
```

### Step 3: Create ECS Cluster

```bash
# Create ECS cluster
aws ecs create-cluster \
  --cluster-name tdfol-cluster \
  --capacity-providers FARGATE FARGATE_SPOT \
  --default-capacity-provider-strategy \
    capacityProvider=FARGATE,weight=1,base=1 \
    capacityProvider=FARGATE_SPOT,weight=4
```

### Step 4: Create Task Definition

Create `ecs-task-definition.json`:

```json
{
  "family": "tdfol",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "2048",
  "memory": "4096",
  "containerDefinitions": [
    {
      "name": "tdfol",
      "image": "${REPO_URI}:latest",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 8080,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {"name": "TDFOL_LOG_LEVEL", "value": "INFO"},
        {"name": "TDFOL_WORKERS", "value": "4"}
      ],
      "secrets": [
        {
          "name": "SECRET_KEY",
          "valueFrom": "arn:aws:secretsmanager:region:account:secret:tdfol/secret-key"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/tdfol",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      },
      "healthCheck": {
        "command": ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 60
      }
    }
  ],
  "executionRoleArn": "arn:aws:iam::account:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::account:role/tdfol-task-role"
}
```

Register task definition:

```bash
aws ecs register-task-definition --cli-input-json file://ecs-task-definition.json
```

### Step 5: Create ALB (Application Load Balancer)

```bash
# Create security group for ALB
aws ec2 create-security-group \
  --group-name tdfol-alb-sg \
  --description "Security group for TDFOL ALB" \
  --vpc-id vpc-xxxxxx

# Allow HTTP/HTTPS traffic
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxx \
  --protocol tcp \
  --port 80 \
  --cidr 0.0.0.0/0

aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxx \
  --protocol tcp \
  --port 443 \
  --cidr 0.0.0.0/0

# Create ALB
aws elbv2 create-load-balancer \
  --name tdfol-alb \
  --subnets subnet-xxxxxx subnet-yyyyyy \
  --security-groups sg-xxxxxx \
  --scheme internet-facing \
  --type application

# Create target group
aws elbv2 create-target-group \
  --name tdfol-targets \
  --protocol HTTP \
  --port 8080 \
  --vpc-id vpc-xxxxxx \
  --target-type ip \
  --health-check-path /health \
  --health-check-interval-seconds 30

# Create listener
aws elbv2 create-listener \
  --load-balancer-arn arn:aws:elasticloadbalancing:region:account:loadbalancer/app/tdfol-alb/xxxxx \
  --protocol HTTP \
  --port 80 \
  --default-actions Type=forward,TargetGroupArn=arn:aws:elasticloadbalancing:region:account:targetgroup/tdfol-targets/xxxxx
```

### Step 6: Create ECS Service

```bash
# Create security group for ECS tasks
aws ec2 create-security-group \
  --group-name tdfol-task-sg \
  --description "Security group for TDFOL ECS tasks" \
  --vpc-id vpc-xxxxxx

# Allow traffic from ALB
aws ec2 authorize-security-group-ingress \
  --group-id sg-yyyyyy \
  --protocol tcp \
  --port 8080 \
  --source-group sg-xxxxxx

# Create ECS service
aws ecs create-service \
  --cluster tdfol-cluster \
  --service-name tdfol-service \
  --task-definition tdfol:1 \
  --desired-count 3 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxxxxx,subnet-yyyyyy],securityGroups=[sg-yyyyyy],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=arn:aws:elasticloadbalancing:region:account:targetgroup/tdfol-targets/xxxxx,containerName=tdfol,containerPort=8080" \
  --health-check-grace-period-seconds 60
```

### Step 7: Enable Auto Scaling

```bash
# Register scalable target
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id service/tdfol-cluster/tdfol-service \
  --scalable-dimension ecs:service:DesiredCount \
  --min-capacity 3 \
  --max-capacity 10

# Create scaling policy
aws application-autoscaling put-scaling-policy \
  --service-namespace ecs \
  --resource-id service/tdfol-cluster/tdfol-service \
  --scalable-dimension ecs:service:DesiredCount \
  --policy-name tdfol-cpu-scaling \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration file://scaling-policy.json
```

`scaling-policy.json`:

```json
{
  "TargetValue": 70.0,
  "PredefinedMetricSpecification": {
    "PredefinedMetricType": "ECSServiceAverageCPUUtilization"
  },
  "ScaleInCooldown": 300,
  "ScaleOutCooldown": 60
}
```

## Option 2: AWS EKS (Kubernetes)

### Step 1: Create EKS Cluster

```bash
# Create cluster configuration
cat > eks-cluster.yaml <<EOF
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig

metadata:
  name: tdfol-cluster
  region: us-east-1
  version: "1.28"

managedNodeGroups:
  - name: tdfol-nodes
    instanceType: t3.xlarge
    minSize: 3
    maxSize: 10
    desiredCapacity: 3
    volumeSize: 50
    ssh:
      allow: true
    labels:
      role: tdfol
    tags:
      Environment: production
      Application: tdfol
    iam:
      withAddonPolicies:
        autoScaler: true
        cloudWatch: true
        ebs: true
        efs: true
        albIngress: true

addons:
  - name: vpc-cni
  - name: coredns
  - name: kube-proxy
  - name: aws-ebs-csi-driver

iam:
  withOIDC: true
EOF

# Create cluster
eksctl create cluster -f eks-cluster.yaml
```

### Step 2: Configure kubectl

```bash
# Update kubeconfig
aws eks update-kubeconfig \
  --name tdfol-cluster \
  --region us-east-1

# Verify connection
kubectl get nodes
```

### Step 3: Install AWS Load Balancer Controller

```bash
# Create IAM policy
curl -o iam-policy.json https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/main/docs/install/iam_policy.json

aws iam create-policy \
  --policy-name AWSLoadBalancerControllerIAMPolicy \
  --policy-document file://iam-policy.json

# Create service account
eksctl create iamserviceaccount \
  --cluster=tdfol-cluster \
  --namespace=kube-system \
  --name=aws-load-balancer-controller \
  --attach-policy-arn=arn:aws:iam::account:policy/AWSLoadBalancerControllerIAMPolicy \
  --approve

# Install controller
helm repo add eks https://aws.github.io/eks-charts
helm repo update

helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=tdfol-cluster \
  --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller
```

### Step 4: Install Metrics Server

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

### Step 5: Deploy TDFOL with Helm

```bash
# Create namespace
kubectl create namespace tdfol

# Create secrets
kubectl create secret generic tdfol-secrets \
  --namespace tdfol \
  --from-literal=SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=JWT_SECRET="$(openssl rand -hex 32)"

# Install Helm chart
helm install tdfol deployment/tdfol/helm/tdfol \
  --namespace tdfol \
  --values deployment/tdfol/helm/tdfol/values.yaml \
  --set image.registry=$REPO_URI \
  --set image.tag=latest \
  --set ingress.enabled=true \
  --set ingress.className=alb \
  --set ingress.annotations."alb\.ingress\.kubernetes\.io/scheme"=internet-facing \
  --set ingress.annotations."alb\.ingress\.kubernetes\.io/target-type"=ip
```

### Step 6: Configure Autoscaling

```bash
# Install Cluster Autoscaler
kubectl apply -f https://raw.githubusercontent.com/kubernetes/autoscaler/master/cluster-autoscaler/cloudprovider/aws/examples/cluster-autoscaler-autodiscover.yaml

# Verify HPA is working
kubectl get hpa -n tdfol
```

## Configuration

### Environment Variables

Store sensitive configuration in AWS Secrets Manager:

```bash
# Create secret
aws secretsmanager create-secret \
  --name tdfol/config \
  --description "TDFOL configuration" \
  --secret-string '{
    "SECRET_KEY": "your-secret-key",
    "API_TOKEN": "your-api-token",
    "DATABASE_URL": "postgresql://user:pass@host:5432/db"
  }'

# Grant access to ECS task role
aws iam put-role-policy \
  --role-name tdfol-task-role \
  --policy-name SecretsManagerAccess \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:region:account:secret:tdfol/*"
    }]
  }'
```

### Using RDS for Database

```bash
# Create RDS PostgreSQL instance
aws rds create-db-instance \
  --db-instance-identifier tdfol-db \
  --db-instance-class db.t3.medium \
  --engine postgres \
  --engine-version 15.3 \
  --master-username admin \
  --master-user-password <password> \
  --allocated-storage 100 \
  --storage-type gp3 \
  --vpc-security-group-ids sg-xxxxxx \
  --db-subnet-group-name tdfol-subnet-group \
  --backup-retention-period 7 \
  --preferred-backup-window "03:00-04:00" \
  --multi-az \
  --storage-encrypted \
  --enable-performance-insights

# Get endpoint
aws rds describe-db-instances \
  --db-instance-identifier tdfol-db \
  --query 'DBInstances[0].Endpoint.Address' \
  --output text
```

### Using ElastiCache for Redis

```bash
# Create ElastiCache Redis cluster
aws elasticache create-cache-cluster \
  --cache-cluster-id tdfol-redis \
  --cache-node-type cache.t3.medium \
  --engine redis \
  --engine-version 7.0 \
  --num-cache-nodes 1 \
  --cache-subnet-group-name tdfol-subnet-group \
  --security-group-ids sg-xxxxxx \
  --snapshot-retention-limit 5 \
  --automatic-failover-enabled false

# Get endpoint
aws elasticache describe-cache-clusters \
  --cache-cluster-id tdfol-redis \
  --show-cache-node-info \
  --query 'CacheClusters[0].CacheNodes[0].Endpoint.Address' \
  --output text
```

## Monitoring

### CloudWatch Integration

```bash
# Create CloudWatch log group
aws logs create-log-group --log-group-name /aws/ecs/tdfol

# Create CloudWatch dashboard
aws cloudwatch put-dashboard \
  --dashboard-name TDFOL-Metrics \
  --dashboard-body file://cloudwatch-dashboard.json
```

### X-Ray Tracing

```bash
# Enable X-Ray in task definition
{
  "containerDefinitions": [
    {
      "name": "xray-daemon",
      "image": "amazon/aws-xray-daemon",
      "cpu": 32,
      "memoryReservation": 256,
      "portMappings": [
        {
          "containerPort": 2000,
          "protocol": "udp"
        }
      ]
    }
  ]
}
```

## Security Best Practices

1. **Use IAM Roles**: Assign least-privilege IAM roles to tasks
2. **Enable Encryption**: Use encrypted EBS volumes and RDS storage
3. **Network Isolation**: Use private subnets for tasks, public for ALB
4. **Secrets Management**: Store secrets in AWS Secrets Manager
5. **VPC Endpoints**: Use VPC endpoints for AWS services
6. **Security Groups**: Implement strict security group rules
7. **WAF**: Deploy AWS WAF in front of ALB
8. **GuardDuty**: Enable AWS GuardDuty for threat detection

## Cost Optimization

### Monthly Cost Estimates (us-east-1)

#### ECS Fargate Option

- **3 Fargate tasks (2 vCPU, 4GB RAM)**: ~$140/month
- **Application Load Balancer**: ~$20/month
- **Data transfer (100GB/month)**: ~$9/month
- **CloudWatch Logs (10GB/month)**: ~$5/month
- **RDS db.t3.medium (optional)**: ~$70/month
- **ElastiCache t3.medium (optional)**: ~$50/month

**Total**: $294-424/month

#### EKS Option

- **EKS Control Plane**: $73/month
- **3x t3.xlarge nodes**: ~$280/month
- **Application Load Balancer**: ~$20/month
- **Data transfer (100GB/month)**: ~$9/month
- **CloudWatch Logs (10GB/month)**: ~$5/month
- **RDS db.t3.medium (optional)**: ~$70/month
- **ElastiCache t3.medium (optional)**: ~$50/month

**Total**: $457-577/month

### Cost Optimization Tips

1. Use Fargate Spot for non-critical tasks (70% savings)
2. Enable EBS volume optimization
3. Use S3 for static assets and backups
4. Implement CloudWatch Log retention policies
5. Use Reserved Instances for predictable workloads
6. Enable EKS Cluster Autoscaler for right-sizing
7. Use Graviton2 instances (ARM) for 20% cost savings

## Troubleshooting

### Common Issues

#### Issue: Tasks failing to start

```bash
# Check task logs
aws ecs describe-tasks \
  --cluster tdfol-cluster \
  --tasks <task-arn>

# View CloudWatch logs
aws logs tail /aws/ecs/tdfol --follow
```

#### Issue: Cannot pull Docker image

```bash
# Verify ECR permissions
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <repo-uri>

# Check task execution role has ECR permissions
aws iam get-role-policy --role-name ecsTaskExecutionRole --policy-name ECRAccess
```

#### Issue: Service not scaling

```bash
# Check CloudWatch alarms
aws cloudwatch describe-alarms

# Verify metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name CPUUtilization \
  --dimensions Name=ServiceName,Value=tdfol-service Name=ClusterName,Value=tdfol-cluster \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-01T23:59:59Z \
  --period 300 \
  --statistics Average
```

### Support Resources

- [AWS ECS Documentation](https://docs.aws.amazon.com/ecs/)
- [AWS EKS Documentation](https://docs.aws.amazon.com/eks/)
- [AWS Support](https://aws.amazon.com/support/)
- [GitHub Issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)

## Next Steps

- [Configure monitoring and alerts](../monitoring.md)
- [Set up CI/CD pipeline](../cicd.md)
- [Scale your deployment](../scaling.md)
- [Backup and disaster recovery](../backup.md)
