+++
date = '2026-07-23T17:18:05+05:30'
draft = false
title = 'Under the Hood of K8s: What Kubernetes The Hard Way + Vagrant Taught Me About Networking and Control Planes'
author = 'Aswin KM'
+++

If you’ve worked with cloud-native applications over the last few years, chances are you’ve interacted with Kubernetes. Whether it’s spinning up an Amazon EKS cluster with a single terraform apply, provisioning Google GKE from a console, or running minikube start locally, modern tooling has made running container orchestrators deceptively easy.

And that’s precisely the problem.

Managed Kubernetes services and abstraction tools handle the heavy lifting: generating TLS certificates, configuring systemd service files, bootstrapping etcd consensus groups, and setting up Pod network routing behind the scenes. While this developer experience is incredible for day-to-day productivity, it creates a massive knowledge gap. When a worker node drops off the grid, an API server refuses to authorize requests, or a service fails to route traffic, abstract tools won't help you debug what's happening under the hood.

To bridge this gap, Kelsey Hightower created the legendary guide Kubernetes The Hard Way (KTHW).

## Why KTHW?

The premise of Kubernetes The Hard Way is simple: no automated scripts, no kubeadm, no cloud provider shortcuts. You manually provision every binary, write every config file by hand, generate every certificate authority, and wire together every networking route from scratch.

By doing it manually, you realize that Kubernetes isn't a monolithic magic engine—it is simply a collection of small, independent Go binaries talking to each other over HTTP/TLS interfaces.

## Why Bring It Down to Vagrant?

Kelsey’s original guide relies heavily on Google Cloud Platform (GCP) to handle compute instances, static public IPs, and cloud routes. While GCP is great, setting it up locally using Vagrant and virtualized infrastructure adds a whole new dimension to the challenge:

* Zero Cloud Costs: You can tear down, break, and rebuild the cluster a hundred times on your local machine without incurring cloud billing surprises.

* True Bare-Metal Feeling: You deal directly with hypervisor interfaces, private network adapters (host-only), local IP routing tables, and real-world network constraints.

* Hyper-Focus on Networking: In a cloud environment, virtual networks handle subnet routing automatically. With Vagrant, you have to explicitly manage multi-NIC network bindings, Pod CIDR routes, and local DNS resolution yourself.

In this post, I’ll walk you through my journey of adapting Kubernetes The Hard Way to a local Vagrant environment, the architecture I settled on, the critical "Aha!" moments along the way, and—most importantly—the painful edge cases and networking trapdoors that almost drove me crazy.

# Local Hypervisor Setup

Before writing a Vagrantfile or downloading Kubernetes binaries, you need a local hypervisor that can comfortably spin up multiple lightweight VMs.While VirtualBox is the default provider for Vagrant, KVM (Kernel-based Virtual Machine) combined with libvirt is the gold standard for running Linux-on-Linux labs. 

Because KVM runs directly inside the Linux kernel, VM overhead is minimal, RAM footprint is reduced, and network throughput between virtual machines is significantly faster.

## Step 1: Verify Hardware Virtualization
First, ensure your CPU supports hardware virtualization extensions (Intel VT-x or AMD-V):  
```bash
grep -E -c '(vmx|svm)' /proc/cpuinfo
```
Note: If this command outputs 0, you need to enable Virtualization Technology (VT-x/AMD-V) in your host machine’s BIOS/UEFI.

## Step 2: Install KVM, QEMU, and Libvirt
Install the core virtualization packages and network bridges for your Linux distribution:
Ubuntu / Debian:
```bash
sudo apt update
sudo apt install -y qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils virt-manager libvirt-dev
``` 
Fedora / RHEL:
```bash
sudo dnf install -y @virtualization libvirt-devel
```
Next, enable and start the libvirtd service:
```bash
sudo systemctl enable --now libvirtd
```

## Step 3: Configure User Permissions
By default, running virsh or managing libvirt requires root privileges. Add your local user to the libvirt and kvm groups so Vagrant can manage VMs without needing sudo every time:
```bash
sudo usermod -aG libvirt,kvm $USER
newgrp libvirt
```
Verify your setup by checking if 
```bash
virsh list --all
```
executes without permission errors.

## Step 4: Install Vagrant & the vagrant-libvirt Provider
> It’s best to download official Vagrant releases directly from HashiCorp rather than distro package managers to ensure compatibility.

Once Vagrant is installed, install the vagrant-libvirt plugin:
``` bash
# Install the plugin
vagrant plugin install vagrant-libvirt

# Set libvirt as your default Vagrant provider globally
export VAGRANT_DEFAULT_PROVIDER=libvirt
```

## Step 5: Quick Sanity Check
Before jumping into a multi-node Kubernetes cluster, run a quick sanity test to verify Vagrant can pull a libvirt box, spin it up, and SSH into it:
```bash
mkdir ~/vagrant-test && cd ~/vagrant-test
vagrant init debian/bookworm64
vagrant up
vagrant ssh
```
If you drop straight into a shell inside your Debian VM, your local hypervisor stack is fully operational!

Tear it down with 
```bash
vagrant destroy -f
```
and you're ready to write the Vagrantfile.

# Designing the Cluster Infrastructure with Vagrant
With KVM/libvirt operational, the next step is defining our cluster topology.

In cloud setups, provisioning scripts usually run curl commands inside each VM to fetch Kubernetes binaries and static configuration files. However, downloading heavy binaries across three virtual machines every time you re-provision is slow and prone to network timeouts.

## The Host-Staging Pattern
To keep local iterations lightning fast, my setup in [astrobot7/k8s-the-hardway](https://github.com/astrobot7/k8s-the-hardway) uses a host-side pre-staging strategy:

Download all required binaries (etcd, kube-apiserver, containerd, CNI plugins, etc.) once onto the host machine into a ./downloads folder.

Generate all TLS certificates and kubeconfig files locally into ./config (see the config/ structure in the repo).

Use Vagrant's file provisioner to inject these pre-computed assets directly into /tmp inside each VM during boot.

Use shell inline provisioners to move binaries into /usr/local/bin, write /etc/hosts entries, configure systemd units, and launch services.

## Cluster Topology & IP Assignment
The cluster uses a 1 control plane server + 2 worker nodes architecture attached to a dedicated private network (10.200.0.0/24):

| Node Name | Role | IP Address | RAM | vCPUs | Key Components |
|--|--|--|--|--|--|
| server |Control Plane | 10.200.0.10 | 1024 MB | 1 | etcd, kube-apiserver, kube-controller-manager, kube-scheduler |
| node-0 | Worker 0 | 10.200.0.11 |1024 MB | 1 | containerd, kubelet, kube-proxy, CNI Plugins |
| node-1 | Worker 1 | 10.200.0.12 | 1024 MB | 1 | containerd, kubelet, kube-proxy, CNI Plugins |

The complete vagrant file is available in the [repository](https://github.com/astrobot7/k8s-the-hardway/blob/main/vagrant/Vagrantfile)

# Automating the Lifecycle: Staging and Smoke Testing

While the Vagrantfile handles VM creation and service orchestration, managing host-side assets and verifying cluster health manually can quickly become tedious. To make the entire process repeatable, two shell scripts serve as the primary workflow entry points: setup.sh and smoke-test.sh.

```
                      +-------------------+
                      |     setup.sh      |
                      +---------+---------+
                                |
             1. Downloads binaries & CNI plugins
             2. Generates CA, TLS Certs & SAN IPs
             3. Creates Kubeconfigs & Encryption keys
             4. Provisions Server & Worker VMs
                                |
                                v
                      +---------------------+
                      |   Virtual Machines  |
                      |  (server, node-0/1) |
                      +---------+-----------+
                                |
             5. Starts etcd, Control Plane, Containerd
                                |
                                v
                      +-------------------+
                      |   smoke-test.sh   |
                      +-------------------+
             6. Validates Data Encryption at Rest
             7. Deploys Test Pods & Verifies Logs
             8. Tests Node-to-Node Pod Networking
```
## Phase 1: End-to-End Cluster Provisioning with setup.sh

Instead of making you manually generate certificates, download multi-megabyte binaries, and manually trigger vagrant up, running setup.sh handles the entire bootstrapping process from a single command:

* Downloads Dependencies: Pulls official static binaries for etcd, kube-apiserver, kube-controller-manager, kube-scheduler, kubelet, kube-proxy, containerd, runc, and core CNI plugins directly into ./downloads.

* Generates Public Key Infrastructure (PKI): Uses cfssl to generate the Certificate Authority (CA) and issues signed TLS certificates for all control plane components, admin clients, and worker nodes.

* Builds Kubeconfigs: Embeds the generated TLS certificates directly into .kubeconfig files for kube-controller-manager, kube-scheduler, kube-proxy, and worker nodes (node-0, node-1).

* Generates Encryption Config: Creates an encryption-config.yaml with a random secret key for encrypting secrets at rest in etcd.

* Launches the VMs (vagrant up): As its final step, setup.sh automatically invokes vagrant up, passing the pre-staged binaries, certificates, and systemd units into the libvirt hypervisor to boot the cluster.

To get a full Kubernetes cluster built entirely from source on your local machine, all it takes is:
```bash
./setup.sh
```

## Validating Cluster Health with smoke-test.sh

Once setup.sh finishes bringing up the VMs and systemd services are running, running smoke-test.sh executes a series of automated end-to-end checks against the live cluster:
1. Secret Encryption at Rest Verification

The script creates a test secret and inspects the raw key inside etcd over SSH to confirm it is stored encrypted rather than plain text:
```bash
# Create a test secret
kubectl create secret generic kubernetes-the-hard-way \
  --from-literal="mykey=mydata"

# Verify etcd stores it encrypted (prefixed with k8s:enc:aescbc:v1)
vagrant ssh server -- sudo etcdctl get /registry/secrets/default/kubernetes-the-hard-way
```

2. Pod Lifecycle & Workload Scheduling

It spins up an Nginx deployment, verifies that kube-scheduler places pods onto worker nodes, and validates container execution via kubectl exec:
```bash
kubectl create deployment nginx --image=nginx 
kubectl wait --for=condition=Ready pod -l app=nginx
```

3. Pod Networking
It creates a port-forward to the pod and verifies it is working by making a curl request:
```bash
POD_NAME=$(kubectl get pods -l app=nginx \
  -o jsonpath="{.items[0].metadata.name}")

kubectl port-forward $POD_NAME 8080:80 2>/dev/null 1>/dev/null &

curl --head http://127.0.0.1:8080
```
The output looks something like:
```
HTTP/1.1 200 OK
Server: nginx/1.31.3
Date: Thu, 23 Jul 2026 12:30:42 GMT
Content-Type: text/html
Content-Length: 896
Last-Modified: Wed, 15 Jul 2026 16:03:14 GMT
Connection: keep-alive
ETag: "6a57af42-380"
Accept-Ranges: bytes
```

Finally it tries to expose a NodePort and make a curl request:
```
kubectl expose deployment nginx \
  --port 80 --type NodePort

NODE_PORT=$(kubectl get svc nginx \
  --output=jsonpath='{range .spec.ports[0]}{.nodePort}')

NODE_NAME=$(kubectl get pods \
  -l app=nginx \
  -o jsonpath="{.items[0].spec.nodeName}")

curl -I http://${NODE_NAME}:${NODE_PORT}
```
The output looks something like:
```
service/nginx exposed
HTTP/1.1 200 OK
Server: nginx/1.31.3
Date: Thu, 23 Jul 2026 12:31:31 GMT
Content-Type: text/html
Content-Length: 896
Last-Modified: Wed, 15 Jul 2026 16:03:14 GMT
Connection: keep-alive
ETag: "6a57af42-380"
Accept-Ranges: bytes
```

## Cleanup
To cleanup the entire setup just run the following
```bash
cd vagrant
vagrant destroy -f
```

# Lessons Learned & Key Takeaways

Running through Kubernetes The Hard Way—especially adapted to run locally on Vagrant—demystifies the abstractions that tools like kubeadm, minikube, and managed cloud offerings (EKS/GKE) provide.

Here are the biggest technical takeaways from building the cluster from scratch:
1. kubectl is Just an HTTP Client

There is no hidden magic inside kubectl. It is simply a CLI wrapper that reads your local .kubeconfig file, extracts the embedded client certificate and private key, and sends HTTP/2 JSON payloads to the kube-apiserver endpoint (in our case, [https://server.kubernetes.local:6443](https://server.kubernetes.local:6443)). Every single command you run is just an authenticated REST API call.

2. Control Plane Components are Isolated Go Binaries

Before doing KTHW, it’s easy to imagine Kubernetes as a giant monolithic engine. In reality, kube-apiserver, kube-controller-manager, and kube-scheduler are completely independent Go binaries. They don't even talk to each other directly—kube-apiserver acts as the single central hub connected to etcd, while the controller-manager and scheduler continuously poll the API server to watch state changes and execute control loops.
3. TLS is the Backbone of K8s Security

Every component in Kubernetes—from kubelet reporting node status, to kube-proxy reading service endpoints, to etcd maintaining quorum—requires its own TLS client/server certificate pair.

> The Vagrant Gotcha: Forgetting to explicitly add local node IP addresses (10.200.0.10, 10.200.0.11, etc.) and setting up Subject Alternative Names (SANs) of your certificates with hostnames will break TLS handshakes immediately.

4. Pod IPs Are Virtual Magic

Service IPs (10.32.0.0/24) don't actually exist on physical network interfaces or virtual network adapters. They are virtual IP address rules managed by kube-proxy via iptables or IPVS kernel parameters. Meanwhile, Pod-to-Pod cross-node traffic depends on the br-netfilter kernel module (net.bridge.bridge-nf-call-iptables = 1) to route bridged traffic through netfilter rules correctly.

# Conclusion & Wrap Up

Building a bare-metal Kubernetes cluster on local VMs using Vagrant, libvirt, and KVM was one of the most rewarding engineering exercises I've completed. It transforms Kubernetes from a "black box" into a set of understandable, debuggable Linux processes.

When managed control planes break or local developmental networking behaves strangely, I no longer have to guess what's going wrong—I know exactly which systemd service, CNI config, or TLS cert to inspect.

Try It Yourself!

If you want to spin up this exact setup on your own Linux host machine without spending a dime on cloud providers, check out the complete code, configuration files, and automation scripts in my GitHub repository:

**GitHub Repository: astrobot7/k8s-the-hardway**

All it takes is cloning the repo and executing:
```bash
./setup.sh      # Downloads binaries, builds PKI, and boots VMs
./smoke-test.sh # Verifies encryption at rest & pod networking
```

Happy hacking!
