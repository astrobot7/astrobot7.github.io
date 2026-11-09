+++
date = '2026-11-10T01:45:00+05:30'
draft = false
title = 'Killing :latest in My Homelab: Digest-Pinned Images and a Self-Hosted Renovate on Docker Swarm'
author = 'Aswin KM'
url = '/renovate/'
+++

My homelab runs on a small Docker Swarm: a few ARM single-board computers and an x86 box spread across two locations, joined over Tailscale. Every stack lives in a single Git repository, and Portainer's GitOps sync deploys whatever lands on `main`. It is a setup I am genuinely happy with, except for one line that kept showing up in almost every stack file:

```yaml
image: traefik:latest
```

Out of roughly forty images, most were pinned to `latest`. A handful were pinned to a version, and a few had no tag at all, which is the same thing as `latest` with less honesty.

This post walks through how I replaced all of them with immutable, digest-pinned references and put a self-hosted Renovate bot on the swarm to keep them up to date through pull requests.

## Why :latest Is a Problem (Even at Home)

`latest` is not a version. It is a moving pointer that the image publisher can repoint at any time. In practice that meant three things for me:

* **Silent drift.** Two nodes pulling `traefik:latest` a week apart could run two different Traefik versions, and nothing in Git would tell me.
* **Accidental upgrades.** Any redeploy, a node reboot, or Swarm rescheduling a task could pull a new major version I had never looked at.
* **No rollback target.** When something broke, "go back to the previous version" had no meaning, because the previous version was never written down anywhere.

Git was supposed to be the source of truth for my infrastructure, but for the most important part of every service, the binary actually running, it wasn't.

## Pinning by Digest, Not Just by Tag

The fix is to reference images by content digest. A digest is the SHA-256 of the image manifest, so it can never point at different bytes. I kept the tag in front of it for readability:

```yaml
image: traefik:latest@sha256:f4bb143d1135a579b630ed491e17ec50f6f7c9c6a30585ff3d385471d2a86f5a
```

When both are present, Docker ignores the tag and pulls exactly the digest. The tag is purely documentation, and it also tells Renovate which tag to track for future updates.

One detail matters a lot on a mixed-architecture cluster. My nodes are a mix of `arm64` and `amd64`, so the digest has to be the **multi-arch index digest**, not the digest of one platform's manifest. Pin the `linux/arm64` manifest and the x86 node simply can't run the service. `docker buildx imagetools inspect` returns the index digest, and it only talks to the registry, so it works without a local Docker daemon:

```bash
docker buildx imagetools inspect traefik:latest --format '{{json .Manifest.Digest}}'
# "sha256:f4bb143d1135a579b630ed491e17ec50f6f7c9c6a30585ff3d385471d2a86f5a"
```

I collected every `image:` line across the repository, resolved each one once, and rewrote the files with a small script. Untagged images became `:latest@sha256:...` so the intent is explicit. Commented-out services were left alone, and the one image hosted in my private registry was skipped because nothing outside my network can read it.

Pinning on its own only trades one problem for another: now nothing ever updates. That's where Renovate comes in.

## Teaching Renovate About Swarm Stack Files

[Renovate](https://docs.renovatebot.com/) understands Compose files out of the box, but its default file pattern only matches names like `docker-compose.yml` and `compose.yaml`. Swarm convention is `docker-stack.yml`, so without extra config Renovate simply never looks at most of my repository. Here is the repo-level `renovate.json`:

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended", "docker:pinDigests"],
  "timezone": "Europe/Stockholm",
  "docker-compose": {
    "managerFilePatterns": [
      "/(^|/)docker-(compose|stack)[^/]*\\.ya?ml$/",
      "/(^|/)hwaccel\\.[^/]+\\.ya?ml$/"
    ]
  },
  "packageRules": [
    {
      "description": "Floating tags only ever get digest bumps; batch them into one weekly PR",
      "matchUpdateTypes": ["digest"],
      "groupName": "image digests",
      "schedule": ["before 6am on monday"]
    },
    {
      "description": "Immich server and machine-learning must run the same version",
      "matchPackageNames": ["ghcr.io/immich-app/**"],
      "groupName": "immich"
    },
    {
      "description": "Postgres major upgrades need a dump/restore; never propose them",
      "matchPackageNames": ["pgvector/pgvector"],
      "matchUpdateTypes": ["major"],
      "enabled": false
    },
    {
      "description": "Private registry: Renovate has no credentials for it",
      "matchPackageNames": ["registry.aswinkm.dev/**"],
      "enabled": false
    }
  ]
}
```

A few decisions worth explaining:

* **`docker:pinDigests`** makes Renovate keep the `tag@digest` format. Any image added later without a digest gets a "pin" PR automatically.
* **Weekly digest batch.** Images like the linuxserver.io ones get rebuilt constantly. Without grouping, I'd get a dozen tiny PRs a week. Now every floating-tag refresh arrives as one PR on Monday morning.
* **Immich as a group.** The server and the machine-learning container must run the same release, so they're updated together in a single PR.
* **No Postgres majors.** A tag like `pg16` looks like a version to Renovate, so it would happily propose `pg17`. A major Postgres upgrade needs a dump and restore, which is not something I want a bot to suggest casually.

Before trusting it, I validated the config and ran a dry extraction locally:

```bash
npx --package renovate -- renovate-config-validator --strict renovate.json
RENOVATE_CONFIG_FILE=$PWD/renovate.json \
  npx renovate --platform=local --dry-run=extract --report-type=file --report-path=report.json
```

One gotcha here: `--platform=local` only sees files tracked by Git. My new `renovate.json` was still uncommitted, so the first dry run silently ignored it and matched just 6 files. Passing the same file in as global config (`RENOVATE_CONFIG_FILE`) got around that, and the second run matched all 26 stack files and 43 images, every one with a digest except the private image.

## Self-Hosting Renovate on Swarm

The hosted Mend app is the easy route, but I wanted the bot to live on the same cluster it maintains. The official `renovate/renovate` image is a CLI that runs once and exits, and Swarm has no CronJob equivalent. The simplest reliable answer is a loop inside the container:

```yaml
services:
  renovate:
    image: renovate/renovate:44@sha256:0405454d925558d5a2368ddb1d8318244e96c73974697a5264a4d1977a277598
    command:
      - bash
      - -c
      - |
        while true; do
          if node /usr/src/app/github-app-token.js /tmp/renovate-auth.env; then
            ( . /tmp/renovate-auth.env && renovate ) || echo "renovate run failed (exit $$?)"
            rm -f /tmp/renovate-auth.env
          else
            echo "skipping run: could not get a GitHub App token"
          fi
          sleep "$$RENOVATE_INTERVAL"
        done
    environment:
      - RENOVATE_CONFIG_FILE=/usr/src/app/config.js
      - RENOVATE_INTERVAL=3600
    configs:
      - source: renovate-config
        target: /usr/src/app/config.js
      - source: renovate-app-token
        target: /usr/src/app/github-app-token.js
    secrets:
      - source: renovate-app-private-key
        mode: 0400
        uid: "12021"
    deploy:
      placement:
        constraints:
          - node.labels.host==pandora
      resources:
        limits:
          memory: 2G
```

The global config is tiny, because everything repository-specific lives in `renovate.json`:

```js
module.exports = {
  platform: 'github',
  repositories: ['astrobot7/docker-compose'],
  onboarding: false,          // renovate.json is already committed
  requireConfig: 'required',
  repositoryCache: 'enabled',
  persistRepoData: true,
  platformCommit: 'enabled',  // commit through the API: attributed to the app, shown as Verified
};
```

Both files are mounted as Swarm configs. Swarm configs are immutable, so my repo already had a small CI step that appends a short content hash to every config name (`renovate-config-638242eb`). Change the file, and the hash changes, so Swarm creates a new config and rolls the service, with no manual cleanup.

I also hit one surprise on the first validation run: Renovate printed *"Renovate versions older than the latest major version are unsupported."* I'd reached for version 43 from memory, and 44 had been out for months. Pinning by digest doesn't protect you from pinning to the wrong thing in the first place.

## Authentication: Why I Ended Up With a GitHub App

Renovate needs to clone the repo, push branches, open pull requests, and maintain its Dependency Dashboard issue. I went through three options:

1. **A personal access token.** It works, but it's tied to my personal account, every PR shows up as me, and it needs rotating by hand.
2. **A deploy key.** It's tempting, since it's scoped to one repo, but it's SSH-only. A deploy key can push branches but can't call the GitHub API, so it can't open a PR or touch an issue. It's a non-starter on its own.
3. **A GitHub App.** It's scoped to only the repositories it's installed on, it's not tied to my account, its tokens expire after an hour, and PRs come from `<app>[bot]`.

The App won, with one wrinkle. I dug into Renovate's source to see how much it handles natively. It does support App tokens: hand it a token starting with `ghs_` and it switches to App mode, derives the `[bot]` git author, and discovers repositories through the installation. What it can't do is *mint* that token from the App's private key. Something has to do that exchange before every run.

So I wrote that piece: about 50 lines of Node with no dependencies, using only `crypto` and `fetch`, which the Renovate image already ships:

```js
function appJwt() {
  const now = Math.floor(Date.now() / 1000);
  const body = `${b64url({ alg: 'RS256', typ: 'JWT' })}.${b64url({ iat: now - 60, exp: now + 540, iss: GITHUB_APP_ID })}`;
  const sig = crypto.sign('RSA-SHA256', Buffer.from(body), fs.readFileSync(GITHUB_APP_KEY_FILE));
  return `${body}.${sig.toString('base64url')}`;
}

const jwt = appJwt();
const inst = await gh(`/repos/${GITHUB_REPOSITORY}/installation`, jwt);
const { token } = await gh(`/app/installations/${inst.id}/access_tokens`, jwt, 'POST');
// write RENOVATE_TOKEN / RENOVATE_GITHUB_COM_TOKEN exports for the run loop
```

The flow on every iteration is:

1. Sign a 9-minute JWT with the App's private key, which comes from a Swarm secret readable only by Renovate's uid.
2. Look up the App's installation on the repository.
3. Exchange the JWT for a one-hour installation token.
4. Run Renovate with that token, then delete it.

If the exchange fails, the loop logs it and skips the run instead of crash-looping.

The App's permissions are deliberately narrow: read and write on Contents, Pull requests, Issues and Workflows; read-only on Checks and Commit statuses; no webhook, since Renovate polls. With `platformCommit` enabled, Renovate creates its commits through the GitHub API rather than `git push`, so they show up as Verified and attributed to the App.

## Deploying It (and a Portainer Surprise)

The stack is deployed like everything else: a Portainer Git stack pointing at `main`, with GitOps auto-update enabled. The first run looked exactly how I hoped:

```text
github app <app>: installation <id> token issued
 INFO: Repository started (repository=astrobot7/docker-compose)
 INFO: Dependency extraction complete
 INFO: PR created (branch=renovate/ghcr.io-homarr-labs-homarr-1.x)
 INFO: PR created (branch=renovate/linuxserver-qbittorrent-5.x)
 INFO: Issue created
 INFO: Repository finished
```

Within minutes there were two real update PRs, Homarr `v1.50.1 → v1.77.2` and qBittorrent `5.1.4 → 5.3.0`, plus the Dependency Dashboard issue listing everything else Renovate knows about.

The surprise came later, when merged PRs stopped rolling out. In Portainer 2.45, GitOps polling is driven per **source**, not per stack. A source is a repository URL plus its credentials, and the stack-level "auto-update every 1m" toggle doesn't start anything by itself. The repository's GitHub URL had changed at some point, and GitHub quietly redirects the old one. The older stacks were attached to a source using the old URL, which was polling happily. The newer stacks, Renovate's included, used the new URL. They had silently ended up on a second source that had no polling interval at all, so they had never been polled once.

The lesson I'm taking from this: once you automate updates, check the delivery half of the pipeline as carefully as the proposing half. A Renovate PR that merges but never deploys is worse than no PR at all, because it makes Git lie about what's running.

## Lessons Learned

* **Pin the index digest, not a platform digest**, or your mixed-arch cluster will tell you about it the hard way.
* **Renovate's default Compose pattern doesn't match `docker-stack.yml`.** If you run Swarm, `managerFilePatterns` is the first thing to configure.
* **Group the noise.** Weekly batched digest PRs turn a firehose into one review a week.
* **Prefer a GitHub App over a PAT**, but expect to mint the installation token yourself when self-hosting.
* **Dry-run before deploying.** `renovate-config-validator` and `--dry-run=extract` caught a config that would otherwise have quietly matched only a quarter of my files.
* **Check how updates actually get deployed**, not just whether they get proposed.

The repository is now honest about what runs on every node: every image is an immutable reference, and every change to one arrives as a reviewable pull request. My homelab finally behaves like the GitOps setup I pretended it was.
