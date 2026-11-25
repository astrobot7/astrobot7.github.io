+++
date = '2026-11-25T14:15:00+05:30'
draft = false
title = 'Homelab Chronicles: Keeping Things Up to Date'
author = 'Aswin KM'
featuredImage = '/images/covers/homelab-chronicles-keeping-things-up-to-date.svg'
featuredImagePreview = '/images/covers/homelab-chronicles-keeping-things-up-to-date.svg'
tags = ['kubernetes', 'flux', 'renovate', 'gitops', 'homelab']
categories = ['Homelab', 'Kubernetes']
url = '/posts/keeping-things-up-to-date/'
+++

A couple of weeks ago I [wrote about](/posts/renovate/) pinning every image in my homelab by digest and running a self-hosted Renovate on Docker Swarm. Since then the homelab has moved to k3s, and the update loop moved with it. Flux deploys from Git, Renovate runs as a CronJob, and [konflate](https://github.com/home-operations/konflate) shows me what each pull request will actually change in the cluster before I approve it.

## Flux, Trimmed Down

The nodes are small ARM boards, so memory decides most things. I don't use Helm or Flux's notifications, so I installed only the two controllers I need and committed the output, which lets Flux manage its own installation:

```bash
flux install --components=source-controller,kustomize-controller --export > k8s/flux-system/gotk-components.yaml
```

Each controller sat at about 90 MB. A patch gives them a 192Mi limit and sets `GOMEMLIMIT` to roughly 80% of it, so the Go garbage collector works harder before the kernel OOM-kills the pod. Flux sets it to 100% of the limit by default.

The repo is split into one directory per node, and each directory is one Flux `Kustomization`, with operators and CRDs in a separate one that the others depend on. Secrets are SOPS files encrypted with age, and Flux decrypts them on apply.

One gotcha cost me a minute of downtime. The top-level `flux-system` Kustomization manages the per-node ones, so when I set `suspend: true` on one of them during a migration, the next reconcile restored it from Git and the change shipped anyway. To hold something back, suspend the parent as well, or annotate the single object you're changing by hand with `kustomize.toolkit.fluxcd.io/reconcile: disabled`.

## Renovate as a CronJob

On Swarm, Renovate ran in a `while true` loop because Swarm has no scheduled jobs. On Kubernetes it's a CronJob that runs hourly, with `concurrencyPolicy: Forbid`. It still authenticates as a GitHub App, minting a short-lived installation token before each run. The node only gives up the memory for the few minutes a run takes.

Renovate's managers now cover more than container images:

- The `kubernetes` manager reads every `image:` under `k8s/`.
- The `flux` manager regenerates `gotk-components.yaml` when Flux releases, keeping the same component list.
- A regex manager tracks the k3s version pinned in Ansible, with a versioning regex that ignores release candidates. Merging only changes the pin; I still run the upgrade by hand, server first.
- Another regex manager reads a file of installed apt package versions per node, written after each OS upgrade. A PR there tells me a node has updates waiting. I never merge it, and the next upgrade rewrites the file and closes the PR.

Two kinds of updates are switched off. Vendored release bundles (operators shipped as one big manifest) are updated by re-vendoring the release, because their images move together with their CRDs. And database major versions need a planned upgrade, so Renovate never proposes them.

One more rule came from a mistake. An image I use has old tags from a versioning scheme it dropped years ago, and they sort above the current versions. Renovate proposed one as an upgrade and I merged it, downgrading the app by several years. An `allowedVersions` rule blocks those tags now. The PR had looked fine: a one-line diff, a valid tag, a resolving digest, and green checks.

## Approving Is Merging

The repo is private on GitHub's free plan, so there's no branch protection or native auto-merge. A small workflow fills in: when I approve a Renovate PR, it waits for every check on that commit to pass and squash-merges it with `--match-head-commit`. If the branch moved after my approval, the merge fails and I approve again. CI renders every kustomization and validates it with kubeconform. CI never applies anything; only Flux touches the cluster.

## konflate: Review What Flux Will Apply

The weak step in that loop was my approval, since all I saw was a one-line YAML diff. konflate lists the open PRs of a repository, renders each one through Flux the way the cluster would (overlays, components, patches), and diffs the result against `main`. A change to a shared base shows up as changes to every Deployment that uses it, and a digest bump shows up as exactly one changed `image:` line.

A few notes if you run it yourself:

- It authenticates as a GitHub App. I reused Renovate's App and turned write-back off, so it never comments on PRs or sets statuses.
- It has no login of its own and shows your rendered infrastructure, so put it behind an auth proxy.
- It never needs the Kubernetes API, so turn off `automountServiceAccountToken`. An `emptyDir` cache is enough when the repo has no Helm charts.
- Set `enableServiceLinks: false`. A Service named `konflate` makes Kubernetes inject `KONFLATE_PORT=tcp://...`, which konflate reads as its listen port, fails to parse, and exits.

## The Loop Now

1. Renovate opens a PR.
2. CI validates the rendered manifests.
3. konflate shows what would change in the cluster.
4. I read that diff and approve.
5. The workflow merges the approved commit, and Flux applies it within a minute.

Only step 4 needs me, and I'm now reviewing rendered manifests instead of a one-line text change.
