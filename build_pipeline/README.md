
# Amazon SageMaker Drift Detection

This folder contains the code to create a model build pipeline that includes a baseline and training job

## Build Pipeline

This build pipeline contains a few stages.

1. **Source**: Pull the latest deployment configuration from AWS CodeCommit repository.
1. **Build**: AWS CodeBuild job to create or the SageMaker pipeline definition
2. **Pipeline**: Run the AWS CloudFormation stack to create/update the SageMaker pipeline.

## Testing

Once you have created a SageMaker Project, you can test the **Build** stage.

### Build Stage

Export the environment variables for the `SAGEMAKER_PROJECT_NAME` and `SAGEMAKER_PROJECT_ID` created by your SageMaker Project cloud formation.  Then run the `python` command:

```
export SAGEMAKER_PROJECT_NAME="<<project_name>>"
export SAGEMAKER_PROJECT_ID="<<project_id>>"
export AWS_REGION="<<region>>"
export ARTIFACT_BUCKET="sagemaker-project-<<project_id>>-build-<<region>>"
export SAGEMAKER_PIPELINE_ROLE_ARN="<<service_catalog_product_use_role>>"
export SAGEMAKER_PIPELINE_NAME="<<project_name>>-pipeline"
export SAGEMAKER_PIPELINE_DESCRIPTION="SageMaker Drift Detection Pipeline"
python app.py
```