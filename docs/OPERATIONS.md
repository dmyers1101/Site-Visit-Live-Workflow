# Operations and maintenance

## Operating model

- GitHub owns the repo and documentation
- Google Cloud owns processing
- human review remains in the loop where approval matters

## Daily flow

1. confirm auth and env values
2. add/verify the video input
3. run the transcription and catalog stage
4. validate outputs
5. produce draft report output only after the data is ready

## Failure handling

When a component fails:
- review the latest logs
- check credentials and permissions
- validate the file input and expected format
- update the relevant runbook and service note

## Update path

Every operational change should also update the architecture, setup, and service docs.
