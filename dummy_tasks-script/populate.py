import httpx
import json

API_URL = "http://127.0.0.1:8001/api/admin/tasks"
HEADERS = {"X-Admin-Token": "admin-token"}

tasks_data = [
    # --- AWS ---
    {
        "task_name": "aws-ec2-instance",
        "display_name": "AWS EC2 Compute Instance",
        "description": "Deploy a customizable EC2 instance with elastic block storage and security groups.",
        "category": "compute",
        "provider": "aws",
        "input_schema": {
            "type": "object",
            "properties": {
                "instance_name": {"type": "string", "default": "dev-instance"},
                "instance_type": {"type": "string", "enum": ["t3.micro", "t3.small", "t3.medium"], "default": "t3.micro"},
                "ami_id": {"type": "string", "placeholder": "ami-xxxxxx"},
                "subnet_id": {"type": "string"}
            },
            "required": ["instance_name", "ami_id"]
        }
    },
    {
        "task_name": "aws-s3-bucket",
        "display_name": "AWS S3 Storage Bucket",
        "description": "Create an Amazon S3 bucket with secure access controls and optional versioning.",
        "category": "storage",
        "provider": "aws",
        "input_schema": {
            "type": "object",
            "properties": {
                "bucket_name": {"type": "string"},
                "acl": {"type": "string", "enum": ["private", "public-read"], "default": "private"},
                "versioning": {"type": "boolean", "default": False}
            },
            "required": ["bucket_name"]
        }
    },
    {
        "task_name": "aws-rds-postgres",
        "display_name": "AWS RDS PostgreSQL Database",
        "description": "Deploy a managed relational PostgreSQL database with automatic scaling and backups.",
        "category": "database",
        "provider": "aws",
        "input_schema": {
            "type": "object",
            "properties": {
                "db_name": {"type": "string"},
                "allocated_storage": {"type": "integer", "minimum": 20, "default": 20},
                "instance_class": {"type": "string", "default": "db.t3.micro"},
                "admin_user": {"type": "string", "default": "postgres_admin"},
                "multi_az": {"type": "boolean", "default": False}
            },
            "required": ["db_name"]
        }
    },
    {
        "task_name": "aws-vpc-network",
        "display_name": "AWS VPC Core Network",
        "description": "Establish a Virtual Private Cloud (VPC) with custom subnets, gateways, and routing tables.",
        "category": "network",
        "provider": "aws",
        "input_schema": {
            "type": "object",
            "properties": {
                "vpc_cidr": {"type": "string", "default": "10.0.0.0/16"},
                "public_subnets": {"type": "array", "items": {"type": "string"}, "default": ["10.0.1.0/24"]},
                "private_subnets": {"type": "array", "items": {"type": "string"}, "default": ["10.0.10.0/24"]}
            },
            "required": ["vpc_cidr"]
        }
    },
    {
        "task_name": "aws-lambda-function",
        "display_name": "AWS Lambda Serverless Function",
        "description": "Deploy serverless code executions using AWS Lambda with execution IAM role binding.",
        "category": "serverless",
        "provider": "aws",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_name": {"type": "string"},
                "runtime": {"type": "string", "enum": ["python3.11", "nodejs18.x", "go1.x"], "default": "python3.11"},
                "memory_size": {"type": "integer", "default": 128}
            },
            "required": ["function_name"]
        }
    },
    {
        "task_name": "aws-ecs-cluster",
        "display_name": "AWS ECS Container Cluster",
        "description": "Create an Elastic Container Service (ECS) cluster for deploying Fargate or EC2 container tasks.",
        "category": "compute",
        "provider": "aws",
        "input_schema": {
            "type": "object",
            "properties": {
                "cluster_name": {"type": "string"},
                "container_insights": {"type": "boolean", "default": True}
            },
            "required": ["cluster_name"]
        }
    },
    {
        "task_name": "aws-dynamodb-table",
        "display_name": "AWS DynamoDB NoSQL Table",
        "description": "Provision a fully-managed, high-performance key-value DynamoDB table.",
        "category": "database",
        "provider": "aws",
        "input_schema": {
            "type": "object",
            "properties": {
                "table_name": {"type": "string"},
                "hash_key": {"type": "string"},
                "read_capacity": {"type": "integer", "default": 5},
                "write_capacity": {"type": "integer", "default": 5}
            },
            "required": ["table_name", "hash_key"]
        }
    },
    {
        "task_name": "aws-iam-role",
        "display_name": "AWS IAM Access Role",
        "description": "Create an AWS Identity and Access Management role with customized assume-role policies.",
        "category": "security",
        "provider": "aws",
        "input_schema": {
            "type": "object",
            "properties": {
                "role_name": {"type": "string"},
                "service_principal": {"type": "string", "default": "ec2.amazonaws.com"}
            },
            "required": ["role_name"]
        }
    },
    {
        "task_name": "aws-route53-record",
        "display_name": "AWS Route53 DNS Record",
        "description": "Create or update a DNS record in an AWS Route53 hosted zone.",
        "category": "network",
        "provider": "aws",
        "input_schema": {
            "type": "object",
            "properties": {
                "zone_id": {"type": "string"},
                "record_name": {"type": "string"},
                "record_type": {"type": "string", "enum": ["A", "CNAME", "TXT", "MX"], "default": "A"},
                "ttl": {"type": "integer", "default": 300},
                "values": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["zone_id", "record_name", "values"]
        }
    },
    {
        "task_name": "aws-sqs-queue",
        "display_name": "AWS SQS Message Queue",
        "description": "Provision a standard or FIFO Simple Queue Service (SQS) message queue.",
        "category": "messaging",
        "provider": "aws",
        "input_schema": {
            "type": "object",
            "properties": {
                "queue_name": {"type": "string"},
                "fifo_queue": {"type": "boolean", "default": False},
                "retention_seconds": {"type": "integer", "default": 345600}
            },
            "required": ["queue_name"]
        }
    },
    {
        "task_name": "aws-sns-topic",
        "display_name": "AWS SNS Notification Topic",
        "description": "Deploy a Simple Notification Service (SNS) pub/sub topic for message dispatching.",
        "category": "messaging",
        "provider": "aws",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic_name": {"type": "string"},
                "display_name": {"type": "string"}
            },
            "required": ["topic_name"]
        }
    },
    {
        "task_name": "aws-cloudfront-distribution",
        "display_name": "AWS CloudFront CDN",
        "description": "Deploy a content delivery network (CDN) cache distribution pointing to S3 or custom origin.",
        "category": "network",
        "provider": "aws",
        "input_schema": {
            "type": "object",
            "properties": {
                "origin_domain": {"type": "string"},
                "ipv6_enabled": {"type": "boolean", "default": True}
            },
            "required": ["origin_domain"]
        }
    },
    {
        "task_name": "aws-kms-key",
        "display_name": "AWS KMS Encryption Key",
        "description": "Provision a Key Management Service (KMS) customer managed cryptographic key.",
        "category": "security",
        "provider": "aws",
        "input_schema": {
            "type": "object",
            "properties": {
                "key_alias": {"type": "string"},
                "rotation_enabled": {"type": "boolean", "default": True}
            },
            "required": ["key_alias"]
        }
    },
    {
        "task_name": "aws-eks-cluster",
        "display_name": "AWS EKS Kubernetes Cluster",
        "description": "Launch a managed Elastic Kubernetes Service (EKS) cluster control plane.",
        "category": "compute",
        "provider": "aws",
        "input_schema": {
            "type": "object",
            "properties": {
                "cluster_name": {"type": "string"},
                "kubernetes_version": {"type": "string", "default": "1.28"}
            },
            "required": ["cluster_name"]
        }
    },
    {
        "task_name": "aws-ebs-volume",
        "display_name": "AWS EBS Block Storage",
        "description": "Deploy an Elastic Block Store (EBS) volume for raw storage attachments.",
        "category": "storage",
        "provider": "aws",
        "input_schema": {
            "type": "object",
            "properties": {
                "availability_zone": {"type": "string"},
                "size_gb": {"type": "integer", "minimum": 1, "default": 8},
                "type": {"type": "string", "enum": ["gp3", "io2"], "default": "gp3"}
            },
            "required": ["availability_zone"]
        }
    },
    # --- Azure ---
    {
        "task_name": "azure-virtual-machine",
        "display_name": "Azure Linux VM",
        "description": "Deploy a standard Azure Linux Virtual Machine on a private subnetwork.",
        "category": "compute",
        "provider": "azure",
        "input_schema": {
            "type": "object",
            "properties": {
                "vm_name": {"type": "string"},
                "resource_group_name": {"type": "string"},
                "vm_size": {"type": "string", "default": "Standard_B1s"},
                "admin_username": {"type": "string", "default": "azureuser"}
            },
            "required": ["vm_name", "resource_group_name"]
        }
    },
    {
        "task_name": "azure-blob-storage",
        "display_name": "Azure Storage Account & Container",
        "description": "Provision an Azure Storage Account and secure Blob storage container.",
        "category": "storage",
        "provider": "azure",
        "input_schema": {
            "type": "object",
            "properties": {
                "account_name": {"type": "string"},
                "resource_group_name": {"type": "string"},
                "container_name": {"type": "string", "default": "uploads"},
                "tier": {"type": "string", "enum": ["Standard", "Premium"], "default": "Standard"}
            },
            "required": ["account_name", "resource_group_name"]
        }
    },
    {
        "task_name": "azure-sql-database",
        "display_name": "Azure SQL Server & DB",
        "description": "Provision a managed Azure SQL database instance with transparent encryption.",
        "category": "database",
        "provider": "azure",
        "input_schema": {
            "type": "object",
            "properties": {
                "server_name": {"type": "string"},
                "db_name": {"type": "string"},
                "resource_group_name": {"type": "string"},
                "admin_login": {"type": "string", "default": "sql_admin"}
            },
            "required": ["server_name", "db_name", "resource_group_name"]
        }
    },
    {
        "task_name": "azure-vnet-network",
        "display_name": "Azure Virtual Network (VNet)",
        "description": "Create an Azure Virtual Network (VNet) with Address spaces and nested subnets.",
        "category": "network",
        "provider": "azure",
        "input_schema": {
            "type": "object",
            "properties": {
                "vnet_name": {"type": "string"},
                "resource_group_name": {"type": "string"},
                "address_space": {"type": "array", "items": {"type": "string"}, "default": ["10.1.0.0/16"]}
            },
            "required": ["vnet_name", "resource_group_name"]
        }
    },
    {
        "task_name": "azure-function-app",
        "display_name": "Azure Serverless Function App",
        "description": "Provision an Azure Function App container for serverless compute plans.",
        "category": "serverless",
        "provider": "azure",
        "input_schema": {
            "type": "object",
            "properties": {
                "app_name": {"type": "string"},
                "resource_group_name": {"type": "string"},
                "os_type": {"type": "string", "enum": ["Linux", "Windows"], "default": "Linux"}
            },
            "required": ["app_name", "resource_group_name"]
        }
    },
    {
        "task_name": "azure-container-registry",
        "display_name": "Azure Container Registry (ACR)",
        "description": "Create a private Azure Container Registry for Docker images storage.",
        "category": "compute",
        "provider": "azure",
        "input_schema": {
            "type": "object",
            "properties": {
                "registry_name": {"type": "string"},
                "resource_group_name": {"type": "string"},
                "sku": {"type": "string", "enum": ["Basic", "Standard", "Premium"], "default": "Basic"}
            },
            "required": ["registry_name", "resource_group_name"]
        }
    },
    {
        "task_name": "azure-cosmos-db",
        "display_name": "Azure Cosmos DB NoSQL",
        "description": "Deploy a multi-model global Cosmos DB database account.",
        "category": "database",
        "provider": "azure",
        "input_schema": {
            "type": "object",
            "properties": {
                "account_name": {"type": "string"},
                "resource_group_name": {"type": "string"},
                "offer_type": {"type": "string", "default": "Standard"}
            },
            "required": ["account_name", "resource_group_name"]
        }
    },
    {
        "task_name": "azure-key-vault",
        "display_name": "Azure Key Vault Secret Storage",
        "description": "Establish an Azure Key Vault for hardware security modules (HSM) and credentials storage.",
        "category": "security",
        "provider": "azure",
        "input_schema": {
            "type": "object",
            "properties": {
                "vault_name": {"type": "string"},
                "resource_group_name": {"type": "string"},
                "soft_delete_retention_days": {"type": "integer", "default": 90}
            },
            "required": ["vault_name", "resource_group_name"]
        }
    },
    {
        "task_name": "azure-dns-zone",
        "display_name": "Azure DNS Hosted Zone",
        "description": "Establish a DNS hosting domain record zone inside Azure.",
        "category": "network",
        "provider": "azure",
        "input_schema": {
            "type": "object",
            "properties": {
                "zone_name": {"type": "string"},
                "resource_group_name": {"type": "string"}
            },
            "required": ["zone_name", "resource_group_name"]
        }
    },
    {
        "task_name": "azure-service-bus",
        "display_name": "Azure Service Bus Queue",
        "description": "Deploy an enterprise messaging service bus namespace and queue system.",
        "category": "messaging",
        "provider": "azure",
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace_name": {"type": "string"},
                "queue_name": {"type": "string"},
                "resource_group_name": {"type": "string"}
            },
            "required": ["namespace_name", "queue_name", "resource_group_name"]
        }
    },
    {
        "task_name": "azure-aks-cluster",
        "display_name": "Azure AKS Kubernetes",
        "description": "Provision a managed Azure Kubernetes Service (AKS) system cluster.",
        "category": "compute",
        "provider": "azure",
        "input_schema": {
            "type": "object",
            "properties": {
                "cluster_name": {"type": "string"},
                "resource_group_name": {"type": "string"},
                "dns_prefix": {"type": "string"}
            },
            "required": ["cluster_name", "resource_group_name", "dns_prefix"]
        }
    },
    {
        "task_name": "azure-application-gateway",
        "display_name": "Azure Application Gateway LoadBalancer",
        "description": "Deploy a Layer-7 Application Gateway load balancer.",
        "category": "network",
        "provider": "azure",
        "input_schema": {
            "type": "object",
            "properties": {
                "gateway_name": {"type": "string"},
                "resource_group_name": {"type": "string"},
                "sku_capacity": {"type": "integer", "default": 2}
            },
            "required": ["gateway_name", "resource_group_name"]
        }
    },
    {
        "task_name": "azure-managed-disk",
        "display_name": "Azure Managed SSD Storage",
        "description": "Deploy a managed block disk volume resource on Azure.",
        "category": "storage",
        "provider": "azure",
        "input_schema": {
            "type": "object",
            "properties": {
                "disk_name": {"type": "string"},
                "resource_group_name": {"type": "string"},
                "disk_size_gb": {"type": "integer", "default": 32}
            },
            "required": ["disk_name", "resource_group_name"]
        }
    },
    {
        "task_name": "azure-log-analytics",
        "display_name": "Azure Log Analytics Workspace",
        "description": "Provision an Azure Log Analytics Workspace for cloud logging data collection.",
        "category": "monitoring",
        "provider": "azure",
        "input_schema": {
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string"},
                "resource_group_name": {"type": "string"},
                "retention_in_days": {"type": "integer", "default": 30}
            },
            "required": ["workspace_name", "resource_group_name"]
        }
    },
    # --- GCP ---
    {
        "task_name": "gcp-compute-instance",
        "display_name": "GCP Compute Engine VM",
        "description": "Launch a Google Compute Engine virtual machine instance.",
        "category": "compute",
        "provider": "gcp",
        "input_schema": {
            "type": "object",
            "properties": {
                "instance_name": {"type": "string"},
                "machine_type": {"type": "string", "default": "e2-micro"},
                "zone": {"type": "string", "default": "us-central1-a"}
            },
            "required": ["instance_name"]
        }
    },
    {
        "task_name": "gcp-cloud-storage",
        "display_name": "GCP Cloud Storage Bucket",
        "description": "Provision a secure Google Cloud Storage (GCS) bucket.",
        "category": "storage",
        "provider": "gcp",
        "input_schema": {
            "type": "object",
            "properties": {
                "bucket_name": {"type": "string"},
                "location": {"type": "string", "default": "US"},
                "storage_class": {"type": "string", "enum": ["STANDARD", "NEARLINE", "COLDLINE"], "default": "STANDARD"}
            },
            "required": ["bucket_name"]
        }
    },
    {
        "task_name": "gcp-cloud-sql-mysql",
        "display_name": "GCP Cloud SQL MySQL Database",
        "description": "Deploy a managed MySQL server instance on GCP Cloud SQL.",
        "category": "database",
        "provider": "gcp",
        "input_schema": {
            "type": "object",
            "properties": {
                "instance_name": {"type": "string"},
                "database_version": {"type": "string", "default": "MYSQL_8_0"},
                "region": {"type": "string", "default": "us-central1"}
            },
            "required": ["instance_name"]
        }
    },
    {
        "task_name": "gcp-vpc-network",
        "display_name": "GCP VPC Core Network",
        "description": "Establish a Google Cloud Virtual Private Cloud network (VPC) with subnetworks.",
        "category": "network",
        "provider": "gcp",
        "input_schema": {
            "type": "object",
            "properties": {
                "network_name": {"type": "string"},
                "auto_create_subnetworks": {"type": "boolean", "default": False}
            },
            "required": ["network_name"]
        }
    },
    {
        "task_name": "gcp-cloud-function",
        "display_name": "GCP Serverless Cloud Function",
        "description": "Deploy serverless functional code execution directly on GCP.",
        "category": "serverless",
        "provider": "gcp",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_name": {"type": "string"},
                "region": {"type": "string", "default": "us-central1"},
                "runtime": {"type": "string", "default": "python310"}
            },
            "required": ["function_name"]
        }
    },
    {
        "task_name": "gcp-gke-cluster",
        "display_name": "GCP Google Kubernetes Engine (GKE)",
        "description": "Provision a managed Kubernetes (GKE) autopilot or standard cluster.",
        "category": "compute",
        "provider": "gcp",
        "input_schema": {
            "type": "object",
            "properties": {
                "cluster_name": {"type": "string"},
                "region": {"type": "string", "default": "us-central1"},
                "initial_node_count": {"type": "integer", "default": 3}
            },
            "required": ["cluster_name"]
        }
    },
    {
        "task_name": "gcp-pubsub-topic",
        "display_name": "GCP Pub/Sub Messaging Queue",
        "description": "Create a Google Cloud Pub/Sub asynchronous messaging topic.",
        "category": "messaging",
        "provider": "gcp",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic_name": {"type": "string"}
            },
            "required": ["topic_name"]
        }
    },
    {
        "task_name": "gcp-kms-keyring",
        "display_name": "GCP Key Management Service (KMS)",
        "description": "Create a cryptographic KeyRing and CryptoKey on Google Cloud.",
        "category": "security",
        "provider": "gcp",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyring_name": {"type": "string"},
                "key_name": {"type": "string"},
                "location": {"type": "string", "default": "global"}
            },
            "required": ["keyring_name", "key_name"]
        }
    },
    {
        "task_name": "gcp-cloud-run-service",
        "display_name": "GCP Cloud Run Container Service",
        "description": "Deploy highly-scalable containerized application workloads serverless on GCP.",
        "category": "compute",
        "provider": "gcp",
        "input_schema": {
            "type": "object",
            "properties": {
                "service_name": {"type": "string"},
                "image_url": {"type": "string"},
                "region": {"type": "string", "default": "us-central1"}
            },
            "required": ["service_name", "image_url"]
        }
    },
    {
        "task_name": "gcp-spanner-database",
        "display_name": "GCP Cloud Spanner DB",
        "description": "Launch a global scale relational SQL Spanner database account cluster.",
        "category": "database",
        "provider": "gcp",
        "input_schema": {
            "type": "object",
            "properties": {
                "instance_name": {"type": "string"},
                "config": {"type": "string", "default": "regional-us-central1"},
                "node_count": {"type": "integer", "default": 1}
            },
            "required": ["instance_name"]
        }
    },
    {
        "task_name": "gcp-bigquery-dataset",
        "display_name": "GCP BigQuery Data Warehouse",
        "description": "Create a Google BigQuery analytic data warehouse dataset.",
        "category": "database",
        "provider": "gcp",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string"},
                "location": {"type": "string", "default": "US"}
            },
            "required": ["dataset_id"]
        }
    },
    {
        "task_name": "gcp-dns-managed-zone",
        "display_name": "GCP Cloud DNS Managed Zone",
        "description": "Establish a public or private managed DNS zone in Google Cloud.",
        "category": "network",
        "provider": "gcp",
        "input_schema": {
            "type": "object",
            "properties": {
                "zone_name": {"type": "string"},
                "dns_name": {"type": "string"}
            },
            "required": ["zone_name", "dns_name"]
        }
    },
    {
        "task_name": "gcp-firewall-rule",
        "display_name": "GCP Firewall Policy Rule",
        "description": "Provision ingress/egress network security policy firewall rules on GCP.",
        "category": "security",
        "provider": "gcp",
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_name": {"type": "string"},
                "network": {"type": "string", "default": "default"},
                "allowed_ports": {"type": "array", "items": {"type": "string"}, "default": ["80", "443"]}
            },
            "required": ["rule_name"]
        }
    },
    # --- Kubernetes ---
    {
        "task_name": "kubernetes-pod-deployment",
        "display_name": "K8s App Deployment",
        "description": "Create a rolling-update Kubernetes deployment controller for containers.",
        "category": "compute",
        "provider": "kubernetes",
        "input_schema": {
            "type": "object",
            "properties": {
                "deployment_name": {"type": "string"},
                "image": {"type": "string"},
                "replicas": {"type": "integer", "minimum": 1, "default": 2}
            },
            "required": ["deployment_name", "image"]
        }
    },
    {
        "task_name": "kubernetes-service-loadbalancer",
        "display_name": "K8s Service LoadBalancer",
        "description": "Create a LoadBalancer or ClusterIP service to expose container workloads.",
        "category": "network",
        "provider": "kubernetes",
        "input_schema": {
            "type": "object",
            "properties": {
                "service_name": {"type": "string"},
                "port": {"type": "integer", "default": 80},
                "target_port": {"type": "integer", "default": 8080},
                "type": {"type": "string", "enum": ["ClusterIP", "NodePort", "LoadBalancer"], "default": "ClusterIP"}
            },
            "required": ["service_name"]
        }
    },
    {
        "task_name": "kubernetes-ingress-route",
        "display_name": "K8s Ingress Controller Route",
        "description": "Provision an Ingress routing resource to forward external traffic to services.",
        "category": "network",
        "provider": "kubernetes",
        "input_schema": {
            "type": "object",
            "properties": {
                "ingress_name": {"type": "string"},
                "host_domain": {"type": "string"}
            },
            "required": ["ingress_name", "host_domain"]
        }
    },
    {
        "task_name": "kubernetes-configmap-secrets",
        "display_name": "K8s ConfigMap & Secret Config",
        "description": "Provision local ConfigMap and Base64 encoded Kubernetes secret stores.",
        "category": "security",
        "provider": "kubernetes",
        "input_schema": {
            "type": "object",
            "properties": {
                "config_name": {"type": "string"},
                "data_keys": {"type": "object"}
            },
            "required": ["config_name"]
        }
    },
    {
        "task_name": "kubernetes-persistent-volume",
        "display_name": "K8s Storage Volume Claim (PVC)",
        "description": "Create a PersistentVolumeClaim storage request for cluster containers.",
        "category": "storage",
        "provider": "kubernetes",
        "input_schema": {
            "type": "object",
            "properties": {
                "claim_name": {"type": "string"},
                "storage_size": {"type": "string", "default": "10Gi"}
            },
            "required": ["claim_name"]
        }
    },
    # --- Local / Docker ---
    {
        "task_name": "local-docker-bridge-network",
        "display_name": "Local Docker Bridge",
        "description": "Provision a local bridge Docker network for container isolation.",
        "category": "network",
        "provider": "local",
        "input_schema": {
            "type": "object",
            "properties": {
                "network_name": {"type": "string"}
            },
            "required": ["network_name"]
        }
    },
    {
        "task_name": "local-redis-cache-service",
        "display_name": "Local Redis Container Cache",
        "description": "Deploy a local running Redis cache container using Docker.",
        "category": "database",
        "provider": "local",
        "input_schema": {
            "type": "object",
            "properties": {
                "container_name": {"type": "string", "default": "redis-local"},
                "port_binding": {"type": "integer", "default": 6379}
            },
            "required": ["container_name"]
        }
    },
    {
        "task_name": "local-mongodb-no-sql",
        "display_name": "Local MongoDB Container database",
        "description": "Deploy a local running MongoDB document NoSQL database container.",
        "category": "database",
        "provider": "local",
        "input_schema": {
            "type": "object",
            "properties": {
                "container_name": {"type": "string", "default": "mongo-local"},
                "port_binding": {"type": "integer", "default": 27017}
            },
            "required": ["container_name"]
        }
    }
]

def create_realistic_tasks():
    print(f"Starting population of {len(tasks_data)} realistic tasks...")
    
    with httpx.Client() as client:
        for i, t in enumerate(tasks_data, 1):
            task_name = t["task_name"]
            
            # Form fields
            data = {
                "task_name": task_name,
                "display_name": t["display_name"],
                "description": t["description"],
                "input_schema": json.dumps(t["input_schema"]),
                "category": t["category"],
                "provider": t["provider"],
                "module_version": "1.0.0"
            }
            
            # File script
            files = {
                "script": ("main.tf", b'resource "null_resource" "dummy" {}', "text/plain")
            }
            
            try:
                response = client.post(API_URL, data=data, files=files, headers=HEADERS)
                if response.status_code == 201:
                    print(f"[{i}/50] Created: {task_name} (Category: {t['category']}, Provider: {t['provider']})")
                else:
                    print(f"[{i}/50] Failed to create {task_name}: {response.status_code} - {response.text}")
            except Exception as e:
                print(f"[{i}/50] Error creating {task_name}: {e}")
                
    print("Finished task population.")

if __name__ == "__main__":
    create_realistic_tasks()

