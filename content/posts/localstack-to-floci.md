+++
date = '2026-07-17T19:25:23+05:30'
draft = false
title = 'Why I Dumped LocalStack for Floci: Am I just saving a quick buck?'
author= 'Aswin KM'
+++

As an infrastructure engineer who has mainly worked on Google Cloud Platform on a professional level, It was important to me to be able to be cloud agnostic and have relevant experience with other cloud providers. Amazon Web Services being the biggest player out in the game, Initially, I tried to get my hands dirty with the free-tier provided by AWS. Alas, I ran into resource restrictions and paywalls as soon as I started playing around with it.

As an engineer, my initial though was that I don't need an entire enterprise level production system to verify if my Terraform syntax was sound of if my modules are wired correctly. As engineers, our default state when faced with this kind of environment friction is to step back and analyze the protocol. I realized that at the end of the day, an AWS SDK, CLI tool, or IaC binary is just making standard HTTP API calls to an endpoint. 

As much as I would like to build an emulator from scratch, I decided to keep it simple and see if there is an emulator out there which provides me with the basic functionalies I need. If it supports docker for emulating some services, or has a plugin system then it would be a match made in heaven.

Enter LocalStack.

## LocalStack and good old days

Discovering LocalStack and running `docker compose up` and firing aws-cli commands felt like a cheatcode for cloud engineers. LocalStack supported majority of aws services that I wanted to experiment with. LocalStack acted as a perfect black box for the AWS api control plane. It exposed the exact wire protocols and endpoints as the standard aws-cli, SDKs and terraform provider expected.

I could setup the terraform provider as simple as the following once LocalStack is up and running.
```hcl
provider "aws" {
  region                      = "us-east-1"
  access_key                  = "mock_key"
  secret_key                  = "mock_secret"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  endpoints {
    s3       = "http://localhost:4566"
    dynamodb = "http://localhost:4566"
    lambda   = "http://localhost:4566"
  }
}
```

This allowed me to build my own terraform modules, test existing terraform modules and debug like I would do in an actual cloud setup. I could run `terraform apply` and watch LocalStack spin up a mock infrastructure all without leaving my laptop. I could easily tear-down the entire infrastructure by a simple `docker compose down` command. It allowed me to aggressively experiment, break things, and intentionally introduce misconfigurations—such as malformed IAM policies or bad DynamoDB global secondary indexes (GSIs)—just to see how the API responded.

An additional feature that LocalStack provided was the ability to run workloads like AWS Lambda be leveraging Docker under the hood to handle execution. This elevated the relevance of the tool from being a static mockserver to a very usable cloud emulator.

When my code triggered a Lambda function, LocalStack orchestrated a runtime container, passed the event payload, and returned the execution logs.

## What went wrong?
For a long time, the LocalStack workflow felt like it could never be replaced. But as my infrastructure grew more complex and integrated into automated testing pipelines, the cracks in the developer experience began to widen.

I started noticing the high resource utilization by the python process. It was negligible when I was running it locally, but when I started to incorporate it with my Github Actions pipelines, It became a pain-point since LocalStack, at the end of the day is a massive python runtime with size of ~1GB. Pulling and running the container would waste precious github actions runtime. 

Then came the operational feature gates. As I moved beyond simple S3 buckets into higher-fidelity infrastructure testing, I hit LocalStack’s commercial wall. Crucial capabilities for an infrastructure engineer—like advanced persistence, snapshotting state, or running specific multi-account architectures—were locked behind their proprietary Pro and Enterprise tiers.

But the definitive breaking point arrived in March 2026.

LocalStack announced a foundational shift in its distribution model. They officially consolidated their images into a single, unified container that strictly requires an account registration and a mandatory LOCALSTACK_AUTH_TOKEN to pull or run—even for the free tier, and even inside CI pipelines.

```
Error: LocalStack container failed to initialize. 
Missing required environment variable: LOCALSTACK_AUTH_TOKEN
```

This felt like deja-vu, I started using LocalStack to escape the public cloud paywalls, , rigid resource gatekeeping, and the friction of API keys and credential management. Suddenly, my local emulation layer was demanding the exact same compliance overhead.

## Enter Floci
I started looking for alternatives to LocalStack, I was purusing through the underbelly of Reddit when Floci caught my eyes. I didn't want just another fork of LocalStack, I wanted something that was less resource hungry and light enough to run in my Github Actions.

[Floci](https://floci.io/floci) is a lightweight drop-in replacement for LocalStack running via the same port be default. This means, I can just swap it into my existing terraform configurations or application code without a single line of code change.

LocalStack’s heavy memory footprint and multi-second startup lag are largely a byproduct of its runtime environment. Floci throws out that traditional playbook by leveraging a highly modern, cloud-native stack: Quarkus and GraalVM Native Image.

I'll talk more about Floci architecture and how I'm using floci in actual development setup in future posts.
