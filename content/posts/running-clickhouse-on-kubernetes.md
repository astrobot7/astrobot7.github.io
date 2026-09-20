+++
date = '2026-09-20T22:18:23+05:30'
draft = false
title = 'Running Clickhouse on Kubernetes: From Zero to a Replicated Production-Ready Cluster'
author = 'Aswin KM'
+++
Running ClickHouse on Kubernetes manually can quickly become cumbersome: managing StatefulSets, maintaining topology layouts, handling persistent storage mappings, and orchestrating replication coordinators requires significant operational overhead.

The Altinity ClickHouse Operator simplifies this by introducing Custom Resource Definitions (CRDs) that automate ClickHouse provisioning, configuration, scaling, and lifecycle management.

This hands-on guide walks you through provisioning a local multi-node Kubernetes environment, deploying the Altinity operator, and progressively building a persistent, replicated ClickHouse cluster.   

## Prerequisites
To follow along locally, ensure you have the following installed:
* kubectl
* helm
* kind (Kubernetes in Docker)  

Because we will deploy a replicated topology with ZooKeeper, configure a Kind cluster with multiple worker nodes. Save the following configuration as cluster.clickhouse-operator.yaml:  

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
  - role: worker
  - role: worker
```
> While the YAML above specifies two worker nodes, you can add a third worker node entry (- role: worker) if you wish to guarantee dedicated node scheduling across all components.

Bootstrap the cluster:
```sh
kind create cluster --config cluster.clickhouse-operator.yaml --name clickhouse-operator
```

Ensure your context points to the new Kind cluster:
```sh
kubectl config current-context
# Output should return: kind-clickhouse-operator
```

## Installing the Altinity ClickHouse Operator
Install the operator into its own dedicated namespace using the official Altinity Helm chart:
```sh
helm repo add altinity https://helm.altinity.com
helm repo update altinity

helm upgrade --install clickhouse-operator \
  altinity/altinity-clickhouse-operator \
  --version 0.27.3 \
  --namespace clickhouse \
  --create-namespace
```
This installation deploys the foundational components into your Kubernetes cluster:
* CRDs: clickhouseinstallations.clickhouse.altinity.com (chi), clickhouseinstallationtemplates, clickhousekeeperinstallations (chk), and clickhouseoperatorconfigurations.
* RBAC & Workload: The clickhouse-operator ServiceAccount, ClusterRoleBinding, and Deployment controller.   

## Provisioning a Basic ClickHouse Instance
To deploy ClickHouse, define a ´ClickHouseInstallation´ (abbreviated chi) custom resource. Save this manifest as clickhouseinstallation.cluster01.yaml:
```yaml
apiVersion: "clickhouse.altinity.com/v1"
kind: "ClickHouseInstallation"
metadata:
  name: cluster01
spec:
  templates:
    podTemplates:
      - name: clickhouse-pod-template
        spec:
          containers:
            - name: clickhouse
              image: altinity/clickhouse-server:25.8.16.10002.altinitystable
  configuration:
    clusters:
      - name: cluster01
        layout:
          shardsCount: 1
          replicasCount: 1
        templates:
          podTemplate: clickhouse-pod-template
```

Apply the manifest:
```sh
kubectl apply -n clickhouse -f clickhouseinstallation.cluster01.yaml
```

Monitor the deployment until the status turns to Completed:
```sh
kubectl get chi -n clickhouse
```

```markdown
NAME        STATUS      CLUSTERS   HOSTS   HOSTS-COMPLETED   AGE   SUSPEND 
cluster01   Completed   1          1       1                 72s
```

Verify the installation by opening an interactive clickhouse-client session inside the pod:
```sh
kubectl exec -it chi-cluster01-cluster01-0-0-0 -n clickhouse -- clickhouse-client
```

Inside the client shell, query the system tables to inspect cluster metadata:
```markdown
┌─cluster────────┬─host_name───────────────────┬─port─┐
│ all-clusters   │ chi-cluster01-cluster01-0-0 │ 9000 │
│ all-replicated │ chi-cluster01-cluster01-0-0 │ 9000 │
│ all-sharded    │ chi-cluster01-cluster01-0-0 │ 9000 │
│ cluster01      │ chi-cluster01-cluster01-0-0 │ 9000 │
│ default        │ localhost                   │ 9000 │
└────────────────┴─────────────────────────────┴──────┘
```

## Enabling Persistent Storage
The initial setup uses ephemeral storage: restarting the pod or rescheduling it after a node failure causes immediate data loss.

To persist ClickHouse data across pod lifecycles, configure a volumeClaimTemplates block mapped to /var/lib/clickhouse. Save this as clickhouseinstallation.cluster02.yaml:
```yaml
apiVersion: "clickhouse.altinity.com/v1"
kind: "ClickHouseInstallation"
metadata:
  name: cluster02
spec:
  templates:
    podTemplates:
      - name: clickhouse-pod-template
        spec:
          containers:
            - name: clickhouse
              image: altinity/clickhouse-server:25.8.16.10002.altinitystable
              volumeMounts:
                - name: clickhouse-storage
                  mountPath: /var/lib/clickhouse
    volumeClaimTemplates:
      - name: clickhouse-storage
        reclaimPolicy: Retain
        spec:
          accessModes:
            - ReadWriteOnce
          resources:
            requests:
              storage: 5Gi
          storageClassName: standard
  configuration:
    clusters:
      - name: cluster01
        layout:
          shardsCount: 1
          replicasCount: 1
        templates:
          podTemplate: clickhouse-pod-template
```

Apply the updated configuration:
```sh
kubectl apply -n clickhouse -f clickhouseinstallation.cluster02.yaml
```

Check the newly bound PersistentVolume:
```sh
kubectl get pv
```

```markdown
NAME                                       CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS   CLAIM                                                           STORAGECLASS   AGE
pvc-87e9d931-f42d-41ad-9582-ef7ed27c0395   5Gi        RWO            Delete           Bound    clickhouse/clickhouse-storage-chi-cluster02-cluster02-0-0-0     standard       5m31s
```

With persistent volumes attached, pods can be restarted or rescheduled without dropping committed data.

## Building a High-Availability Replicated Topology
Single-instance deployments do not provide high availability, failover capabilities, or zero-downtime rolling upgrades. ClickHouse data replication relies on a distributed consensus engine—either ClickHouse Keeper or Apache ZooKeeper.

### Step 1: Deploy a 3-Node ZooKeeper Quorum

Deploy an isolated 3-node ZooKeeper cluster using Altinity's quick-start manifests:
```sh
kubectl apply -f https://raw.githubusercontent.com/Altinity/clickhouse-operator/release-0.26.3/deploy/zookeeper/zookeeper-manually/quick-start-persistent-volume/zookeeper-3-nodes.yaml -n clickhouse
```
Ensure all three ZooKeeper pods reach the Running state:
```sh
kubectl get pods -n clickhouse -l app=zookeeper
```

```markdown
NAME          READY   STATUS    RESTARTS   AGE
zookeeper-0   1/1     Running   0          2m35s
zookeeper-1   1/1     Running   0          115s
zookeeper-2   1/1     Running   0          74s
```

### Step 2: Deploy the Replicated Cluster
Define the replicated ClickHouse cluster. This layout creates 1 shard with 2 replicas, tying into the internal ZooKeeper service endpoint (zookeeper.clickhouse.svc.cluster.local:2181) for distributed coordination.

Save this manifest as clickhouseinstallation.cluster03.yaml:  
```yaml
apiVersion: "clickhouse.altinity.com/v1"
kind: "ClickHouseInstallation"
metadata:
  name: cluster03
spec:
  templates:
    podTemplates:
      - name: clickhouse-pod-template
        spec:
          containers:
            - name: clickhouse
              image: altinity/clickhouse-server:25.8.16.10002.altinitystable
              volumeMounts:
                - name: clickhouse-storage
                  mountPath: /var/lib/clickhouse
    volumeClaimTemplates:
      - name: clickhouse-storage
        reclaimPolicy: Retain
        spec:
          accessModes:
            - ReadWriteOnce
          resources:
            requests:
              storage: 5Gi
          storageClassName: standard
  configuration:
    zookeeper:
      nodes:
        - host: zookeeper.clickhouse.svc.cluster.local
          port: 2181
    clusters:
      - name: cluster03
        layout:
          shardsCount: 1
          replicasCount: 2
        templates:
          podTemplate: clickhouse-pod-template
```
Deploy the cluster:
```sh
kubectl apply -n clickhouse -f clickhouseinstallation.cluster03.yaml
```

### Step 3: Validate Active Replication

Once the operator provisions both replica instances, start a client session on the second replica:

```sh
kubectl exec -it chi-cluster03-cluster03-0-1-0 -n clickhouse -- clickhouse-client
```

Inspect the replication layout from system.clusters:
```sql
SELECT
    cluster,
    shard_num,
    replica_num,
    host_name,
    host_address
FROM system.clusters
WHERE cluster = 'cluster03';
```
```markdown
┌─cluster───┬─shard_num─┬─replica_num─┬─host_name───────────────────┬─host_address─┐
│ cluster03 │         1 │           1 │ chi-cluster03-cluster03-0-0 │ 10.244.4.5   │
│ cluster03 │         1 │           2 │ chi-cluster03-cluster03-0-1 │ 127.0.0.1    │
└───────────┴───────────┴─────────────┴─────────────────────────────┴──────────────┘
```

The distinct replica_num values verify that both hosts participate in the same shard under active replication. You now have a resilient ClickHouse deployment capable of surviving node restarts, handling rolling maintenance, and serving queries across multiple replicas.

## Summary
By deploying the Altinity ClickHouse Operator, managing complex columnar database topologies on Kubernetes shifts from manual configuration drift to declarative, automated operations. You started with a basic single-node setup, introduced persistent storage volumes to safeguard state across restarts, and scaled into a fault-tolerant multi-replica cluster coordinated by ZooKeeper.

From here, you can adapt this architecture for production by tuning resource requests and limits, introducing ClickHouse Keeper via the operator’s dedicated CRDs as a lightweight alternative to ZooKeeper, and adding sharding topologies as your analytical throughput demands scale.
