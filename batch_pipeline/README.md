
# Amazon SageMaker Drift Detection

This folder contains the code to create a batch pipeline that includes a SageMaker Transform Job and [Model Monitor](https://aws.amazon.com/sagemaker/model-monitor/) Processing Job.

## Build Pipeline

The model build pipeline contains three stages:
1. Source: This stage pulls the latest code from the **AWS CodeCommit** repository.
2. Build: The **AWS CodeBuild** action creates an Amazon SageMaker Pipeline definition and stores this definition as a JSON on S3. Take a look at the pipeline definition in the CodeCommit repository `pipelines/pipeline.py`. The build also creates an **AWS CloudFormation** template using the AWS CDK - take a look at the respective CDK App `app.py`.
3. Pipeline: This stage creates the **AWS CloudFormation** stack that has been synthesized in the  Build stage to create/update the Amazon SageMaker Pipeline. 

The batch transform pipeline will be triggered when a new file is uploaded to S3 or on a regular schedule.