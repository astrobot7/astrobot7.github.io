---
title: ""
description: "Infrastructure engineer with 9 years of experience in GCP and Kubernetes."
---
# About Me

Hi, I'm Aswin. I build and run the platforms other engineers deploy to: Kubernetes clusters, cloud infrastructure, and the automation that keeps both boring in the best way. I've done this for nine years, most of them at Truecaller in Stockholm. I've since moved back home to Kochi, Kerala, and I'm looking for the right next role.

[Resume (PDF)](/documents/resume.pdf) · [LinkedIn](https://www.linkedin.com/in/aswin-km) · [GitHub](https://github.com/astrobot7) · [Email](mailto:dev.aswinkm@gmail.com)

## Things I've Built

- Kubernetes operators for ScyllaDB and Redis that handle setup, configuration and day-2 operations, with an end-to-end test framework that runs them in GitHub CI before anything reaches production.
- Truecaller's move from on-prem to GCP, which I contributed to, and the migration of the payments platform from AWS to GCP, which I led.
- A company-wide rollout of Grafana Mimir after a proof of concept, replacing Prometheus federation that had hit its limits. I [wrote about it here]({{< relref "posts/mimir-migration" >}}).
- A move from self-managed Istio to Anthos Service Mesh, which took mesh upgrades off the team's plate.
- GitOps for infrastructure with Config Sync and Config Connector, Terraform for everything on GCP, and Ansible to stop configuration drift.
- A Hadoop/HDFS orchestration in Python that replaced Dataproc and saved a good chunk of the bill.

Along the way I ran Cassandra, ScyllaDB, MongoDB, Redis, Elasticsearch and Memcached in production, took my share of on-call, and interviewed and onboarded a good number of engineers.

## Off the Clock

My homelab is where I try things before I'd recommend them to anyone. It's a handful of small machines across two sites, running k3s with Flux and Renovate, and it has already been through one full migration off Docker Swarm. The [homelab posts](/categories/homelab/) cover what worked and what didn't.

Away from the keyboard I'm usually trekking or planning the next trip.

## Toolbox

| Area | Tools |
|---|---|
| Cloud | GCP, AWS |
| Kubernetes | GKE, k3s, operators in Go, Config Connector, Argo CD, Flux |
| Infrastructure as code | Terraform, Ansible, Chef, cloud-init |
| Observability | Grafana stack and Mimir, ELK, Splunk, Cloud Monitoring |
| Data | Cassandra, ScyllaDB, PostgreSQL, MongoDB, Redis, ClickHouse |

## Work With Me

I'm open to senior infrastructure and platform roles, and to consulting on GCP and Kubernetes: migrations, cluster design, GitOps and observability. Email or LinkedIn is the fastest way to reach me.
