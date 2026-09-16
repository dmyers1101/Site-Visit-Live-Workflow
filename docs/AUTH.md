# Authentication and authorization

## GitHub

GitHub is the live source of truth across devices.

Requirements:
- a repo for the live build
- a consistent branch policy
- secure access for contributors who need to update the current pipeline

## Google Cloud

Google Cloud handles processing and output generation.

Requirements:
- dedicated project for the live workflow
- service account with least-privilege permissions
- secure credentials store and environment configuration
- documented permission changes when a new service or export path is added

## Security rules

- never commit secrets
- keep credentials in environment-controlled storage
- use a service account instead of personal credentials when possible
- update this file when auth or permissions change
