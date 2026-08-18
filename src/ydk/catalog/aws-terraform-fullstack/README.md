# aws-terraform-fullstack

YDK ignition pack that generates production-ready Terraform infrastructure for
full-stack web applications on AWS.

## Overview

This pack produces a complete AWS infrastructure stack via Terraform, covering
compute, database, CDN, networking, state management, and optional
authentication. All generated code uses flat Terraform files (not nested
modules) for readability, and every resource is tagged consistently.

The generated stack:

- **Compute** -- ECS Fargate (backend API containers)
- **Database** -- Aurora Serverless v2 (PostgreSQL)
- **CDN** -- CloudFront distribution (S3 frontend + ALB API origin)
- **Auth** -- Cognito User Pool (optional, only generated when configured)
- **Networking** -- VPC with public/private subnets, NAT Gateway
- **State** -- S3 + DynamoDB for Terraform state locking

### Key Design Decisions

- Flat Terraform files for better readability of generated code.
- Single CloudFront distribution serving both frontend and API.
- Aurora Serverless v2 (no RDS Proxy needed -- avoids cost trap).
- Single NAT Gateway by default (cost-conscious), with HA option.
- Auth is optional -- only generated when `auth.provider` is set to `cognito`.
- Terraform AWS provider ~> 5.0.

---

## Inputs

This pack consumes standard YDK component types. Both are optional -- the pack
can generate infrastructure from its own `infrastructure.yaml` fixture alone.

| Component Type | Schema Ref                  | Version   | Required |
|----------------|-----------------------------|-----------|----------|
| entity         | ydk-core-schemas/entity     | >= 1.0.0  | No       |
| crosscut       | ydk-core-schemas/crosscut   | >= 1.0.0  | No       |

---

## Architecture

```
                    CloudFront CDN
                   (unified domain, TLS termination)
                    /            \
              S3 Bucket        ALB
              (frontend)     (API origin)
                                |
                         ECS Fargate Service
                        (private subnet, autoscale)
                                |
                         Aurora Serverless v2
                        (private subnet, encrypted)
```

A single CloudFront distribution sits in front of the entire application:

- The **default behavior** routes to an S3 bucket that hosts the frontend SPA.
- The `/api/*` path pattern routes to an Application Load Balancer origin
  that fronts the ECS Fargate service.
- ECS tasks run in private subnets and connect to an Aurora Serverless v2
  cluster, also in private subnets.
- All traffic between tiers flows through least-privilege security groups.

---

## Networking

### VPC Layout

| Component        | Placement       | Details                            |
|------------------|-----------------|------------------------------------|
| VPC              | --              | Custom CIDR (default 10.0.0.0/16)  |
| Public subnets   | 2 AZs           | ALB, NAT Gateway                   |
| Private subnets  | 2 AZs           | ECS Fargate tasks, Aurora cluster  |
| NAT Gateway      | Public subnets  | Single (default) or HA (one per AZ)|

### Security Groups

All security groups follow least-privilege rules:

- **ALB SG** -- allows inbound HTTPS (443) from the internet; outbound only to
  ECS SG on the container port.
- **ECS SG** -- allows inbound from ALB SG on the container port only; outbound
  to Aurora SG on port 5432 and to NAT Gateway for external calls.
- **Aurora SG** -- allows inbound from ECS SG on port 5432 only; no other
  inbound or outbound rules.

Traffic path: `Internet -> ALB -> ECS -> Aurora` (no shortcuts).

---

## Compute (ECS Fargate)

- **Task definition** with configurable CPU (256--4096 units) and memory
  (512--8192 MB).
- **Application Load Balancer** with health checks on a configurable endpoint
  (default `/health`).
- **ECR repository** for container images.
- **CloudWatch log group** for container stdout/stderr.
- **Auto-scaling** with configurable min/max task count and CPU threshold
  (default 70%).
- **Desired count** defaults to 2 tasks for availability.

---

## Database (Aurora Serverless v2)

- **Engine:** PostgreSQL (default version 15.4).
- **Scaling:** Configurable min/max ACU (default 0.5--4 ACU). Scales to near
  zero when idle.
- **Encryption:** At rest via KMS.
- **Network:** Deployed in private subnets only; accessible exclusively from
  the ECS security group.
- **Backups:** Automatic backups with configurable retention (default 7 days).
- **Deletion protection:** Enabled by default in production environments.

---

## CDN (CloudFront)

- **Single distribution** with two origins:
  - **S3** (default behavior) -- serves the frontend SPA.
  - **ALB** (path pattern `/api/*`) -- proxies to the backend.
- **Origin Access Control (OAC)** for S3 -- the bucket is never publicly
  accessible; CloudFront uses OAC to fetch objects.
- **HTTPS only** -- viewer protocol policy redirects HTTP to HTTPS.
- **TLS 1.2 minimum** enforced on the distribution.
- **Price class** configurable (`PriceClass_100`, `PriceClass_200`,
  `PriceClass_All`).
- **Custom error responses** configurable (e.g., 404 -> index.html for SPA
  routing).

---

## Authentication (Optional)

Generated only when `auth.provider` is set to `cognito`. When the provider is
`none` or absent, the auth generator produces an empty file.

- **Cognito User Pool** with configurable password policy:
  - Minimum length
  - Require uppercase, lowercase, numbers, symbols
- **MFA** support: `off`, `optional`, or `required`.
- **App client** for frontend integration.
- **Custom domain** support.

---

## State Management

Terraform state is stored remotely to enable team collaboration and prevent
state conflicts:

- **S3 bucket** for state storage (versioning enabled, server-side encryption).
- **DynamoDB table** for state locking (prevents concurrent modifications).
- **Bootstrap script** (`bootstrap.sh`) creates the state resources before the
  first `terraform apply`. Run this once per environment.

---

## Tagging Strategy

All generated resources include the following tags:

| Tag          | Value                    | Purpose                          |
|--------------|--------------------------|----------------------------------|
| `Name`       | Resource identifier      | Human-readable resource naming   |
| `Environment`| `dev` / `staging` / `prod` | Distinguish deployment stages  |
| `Project`    | Application name         | Group resources by project       |
| `ManagedBy`  | `terraform`              | Identify IaC-managed resources   |

The `check_tagging.sh` enforcement script verifies that all taggable resources
include these tags.

---

## Generators

Each generator reads the infrastructure configuration and produces Terraform
files in `infra/`. All generators are idempotent -- re-running produces the
same output.

| Generator      | Output Files                      | Description                                       |
|----------------|-----------------------------------|---------------------------------------------------|
| tf_state       | `state.tf`, `bootstrap.sh`        | S3 backend + DynamoDB lock table                   |
| tf_networking  | `networking.tf`                   | VPC, subnets, NAT Gateway, security groups         |
| tf_compute     | `compute.tf`                      | ECS Fargate, ALB, ECR, IAM roles, CloudWatch logs  |
| tf_database    | `database.tf`                     | Aurora Serverless v2 cluster                        |
| tf_cdn         | `cdn.tf`                          | CloudFront distribution + S3 frontend bucket        |
| tf_auth        | `auth.tf`                         | Cognito User Pool (conditional on auth.provider)    |
| tf_variables   | `variables.tf`, `terraform.tfvars`| Variable declarations and values                    |
| tf_outputs     | `outputs.tf`                      | Output values (URLs, ARNs, endpoints)               |
| deploy_script  | `deploy.sh`                       | Deployment automation (plan, apply, build, push)    |

Generator source files live in `generators/`. Jinja2 templates live in
`templates/`.

---

## Enforcement Rules

This pack includes 8 enforcement scripts in `enforcements/infra/`. They run
automatically on the following triggers:

- `file_write` / `file_create` -- when `.tf` or `.sh` files are modified
- `pre_commit` -- before git commits
- `on_demand` -- when explicitly requested via `ydk verify`

Path filters: `infra/**/*.tf`, `*.sh`

### check_security.sh (checkov-based)

Runs [checkov](https://www.checkov.io/) with a curated set of AWS security
checks targeting critical misconfigurations.

| Category                          | Check IDs                                  | What It Detects                                                    |
|-----------------------------------|--------------------------------------------|--------------------------------------------------------------------|
| S3 public access                  | CKV_AWS_20, 21, 54, 55, 56, 57, 93        | Public ACLs, missing public access blocks, public bucket policies  |
| SQS/SNS public policies           | CKV_AWS_27, 26                             | Publicly accessible queues and topics                              |
| KMS key rotation and access       | CKV_AWS_7, 33                              | Disabled key rotation, overly permissive key policies              |
| Lambda public access              | CKV_AWS_45, 115, 173, 260                  | Public Lambda functions, missing resource-based policy restrictions |
| Security groups wide-open         | CKV_AWS_23, 24, 25                         | Ingress from 0.0.0.0/0 on sensitive ports                         |
| IAM overly permissive             | CKV_AWS_290, 60, 61                        | Wildcard actions, overly broad resource permissions                |
| RDS/EBS public snapshots/IAM auth | CKV_AWS_118, 129, 46, 74, 134              | Public snapshots, missing IAM authentication                       |
| Elasticsearch public access       | CKV_AWS_5, 84, 137                         | Public domains, missing encryption, missing logging                |

**How to fix:** Run `checkov --directory infra/ --check <CHECK_ID>` for
detailed guidance on each violation.

### check_paravirt_ec2.sh

**Detects:** Paravirtualized EC2 instance types (`t1.*`, `m1.*`, `c1.*`,
`m2.*`) in `.tf` files.

**Why it matters:** These legacy instance types use paravirtualization and lack
modern security features (NitroTPM, EBS encryption by default, IMDSv2
enforcement). They are also end-of-life and receive no new patches.

**How to fix:** Replace with current-generation HVM instance types (`t3.*`,
`m5.*`, `c5.*`, etc.).

### check_external_iam.sh

**Detects:** Wildcard IAM principals (`Principal: "*"`) in assume-role policies
within `.tf` files.

**Why it matters:** A wildcard principal allows any AWS entity -- any account,
any service, any user -- to assume the role. This is a privilege escalation
vector that can be exploited cross-account.

**How to fix:** Restrict principals to specific AWS account IDs, service
principals (`ecs-tasks.amazonaws.com`), or IAM ARNs.

### check_public_ami.sh

**Detects:** `data "aws_ami"` blocks without an `owners` restriction, and
hardcoded AMI IDs without corresponding data-source lookups.

**Why it matters:** Without `owners` specified, AMI lookups may return
community AMIs from untrusted third parties, potentially containing malware or
backdoors.

**How to fix:** Add `owners = ["amazon", "self"]` (or your organization's
account ID) to all `data "aws_ami"` blocks. Prefer data-source lookups over
hardcoded AMI IDs.

### check_dangling_resources.sh

**Detects:** Route53 alias records and CloudFront origins pointing to S3
buckets or AWS endpoints not defined as resources in the codebase. Also flags
hardcoded AWS domain names in CloudFront origin configurations.

**Why it matters:** Dangling DNS records and CDN origins can be hijacked by
attackers who create the target resource (e.g., an S3 bucket with the expected
name) in their own account -- a subdomain takeover attack.

**How to fix:** Use Terraform resource references
(`aws_s3_bucket.x.bucket_regional_domain_name`) instead of hardcoded domain
names. Ensure all referenced S3 buckets and origins are defined in your code.

### check_glacier_public.sh

**Detects:** Glacier vaults with wildcard principals (`*`) in access policies.

**Why it matters:** A Glacier vault with `Principal: "*"` in its access policy
allows anyone on the internet to read your archived data.

**How to fix:** Restrict `access_policy` principals to specific AWS accounts or
IAM roles.

### check_tf_format.sh

**Detects:** Terraform files that are not properly formatted according to
`terraform fmt`.

**Why it matters:** Consistent formatting makes code reviews easier, reduces
merge conflicts, and ensures generated code matches Terraform conventions.

**How to fix:** Run `terraform fmt -recursive infra/`.

### check_tagging.sh

**Detects:** Terraform resources missing required tags (`Environment`,
`Project`, `ManagedBy`). Skips resources that do not support tags (e.g.,
`aws_iam_role_policy_attachment`, `aws_route_table_association`).

**Why it matters:** Consistent tagging is essential for cost allocation,
security auditing, and automated resource management. Untagged resources become
orphans that are difficult to attribute or manage at scale.

**How to fix:** Add a `tags` block to every taggable resource with at minimum
`Environment`, `Project`, and `ManagedBy` keys.

---

## Quick Start

### 1. Generate infrastructure

```bash
ydk generate
```

This produces Terraform files in `infra/` and a `deploy.sh` script at the
project root.

### 2. Bootstrap state management (run once per environment)

```bash
cd infra && bash bootstrap.sh
```

Creates the S3 bucket and DynamoDB table used for Terraform state.

### 3. Initialize and plan

```bash
terraform init
terraform plan
```

Review the plan output to verify resources before applying.

### 4. Set required secrets

```bash
export TF_VAR_db_password="your-secure-password"
```

### 5. Apply infrastructure

```bash
terraform apply
```

### 6. Deploy the application

```bash
cd .. && bash deploy.sh
```

The deploy script handles Docker image build, ECR push, ECS service update, and
CloudFront cache invalidation.

### 7. Run enforcement checks

```bash
ydk verify
```

---

## Prerequisites

| Tool       | Version   | Purpose                                 | Install                         |
|------------|-----------|-----------------------------------------|---------------------------------|
| Terraform  | >= 1.5    | Infrastructure as code                  | https://terraform.io/downloads  |
| AWS CLI    | v2        | AWS credential configuration            | `brew install awscli`           |
| Docker     | Latest    | Building backend container images       | https://docker.com              |
| checkov    | Latest    | Infrastructure security scanning        | `pip install checkov`           |

### AWS Permissions

The AWS credentials used must have the following managed policies (or
equivalent custom permissions):

- `AmazonVPCFullAccess`
- `AmazonECS_FullAccess`
- `AmazonRDSFullAccess`
- `CloudFrontFullAccess`
- `AmazonS3FullAccess`
- `IAMFullAccess`
- `AmazonECRFullAccess`
- `AmazonCognitoPowerUser` (if using auth)
- `DynamoDBFullAccess` (for state locking)

### Cost Estimate

Default configuration (single NAT, small Fargate, Aurora min 0.5 ACU):

| Component          | Estimated Monthly Cost |
|--------------------|------------------------|
| NAT Gateway        | ~$32 (single), ~$64 (HA) |
| Aurora Serverless  | Scales to near zero when idle (0.5 ACU minimum) |
| ECS Fargate        | Depends on task size and count |
| CloudFront         | Pay per request (free tier covers most dev usage) |
| **Dev total**      | **~$100--150/month**   |
