
# Amazon SageMaker Drift Detection
0
This folder contains the CDK infrastructure to deploy the SageMaker endpoint with model monitoring

## Deployment Pipeline

This deployment pipeline contains a few stages.

1. **Source**: Pull the latest deployment configuration from AWS CodeCommit repository.
1. **Build**: AWS CodeBuild job to create the AWS CloudFormation template for deploying the endpoint.
    - Query the Amazon SageMaker project to get the top approved models.
    - Use the AWS CDK to create a CFN stack to deploy multi-variant SageMaker Endpoint.
2. **Deploy**: Run the AWS CloudFormation stack to create/update the SageMaker endpoint.

## Testing

Once you have created a SageMaker Project, you can test the **Build** stage and **Register** events locally by setting some environment variables.

### Build Stage

Export the environment variables for the `SAGEMAKER_PROJECT_NAME` and `SAGEMAKER_PROJECT_ID` created by your SageMaker Project cloud formation.  Then run the `cdk synth` command:

```
export SAGEMAKER_PROJECT_NAME="<<project_name>>"
export SAGEMAKER_PROJECT_ID="<<project_id>>"
cdk synth
```