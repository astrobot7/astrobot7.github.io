+++
date = '2026-06-15T18:35:44+05:30'
draft = false
title = 'Scaling Metrics Past the Limits of Prometheus Federation with Mimir'
author = 'Aswin KM'
+++

If you manage a growing multi-cluster Kubernetes environment, there comes a day when your central monitoring infrastructure starts to groan under its own weight. For us, that day arrived when our central, federated Prometheus instances began repeatedly throwing Out-Of-Memory (OOM) errors during heavy query loads.

Prometheus is phenomenal for single-cluster monitoring. However, scaling it across dozens of regions and clusters using traditional **Prometheus Federation** eventually hits a hard wall.

This post details why we abandoned our federated pull architecture and migrated our entire global metrics pipeline to Grafana Mimir—without losing historical data, and while drastically slashing our storage costs.

## The Breaking Point of Hierarchical Federation
In our old setup, we ran a pair of local Prometheus instances in every application cluster to scrape workloads. We then stood up a pair of massive, centralized "Global" Prometheus instances that scraped the /federate endpoint of every downstream cluster to aggregate core operational metrics.

![Legacy Prometheus Architecture](/images/mimir-migration/federation.png)

This structural pattern works fine at a small scale, but as our engineering organization expanded beyond a million metrics being ingested per minute, three systemic issues paralyzed our monitoring stack:

* The Monolithic Single Point of Failure (SPOF): Our global Prometheus was a pair of massive virtual machine running on expensive block storage (SSD). If those nodes got restarted or replayed its Write-Ahead Log (WAL), we were blind globally for a period of time.

* The High-Cardinality Exploding Scrape: When developers spun up dynamic microservices with unique container IDs or ephemeral labels, the data payload crossing the network via /federate caused frequent timeout failures and dropped metrics.

* The Compute/Storage Disconnect: To handle 30-day or 90-day retention queries, we had to scale up the entire global Prometheus instance's CPU and RAM just to support the storage footprint—even if query traffic was low.

## Enter Grafana Mimir: Moving from Pull to Push

We needed an architecture that separated ingestion from querying and decoupled compute from long-term storage. After evaluating alternative tools like Thanos and Cortex, we selected Grafana Mimir because of its modular, cloud-native microservices layout. It also incorporated a lot of useful features of both Thanos and Cortex into a single package.

### The Architectural Advantage

* Distributors & Ingesters: Mimir separates incoming write traffic across lightweight worker pools. If write traffic spikes, we horizontally scale the distributors and when the traffic goes down we scale down the distributors to save cost.

* Pure Object Storage: Mimir compiles metric time-series blocks and dumps them directly into cheap, durable cloud object storage (like Google Cloud Storage or AWS S3). We swapped expensive block storage SSDs for virtually infinite, low-cost GCS buckets.

* Isolated Query Engines: When a user opens a Grafana dashboard, the request hits a dedicated Query Frontend microservice. Heavy historical queries can crunch data over weeks without ever interfering with or slowing down the real-time data ingestion path. We also added horizontal autoscaling to the query path so that users won't get starved for resources while a huge query is running.

### Mimir Ingestion Architecture
Instead of a heavy central scraper pulling data, Mimir relies on a push model. We converted our edge Prometheus instances into lightweight Prometheus instance with much shorted retention. they immediately stream metrics out using the `remote_write` protocol.

Only a short amount of repeatedly queried metrics needs to be kept in the ingesters for faster queries, the long term retention of metrics is handed off to cheaper cloud storage buckets. This allowed us to increase our retention for 90 days to 365 days without incuring a huge performance hit like you would in the legacy prometheus setup.

![Mimir Ingestion Architecture Diagram](/images/mimir-migration/write-path.svg)

### Mimir Query Architecture
Instead of the same prometheus servers handling both the ingestion and querying of data on single machine, mimir lets you split the queries into multiple smaller **shards** which can be individually queried in parallel.

The short term queries(until 24 hours) is handled by the **ingester** and any queries beyond that is handled by the **store gateway** component which can be scaled based on the usage. This allowed us to query the whole 365 days worth of metrics without a glitch.

![Mimir Query Architecture Diagram](/images/mimir-migration/read-path.svg)

## infrastructure as Code: Migration Blueprint
Because our team operates strictly through GitOps, we wanted the entire Mimir topology, tenant definitions, and bucket configurations declared via [Google Config Connector](https://docs.cloud.google.com/config-connector/docs/overview) and Helm Manifests.

On the ingestion side, ie; edge prometheus servers on kubernetes clusters and GCP VMs, the `remote_write` paths were added to start sending the traffic to mimir once the endpoints were ready.

## High Availability Concerns
In every important production systems while deciding on a new tool, it's paramount to ensure the availability of the tool during outages. Since zonal outages are becoming more and more common, we had to take that into consideration while deciding on the deployment method of Mimir.

Thankfully, mimir supports series sharding and replication out of the box, this was a huge win when compared to the previous setup. We managed to setup a production with 3 replicas across 3 zones in GCP.

The included **rollout-operator** components that comes with the [mimir helmchart](https://github.com/grafana/mimir/blob/main/operations/helm/charts/mimir-distributed/README.md) ensures that the deployment are rolled out in a way that it ensures highest availablility by doing deployments in one zone at a time.

## Lessons Learned & Production Realities

Migrating a core infrastructure component at scale always reveals a few surprises. If you are planning a similar migration, keep these two operational notes in mind:

* Watch Your Churn Rate: Because Mimir tracks metrics globally, high-cardinality labels (like putting an explicit timestamp or unique UUID into a metric label) can cause Mimir's ingester memory to spike. Enforce strict metric relabeling rules at the agent level to drop garbage labels before they cross the wire.

* The Compactor is Critical: The Mimir Compactor component is responsible for deduplicating data blocks sent by multiple replicas. Ensure you assign sufficient CPU and disk space to your compactor nodes, or your query speeds will degrade over long time ranges.

## The Final Verdict

By shifting from Prometheus Federation to Grafana Mimir, we turned our global monitoring infrastructure from a brittle, scary monolith into an elastic system that behaves like any other stateless microservice app.

Our metrics data costs dropped by over 60% due to object storage utilization, our dashboard query load times dropped significantly, and our infrastructure engineering team no longer gets paged in the middle of the night because a Prometheus disk filled up.
