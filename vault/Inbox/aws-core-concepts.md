---
title: "AWS Core Concepts"
tags:
  - aws
  - cloud-computing
  - infrastructure
  - devops
  - overview
created: 2026-06-22
folder: Inbox
---

## Summary
AWS provides on-demand cloud computing services like servers, storage, and databases over the internet, letting you scale resources instantly without managing physical hardware. You pay only for what you use, which reduces upfront costs and increases agility for development and operations.

## Global Infrastructure
- **Regions**: Large geographic areas (e.g., `us-east-1`) containing multiple isolated data centers.
- **Availability Zones (AZs)**: Distinct data centers within a region, connected by low-latency links for fault tolerance.
- **Edge Locations**: Nodes distributed globally for caching content closer to users (CloudFront).

```mermaid
mindmap
  classDef neutral fill:#ADD8E6,stroke:#00008B,stroke-width:2px;
  root((AWS Infrastructure)):::neutral
    Regions
      Geographic boundaries
      Data residency compliance
      [[us-east-1]]
      [[eu-west-2]]
    Availability Zones
      Independent data centers
      Power/Cooling isolation
      Failover capability
    Edge Locations
      Content Delivery Network
      Reduced latency
      Global reach
```

## Core Service Categories
| Category | Key Services | Use Case |
| :--- | :--- | :--- |
| **Compute** | EC2, Lambda, ECS | Run code, containers, serverless functions |
| **Storage** | S3, EBS, EFS | Object storage, block volumes, file shares |
| **Database** | RDS, DynamoDB, Aurora | Relational DBs, NoSQL, managed engines |
| **Networking** | VPC, Route 53, CloudFront | Isolated networks, DNS, CDN |
| **Security** | IAM, KMS, GuardDuty | Identity management, encryption, threat detection |

## Shared Responsibility Model
> [!IMPORTANT] Security Split
> AWS secures the **cloud** (hardware, software, facilities). You secure **in** the cloud (data, access, OS patching).

- **AWS Responsibility**: Global infrastructure, hardware, host OS, network fabric.
- **Customer Responsibility**: Guest OS, data encryption, IAM policies, firewall configs.

## Pricing Models
| Model | Best For | Cost Profile |
| :--- | :--- | :--- |
| **On-Demand** | Unpredictable workloads | Highest price, pay-per-second |
| **Reserved** | Steady-state usage | Up to 72% discount, 1-3 yr commitment |
| **Spot** | Fault-tolerant, flexible jobs | Up to 90% discount, instances can be interrupted |

> [!WARNING] Cost Gotchas
> - Data transfer out costs can exceed compute costs.
> - Unattached EBS volumes and idle NAT Gateways drain budget silently.

## Quick Architecture Pattern
> [!NOTE] Excalidraw: Sketch a 3-tier web app: S3/CloudFront -> API Gateway -> Lambda -> RDS/Aurora, highlighting public vs private subnets.